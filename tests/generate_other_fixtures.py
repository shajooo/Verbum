import os
import wave
import numpy as np

fixtures_dir = r"c:\Projects\Verbus\tests\fixtures\audio"
os.makedirs(fixtures_dir, exist_ok=True)

# 4. Silence (3 seconds, 16kHz, 16-bit mono)
sample_rate = 16000
duration = 3.0
num_samples = int(sample_rate * duration)
silence_samples = np.zeros(num_samples, dtype=np.int16)

silence_path = os.path.join(fixtures_dir, "silence.wav")
with wave.open(silence_path, "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sample_rate)
    wf.writeframes(silence_samples.tobytes())

# 5. Noise (3 seconds, low amplitude white noise)
noise_samples = (np.random.normal(0, 0.05, num_samples) * 32767).astype(np.int16)
noise_path = os.path.join(fixtures_dir, "noise.wav")
with wave.open(noise_path, "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sample_rate)
    wf.writeframes(noise_samples.tobytes())

# 6. Corrupt file (truncated invalid wav)
corrupt_path = os.path.join(fixtures_dir, "corrupt.wav")
with open(corrupt_path, "wb") as f:
    f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00NOT_VALID_AUDIO_DATA_TRUNCATED")

print("All fixtures generated:")
for name in sorted(os.listdir(fixtures_dir)):
    p = os.path.join(fixtures_dir, name)
    print(f"  {name}: {os.path.getsize(p)} bytes")
