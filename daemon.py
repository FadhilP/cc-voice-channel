import functools
import os
import queue
import secrets
import threading
import urllib.request
import winsound
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import keyboard
import numpy as np
import sounddevice as sd
import torch

HOTKEY = "ctrl+alt+space"
STT_REPO = "kyutai/stt-2.6b-en"
STT_DEVICE = "cuda"
TTS_VOICE = "mary"
CHANNEL_URL = "http://127.0.0.1:8788/"
SPEAK_PORT = 8789
SAMPLE_RATE = 24000  # Kyutai STT expects 24 kHz mono
SPEECH_RMS = 0.01  # Tune to your mic: 30 ms frames louder than this count as speech.
MIN_SPEECH_SECONDS = 0.3
TOKEN_PATH = Path.home() / ".cc-voice-channel" / "token"


def load_token():
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with TOKEN_PATH.open("x") as file:
            file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return TOKEN_PATH.read_text().strip()


def is_authorized(headers):
    if headers.get("Origin") is not None:
        return False
    return headers.get("X-Voice-Token") == token


class Recorder:
    def __init__(self):
        self.chunks = []
        self.stream = None

    def toggle(self):
        if self.stream is None:
            self.start()
        else:
            self.stop()

    def start(self):
        self.chunks = []
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=self.on_audio
        )
        self.stream.start()
        winsound.Beep(880, 120)

    def on_audio(self, data, frames, time, status):
        self.chunks.append(data.copy())

    def stop(self):
        self.stream.stop()
        self.stream.close()
        self.stream = None
        winsound.Beep(440, 120)
        if not self.chunks:
            return
        audio = np.concatenate(self.chunks)[:, 0]
        threading.Thread(target=send_transcript, args=(audio,), daemon=True).start()


@torch.no_grad()
def transcribe(audio):
    pcm = torch.from_numpy(audio).to(STT_DEVICE)[None, None]
    # The model emits text with a delay, so trailing silence flushes the last words.
    pad_left = int(stt_config.get("audio_silence_prefix_seconds", 0.0) * SAMPLE_RATE)
    pad_right = int((stt_config.get("audio_delay_seconds", 0.0) + 1.0) * SAMPLE_RATE)
    pcm = torch.nn.functional.pad(pcm, (pad_left, pad_right))
    pieces = []
    with stt_lock, mimi.streaming(1), lm_gen.streaming(1):
        for chunk in pcm.split(frame_size, dim=2):
            if chunk.shape[-1] < frame_size:
                break
            tokens = lm_gen.step(mimi.encode(chunk))
            if tokens is None:
                continue
            token = tokens[0, 0].item()
            if token not in (0, 3):  # padding tokens
                pieces.append(text_tokenizer.id_to_piece(token))
    return "".join(pieces).replace("▁", " ").strip()


def speech_seconds(audio):
    frame = SAMPLE_RATE * 30 // 1000
    frames = audio[: len(audio) // frame * frame].reshape(-1, frame)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    return np.count_nonzero(rms > SPEECH_RMS) * frame / SAMPLE_RATE


def send_transcript(audio):
    # The model invents words from silence, so skip recordings without speech.
    seconds = speech_seconds(audio)
    if seconds < MIN_SPEECH_SECONDS:
        print(f"No speech detected ({seconds:.2f} s above SPEECH_RMS={SPEECH_RMS}).")
        return
    text = transcribe(audio)
    if not text:
        return
    print(f"> {text}")
    request = urllib.request.Request(
        CHANNEL_URL, data=text.encode(), headers={"X-Voice-Token": token}, method="POST"
    )
    try:
        urllib.request.urlopen(request, timeout=5)
    except OSError as error:
        print(f"Channel unreachable. Is Claude Code running with the voice channel? ({error})")
        winsound.Beep(220, 400)


def speak_worker():
    while True:
        text = speech_queue.get()
        try:
            audio = tts.generate_audio(voice, text)
            sd.play(audio.numpy(), tts.sample_rate)
            sd.wait()
        except Exception as error:
            print(f"TTS failed: {error}")


class SpeakHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/speak" or not is_authorized(self.headers):
            self.send_response(403)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        speech_queue.put(self.rfile.read(length).decode())
        self.send_response(202)
        self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    # torch.compile needs Triton, which has no official Windows build.
    os.environ["NO_TORCH_COMPILE"] = "1"
    import pocket_tts.utils.config
    from moshi.models import LMGen, loaders
    from pocket_tts import TTSModel

    # pocket-tts reads its YAML config without encoding=, which breaks on Windows code pages.
    pocket_tts.utils.config.open = functools.partial(open, encoding="utf-8")

    token = load_token()
    print("Loading models...")
    checkpoint = loaders.CheckpointInfo.from_hf_repo(STT_REPO)
    mimi = checkpoint.get_mimi(device=STT_DEVICE)
    text_tokenizer = checkpoint.get_text_tokenizer()
    lm_gen = LMGen(checkpoint.get_moshi(device=STT_DEVICE), **checkpoint.lm_gen_config)
    stt_config = checkpoint.stt_config
    frame_size = int(mimi.sample_rate / mimi.frame_rate)
    stt_lock = threading.Lock()
    # The first pass on CUDA is slow, so do it now instead of on the first dictation.
    transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))
    tts =TTSModel.load_model()
    voice = tts.get_state_for_audio_prompt(TTS_VOICE)
    speech_queue = queue.Queue()
    threading.Thread(target=speak_worker, daemon=True).start()

    recorder = Recorder()
    keyboard.add_hotkey(HOTKEY, recorder.toggle)
    print(f"Ready. Press {HOTKEY} to start and stop dictation.")
    ThreadingHTTPServer(("127.0.0.1", SPEAK_PORT), SpeakHandler).serve_forever()
