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

HOTKEY = "f13"
CANCEL_HOTKEY = "f14"
STT_REPO = "Qwen/Qwen3-ASR-1.7B-hf"
STT_DEVICE = "cuda"
TTS_REPO = "hexgrad/Kokoro-82M"
TTS_VOICE = "af_heart"
TTS_SAMPLE_RATE = 24000
CHANNEL_URL = "http://127.0.0.1:8788/"
SPEAK_PORT = 8789
SAMPLE_RATE = 16000  # Qwen3-ASR expects 16 kHz mono
SPEECH_RMS = 0.01  # Tune to your mic: 30 ms frames louder than this count as speech.
MIN_SPEECH_SECONDS = 0.3
TOKEN_PATH = Path.home() / ".cc-voice-channel" / "token"
VOCABULARY_PATH = Path.home() / ".cc-voice-channel" / "vocabulary.txt"


def load_token():
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with TOKEN_PATH.open("x") as file:
            file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return TOKEN_PATH.read_text().strip()


def load_stt_prompt():
    if not VOCABULARY_PATH.exists():
        return None
    lines = VOCABULARY_PATH.read_text(encoding="utf-8").splitlines()
    terms = [line.strip() for line in lines if line.strip()]
    if not terms:
        return None
    return "Vocabulary: " + ", ".join(terms)


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

    def close_stream(self):
        self.stream.stop()
        self.stream.close()
        self.stream = None

    def stop(self):
        self.close_stream()
        winsound.Beep(440, 120)
        if not self.chunks:
            return
        audio = np.concatenate(self.chunks)[:, 0]
        threading.Thread(target=send_transcript, args=(audio,), daemon=True).start()

    def cancel(self):
        if self.stream is None:
            return
        self.close_stream()
        self.chunks = []
        winsound.Beep(330, 80)
        winsound.Beep(330, 80)
        print("Dictation cancelled.")


@torch.no_grad()
def transcribe(audio):
    with stt_lock:
        inputs = processor.apply_transcription_request(
            audio=audio, prompt=stt_prompt, language="English"
        )
        inputs = inputs.to(stt_model.device, stt_model.dtype)
        output = stt_model.generate(**inputs, max_new_tokens=1024)
    new_tokens = output[:, inputs["input_ids"].shape[1] :]
    text = processor.decode(new_tokens, return_format="transcription_only")[0].strip()
    # On near-silence the model can repeat the vocabulary prompt back.
    if text.startswith("Vocabulary:"):
        return ""
    return text


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
            chunks = [audio.numpy() for _, _, audio in tts(text, voice=TTS_VOICE)]
            sd.play(np.concatenate(chunks), TTS_SAMPLE_RATE)
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
    from kokoro import KPipeline
    from transformers import AutoModelForMultimodalLM, AutoProcessor

    token = load_token()
    print("Loading models...")
    processor = AutoProcessor.from_pretrained(STT_REPO)
    stt_model = AutoModelForMultimodalLM.from_pretrained(
        STT_REPO, device_map=STT_DEVICE, dtype=torch.bfloat16
    )
    stt_prompt = load_stt_prompt()
    stt_lock = threading.Lock()
    # The first pass on CUDA is slow, so do it now instead of on the first dictation.
    transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))
    # Kokoro picks the language from the first letter of the voice name.
    tts = KPipeline(lang_code=TTS_VOICE[0], repo_id=TTS_REPO)
    speech_queue = queue.Queue()
    threading.Thread(target=speak_worker, daemon=True).start()

    recorder = Recorder()
    keyboard.add_hotkey(HOTKEY, recorder.toggle)
    keyboard.add_hotkey(CANCEL_HOTKEY, recorder.cancel)
    print(f"Ready. Press {HOTKEY} to start and stop dictation, {CANCEL_HOTKEY} to cancel it.")
    ThreadingHTTPServer(("127.0.0.1", SPEAK_PORT), SpeakHandler).serve_forever()
