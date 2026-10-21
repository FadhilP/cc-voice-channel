import numpy as np

from daemon import MIN_SPEECH_SECONDS, SAMPLE_RATE, speech_seconds

rng = np.random.default_rng(0)
second = np.arange(SAMPLE_RATE) / SAMPLE_RATE

silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
room_noise = (0.002 * rng.standard_normal(SAMPLE_RATE)).astype(np.float32)
key_click = room_noise.copy()
key_click[:SAMPLE_RATE // 50] = 0.5  # 20 ms
voice = (0.1 * np.sin(2 * np.pi * 200 * second)).astype(np.float32)

assert speech_seconds(silence) == 0
assert speech_seconds(room_noise) < MIN_SPEECH_SECONDS
assert speech_seconds(key_click) < MIN_SPEECH_SECONDS
assert speech_seconds(voice) > 0.9
assert speech_seconds(silence[:10]) == 0
print("ok")
