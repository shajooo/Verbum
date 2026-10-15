"""
Gate A Benchmark & Verification Script
Measures latency, VRAM, and RAM across all supported models on this machine.
"""

import gc
import json
import os
import subprocess
import sys
import time
import psutil

# Ensure parent directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "transcription")))
from engine import TranscriptionEngine, AVAILABLE_MODELS


def get_gpu_memory_used_mb() -> float:
    """Query current GPU VRAM usage in MiB using nvidia-smi."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
        )
        return float(out.strip().split("\n")[0])
    except Exception:
        return 0.0


def get_ram_used_mb() -> float:
    """Query current process RSS RAM in MiB."""
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def run_benchmark():
    fixtures_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures", "audio"))
    short_audio = os.path.join(fixtures_dir, "short_en.wav")
    long_audio = os.path.join(fixtures_dir, "long_en.wav")

    results = {}
    engine = TranscriptionEngine()

    print("=================================================================")
    print("VERBUM GATE A: PER-MODEL LATENCY / VRAM / RAM BENCHMARK")
    print(f"Machine: RTX 3050 (4 GB VRAM), Windows, Python {sys.version.split()[0]}")
    print("=================================================================")

    for model_name in ["tiny", "base", "small", "medium"]:
        print(f"\n--- Testing Model: {model_name.upper()} ---")
        gc.collect()
        time.sleep(0.5)

        base_vram = get_gpu_memory_used_mb()
        base_ram = get_ram_used_mb()

        # Measure load
        t0 = time.perf_counter()
        load_info = engine.load_model(model_name)
        load_time = time.perf_counter() - t0

        loaded_vram = get_gpu_memory_used_mb()
        loaded_ram = get_ram_used_mb()
        model_vram_delta = max(0.0, loaded_vram - base_vram)
        model_ram_delta = max(0.0, loaded_ram - base_ram)

        print(f"Loaded in {load_time:.2f}s | Device: {load_info['device']} ({load_info['compute_type']})")
        print(f"VRAM used: {loaded_vram:.1f} MB (Delta: +{model_vram_delta:.1f} MB)")
        print(f"RAM used:  {loaded_ram:.1f} MB (Delta: +{model_ram_delta:.1f} MB)")

        # Short audio transcribe
        t0 = time.perf_counter()
        res_short = engine.transcribe(short_audio)
        short_time = time.perf_counter() - t0
        short_rtf = short_time / res_short["duration_s"]
        print(f"Short Audio ({res_short['duration_s']}s): {short_time:.3f}s (RTF: {short_rtf:.3f}x)")
        print(f"  Transcript: \"{res_short['text']}\"")

        # Long audio transcribe
        t0 = time.perf_counter()
        res_long = engine.transcribe(long_audio)
        long_time = time.perf_counter() - t0
        long_rtf = long_time / res_long["duration_s"]
        print(f"Long Audio  ({res_long['duration_s']}s): {long_time:.3f}s (RTF: {long_rtf:.3f}x)")
        print(f"  Transcript: \"{res_long['text'][:60]}...\"")

        # Unload
        engine.unload_model()
        gc.collect()
        time.sleep(0.5)
        after_unload_vram = get_gpu_memory_used_mb()

        results[model_name] = {
            "device": load_info["device"],
            "compute_type": load_info["compute_type"],
            "load_time_s": round(load_time, 2),
            "vram_delta_mb": round(model_vram_delta, 1),
            "ram_delta_mb": round(model_ram_delta, 1),
            "short_duration_s": res_short["duration_s"],
            "short_latency_s": round(short_time, 3),
            "short_rtf": round(short_rtf, 3),
            "long_duration_s": res_long["duration_s"],
            "long_latency_s": round(long_time, 3),
            "long_rtf": round(long_rtf, 3),
            "short_text": res_short["text"],
            "vram_reclaimed": round(loaded_vram - after_unload_vram, 1),
        }

    # Save benchmark results to file
    out_path = os.path.join(os.path.dirname(__file__), "gate_a_benchmarks.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\nBenchmark saved to:", out_path)
    return results


if __name__ == "__main__":
    run_benchmark()
