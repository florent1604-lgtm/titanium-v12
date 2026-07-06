import sounddevice as sd
import numpy as np

RATE = 16000
FRAME = 480

for idx in [0, 1, 4, 5, 9, 11]:
    try:
        dev = sd.query_devices(idx)
        if dev["max_input_channels"] == 0:
            continue
        with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=FRAME, device=idx) as s:
            frames = []
            for _ in range(30):
                f, _ = s.read(FRAME)
                frames.append(float(np.sqrt(np.mean(f.astype(np.float32)**2))) / 32768.0)
            max_r = max(frames)
            status = "OK" if max_r > 0.0001 else "SILENCIEUX"
            print(f"Device {idx} ({dev['name'][:40]}): RMS max={max_r:.5f} {status}")
    except Exception as e:
        print(f"Device {idx}: ERREUR - {e}")
