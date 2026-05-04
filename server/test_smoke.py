"""Smoke test: synth 5s sine, verify pipeline loads + runs without crash on CUDA.

Goals:
    1. Pipeline construction succeeds (will trigger model download on first run).
    2. CUDA is actually used.
    3. transcribe() returns a list (likely empty for a sine wave — that's fine).
"""

from __future__ import annotations

import math
import struct
import sys
import tempfile
import time
import wave
from pathlib import Path

import torch

from pipeline import Pipeline, format_as_markdown


def _write_sine_wav(path: Path, seconds: float = 5.0, sr: int = 16_000, freq: float = 440.0) -> None:
    n_frames = int(seconds * sr)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit PCM
        w.setframerate(sr)
        for i in range(n_frames):
            sample = int(0.3 * 32767 * math.sin(2 * math.pi * freq * i / sr))
            w.writeframes(struct.pack("<h", sample))


def main() -> int:
    assert torch.cuda.is_available(), "CUDA not available — won't smoke test on CPU"
    print(f"torch={torch.__version__} cuda={torch.version.cuda} device={torch.cuda.get_device_name(0)}")

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "sine.wav"
        _write_sine_wav(wav)
        print(f"wrote {wav} ({wav.stat().st_size} bytes)")

        baseline_mem = torch.cuda.memory_allocated()
        t0 = time.time()
        pipeline = Pipeline(device="cuda")
        t1 = time.time()
        loaded_mem = torch.cuda.memory_allocated()
        print(f"pipeline loaded in {t1 - t0:.1f}s; CUDA mem: {baseline_mem/1e6:.0f}MB -> {loaded_mem/1e6:.0f}MB")
        assert loaded_mem > baseline_mem, "no GPU memory used by model — CUDA load suspect"

        t2 = time.time()
        segments = pipeline.transcribe(wav)
        t3 = time.time()
        print(f"transcribe() done in {t3 - t2:.1f}s; got {len(segments)} segments")
        assert isinstance(segments, list), "transcribe() did not return a list"

        if segments:
            print("\n--- markdown preview ---")
            print(format_as_markdown(segments, title="Smoke test"))
        else:
            print("(no segments — expected for a pure sine wave)")

    print("\nSMOKE TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
