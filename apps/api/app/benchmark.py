from __future__ import annotations

import argparse
import gc
import json
import logging
import math
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any, Protocol

from .config import Settings, get_settings
from .detection import find_candidates, make_quote, normalize_token
from .transcriber import TranscriptionResult, WhisperTranscriber

logger = logging.getLogger("tuskometr.benchmark")


@dataclass(frozen=True, slots=True)
class AudioWindow:
    offset_seconds: float
    duration_seconds: float
    pcm: bytes


@dataclass(frozen=True, slots=True)
class BenchmarkDetection:
    position_seconds: float
    form: str
    normalized_form: str
    confidence: float
    quote: str


@dataclass(frozen=True, slots=True)
class TruthOccurrence:
    position_seconds: float
    normalized_form: str | None = None


class Transcriber(Protocol):
    model_name: str

    def transcribe_pcm(self, pcm: bytes) -> TranscriptionResult: ...

    def verify_fuzzy_candidate(
        self, pcm: bytes, candidate_start: float, candidate_end: float
    ) -> tuple[str, float] | None: ...


class PeakMemorySampler:
    def __init__(self, interval_seconds: float = 0.05) -> None:
        self.interval_seconds = interval_seconds
        self.peak_bytes = current_rss_bytes()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def __enter__(self) -> PeakMemorySampler:
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop_event.set()
        self._thread.join()
        self.peak_bytes = max(self.peak_bytes, current_rss_bytes())

    def _sample(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            self.peak_bytes = max(self.peak_bytes, current_rss_bytes())


def current_rss_bytes() -> int:
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
    except OSError:
        return 0
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return 0


def decode_audio(path: Path, sample_rate: int, max_seconds: float | None = None) -> bytes:
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
    ]
    if max_seconds is not None:
        command.extend(["-t", str(max_seconds)])
    command.extend(
        [
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        ]
    )
    process = subprocess.run(command, capture_output=True, check=False)
    if process.returncode != 0:
        message = process.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"FFmpeg nie odczytał pliku audio: {message[-1000:]}")
    if not process.stdout:
        raise RuntimeError("FFmpeg zwrócił pusty strumień audio")
    return process.stdout


def iter_audio_windows(
    pcm: bytes,
    sample_rate: int,
    chunk_seconds: int,
    step_seconds: int,
    minimum_final_seconds: int = 5,
) -> list[AudioWindow]:
    bytes_per_second = sample_rate * 2
    chunk_bytes = chunk_seconds * bytes_per_second
    step_bytes = step_seconds * bytes_per_second
    minimum_bytes = minimum_final_seconds * bytes_per_second
    windows: list[AudioWindow] = []
    offset_bytes = 0
    while offset_bytes + chunk_bytes <= len(pcm):
        windows.append(
            AudioWindow(
                offset_seconds=offset_bytes / bytes_per_second,
                duration_seconds=float(chunk_seconds),
                pcm=pcm[offset_bytes : offset_bytes + chunk_bytes],
            )
        )
        offset_bytes += step_bytes
    remaining = len(pcm) - offset_bytes
    if remaining >= minimum_bytes:
        windows.append(
            AudioWindow(
                offset_seconds=offset_bytes / bytes_per_second,
                duration_seconds=remaining / bytes_per_second,
                pcm=pcm[offset_bytes:],
            )
        )
    return windows


def deduplicate_detections(
    detections: list[BenchmarkDetection], tolerance_seconds: float = 0.75
) -> list[BenchmarkDetection]:
    unique: list[BenchmarkDetection] = []
    for detection in sorted(detections, key=lambda item: item.position_seconds):
        duplicate = any(
            item.normalized_form == detection.normalized_form
            and abs(item.position_seconds - detection.position_seconds) <= tolerance_seconds
            for item in unique
        )
        if not duplicate:
            unique.append(detection)
    return unique


def load_truth(path: Path) -> tuple[list[TruthOccurrence], float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("occurrences"), list):
        raise ValueError("Plik anotacji musi zawierać tablicę 'occurrences'")
    tolerance = float(payload.get("toleranceSeconds", 1.5))
    if tolerance <= 0:
        raise ValueError("toleranceSeconds musi być większe od zera")
    occurrences: list[TruthOccurrence] = []
    for index, item in enumerate(payload["occurrences"]):
        if not isinstance(item, dict) or "positionSeconds" not in item:
            raise ValueError(f"Niepoprawna anotacja occurrences[{index}]")
        form = item.get("form")
        occurrences.append(
            TruthOccurrence(
                position_seconds=float(item["positionSeconds"]),
                normalized_form=normalize_token(str(form)) if form else None,
            )
        )
    return sorted(occurrences, key=lambda item: item.position_seconds), tolerance


def evaluate_detections(
    detections: list[BenchmarkDetection],
    truth: list[TruthOccurrence],
    tolerance_seconds: float,
) -> dict[str, Any]:
    possible_matches: list[tuple[float, int, int]] = []
    for truth_index, expected in enumerate(truth):
        for detection_index, actual in enumerate(detections):
            distance = abs(expected.position_seconds - actual.position_seconds)
            form_matches = (
                expected.normalized_form is None
                or expected.normalized_form == actual.normalized_form
            )
            if form_matches and distance <= tolerance_seconds:
                possible_matches.append((distance, truth_index, detection_index))

    matched_truth: set[int] = set()
    matched_detections: set[int] = set()
    matches: list[dict[str, Any]] = []
    for distance, truth_index, detection_index in sorted(possible_matches):
        if truth_index in matched_truth or detection_index in matched_detections:
            continue
        matched_truth.add(truth_index)
        matched_detections.add(detection_index)
        matches.append(
            {
                "expectedPositionSeconds": truth[truth_index].position_seconds,
                "detectedPositionSeconds": detections[detection_index].position_seconds,
                "distanceSeconds": round(distance, 3),
                "form": detections[detection_index].normalized_form,
            }
        )

    true_positives = len(matches)
    false_positives = len(detections) - true_positives
    false_negatives = len(truth) - true_positives
    precision = true_positives / len(detections) if detections else (1.0 if not truth else 0.0)
    recall = true_positives / len(truth) if truth else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "truePositives": true_positives,
        "falsePositives": false_positives,
        "falseNegatives": false_negatives,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "matches": matches,
        "missed": [
            asdict(item) for index, item in enumerate(truth) if index not in matched_truth
        ],
        "unexpected": [
            asdict(item)
            for index, item in enumerate(detections)
            if index not in matched_detections
        ],
    }


def percentile(values: list[float], percentage: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentage / 100 * len(ordered)) - 1)
    return ordered[index]


def simulated_lag(windows: list[AudioWindow], processing_times: list[float]) -> tuple[float, float]:
    finished_at = 0.0
    maximum_lag = 0.0
    final_lag = 0.0
    for window, processing_time in zip(windows, processing_times, strict=True):
        ready_at = window.offset_seconds + window.duration_seconds
        finished_at = max(finished_at, ready_at) + processing_time
        final_lag = max(0.0, finished_at - ready_at)
        maximum_lag = max(maximum_lag, final_lag)
    return maximum_lag, final_lag


def benchmark_model(
    model_name: str,
    pcm: bytes,
    settings: Settings,
    truth: list[TruthOccurrence] | None,
    truth_tolerance_seconds: float,
) -> dict[str, Any]:
    windows = iter_audio_windows(
        pcm,
        sample_rate=settings.sample_rate,
        chunk_seconds=settings.chunk_seconds,
        step_seconds=settings.chunk_step_seconds,
    )
    if not windows:
        raise ValueError("Nagranie musi mieć co najmniej 5 sekund")

    baseline_rss = current_rss_bytes()
    with PeakMemorySampler() as memory:
        load_cpu_started = time.process_time()
        load_started = time.perf_counter()
        transcriber: Transcriber = WhisperTranscriber(settings, model_name)
        load_seconds = time.perf_counter() - load_started
        load_cpu_seconds = time.process_time() - load_cpu_started

        processing_times: list[float] = []
        detections: list[BenchmarkDetection] = []
        window_reports: list[dict[str, Any]] = []
        process_started = time.process_time()
        benchmark_started = time.perf_counter()
        for index, window in enumerate(windows, start=1):
            started = time.perf_counter()
            result = transcriber.transcribe_pcm(window.pcm)
            window_detections: list[BenchmarkDetection] = []
            for candidate in find_candidates(result.words):
                verified_confidence: float | None = None
                if not candidate.exact:
                    verification = transcriber.verify_fuzzy_candidate(
                        window.pcm,
                        candidate.token.start,
                        candidate.token.end,
                    )
                    if verification is None:
                        continue
                    verified_form, verified_confidence = verification
                    if verified_form != candidate.normalized_form:
                        continue
                confidence = candidate.token.probability
                if verified_confidence is not None:
                    confidence = min(1.0, max(confidence, verified_confidence) * 0.95)
                detection = BenchmarkDetection(
                    position_seconds=window.offset_seconds + max(0.0, candidate.token.start),
                    form=candidate.canonical_form,
                    normalized_form=candidate.normalized_form,
                    confidence=max(0.0, min(1.0, confidence)),
                    quote=make_quote(result.words, candidate.word_index),
                )
                detections.append(detection)
                window_detections.append(detection)
            elapsed = time.perf_counter() - started
            processing_times.append(elapsed)
            window_reports.append(
                {
                    "index": index,
                    "offsetSeconds": round(window.offset_seconds, 3),
                    "durationSeconds": round(window.duration_seconds, 3),
                    "processingSeconds": round(elapsed, 3),
                    "text": result.text,
                    "averageConfidence": round(result.average_confidence, 4),
                    "detections": [asdict(item) for item in window_detections],
                }
            )
            logger.info(
                "%s: okno %d/%d, audio %.1fs, czas %.2fs, trafienia %d",
                model_name,
                index,
                len(windows),
                window.duration_seconds,
                elapsed,
                len(window_detections),
            )
        processing_wall_seconds = time.perf_counter() - benchmark_started

    cpu_seconds = time.process_time() - process_started
    unique_detections = deduplicate_detections(detections)
    maximum_lag, final_lag = simulated_lag(windows, processing_times)
    audio_duration = len(pcm) / 2 / settings.sample_rate
    timing = {
        "windowCount": len(windows),
        "meanSeconds": round(mean(processing_times), 3),
        "p50Seconds": round(percentile(processing_times, 50), 3),
        "p95Seconds": round(percentile(processing_times, 95), 3),
        "p99Seconds": round(percentile(processing_times, 99), 3),
        "maxSeconds": round(max(processing_times), 3),
        "overStepCount": sum(
            elapsed > settings.chunk_step_seconds for elapsed in processing_times
        ),
        "processingWallSeconds": round(processing_wall_seconds, 3),
        "cpuSeconds": round(cpu_seconds, 3),
        "realTimeFactor": round(processing_wall_seconds / audio_duration, 4),
        "maximumSimulatedLagSeconds": round(maximum_lag, 3),
        "finalSimulatedLagSeconds": round(final_lag, 3),
    }
    report: dict[str, Any] = {
        "model": transcriber.model_name,
        "loadSeconds": round(load_seconds, 3),
        "loadCpuSeconds": round(load_cpu_seconds, 3),
        "baselineRssMiB": round(baseline_rss / 1024 / 1024, 1),
        "peakRssMiB": round(memory.peak_bytes / 1024 / 1024, 1),
        "timing": timing,
        "detectionCount": len(unique_detections),
        "detections": [asdict(item) for item in unique_detections],
        "evaluation": (
            evaluate_detections(unique_detections, truth, truth_tolerance_seconds)
            if truth is not None
            else None
        ),
        "windows": window_reports,
    }
    del transcriber
    gc.collect()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Izolowany benchmark modeli Faster-Whisper dla Tuskometru"
    )
    parser.add_argument("--audio", required=True, type=Path, help="Plik audio lub wideo")
    parser.add_argument(
        "--models",
        default="base,small,medium",
        help="Modele rozdzielone przecinkami (domyślnie: base,small,medium)",
    )
    parser.add_argument("--truth", type=Path, help="Opcjonalny plik anotacji JSON")
    parser.add_argument("--output", type=Path, help="Ścieżka raportu JSON")
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Wypisz na stdout wyłącznie JSON (do przekierowania do pliku)",
    )
    parser.add_argument("--max-seconds", type=float, help="Przetwórz tylko początek nagrania")
    parser.add_argument("--cpu-threads", type=int, help="Nadpisz ASR_CPU_THREADS")
    parser.add_argument("--beam-size", type=int, help="Nadpisz ASR_BEAM_SIZE")
    parser.add_argument("--chunk-seconds", type=int, help="Nadpisz CHUNK_SECONDS")
    parser.add_argument("--chunk-step-seconds", type=int, help="Nadpisz CHUNK_STEP_SECONDS")
    return parser


def effective_settings(args: argparse.Namespace) -> Settings:
    settings = get_settings()
    updates = {
        key: value
        for key, value in {
            "asr_cpu_threads": args.cpu_threads,
            "asr_beam_size": args.beam_size,
            "chunk_seconds": args.chunk_seconds,
            "chunk_step_seconds": args.chunk_step_seconds,
        }.items()
        if value is not None
    }
    return Settings(**(settings.model_dump() | updates))


def print_summary(report: dict[str, Any]) -> None:
    print("\nWyniki benchmarku")
    print(
        "model          średnia    p95    max   RTF   peak RAM   trafienia   recall"
    )
    for model in report["models"]:
        timing = model["timing"]
        evaluation = model["evaluation"]
        recall = f"{evaluation['recall']:.3f}" if evaluation is not None else "-"
        print(
            f"{model['model']:<14}"
            f"{timing['meanSeconds']:>7.2f}s "
            f"{timing['p95Seconds']:>6.2f}s "
            f"{timing['maxSeconds']:>6.2f}s "
            f"{timing['realTimeFactor']:>5.2f} "
            f"{model['peakRssMiB']:>8.1f} MiB "
            f"{model['detectionCount']:>8}   "
            f"{recall:>6}"
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args()
    if not args.audio.is_file():
        raise SystemExit(f"Nie znaleziono pliku audio: {args.audio}")
    if args.max_seconds is not None and args.max_seconds < 5:
        raise SystemExit("--max-seconds musi wynosić co najmniej 5")
    settings = effective_settings(args)
    models = [item.strip() for item in args.models.split(",") if item.strip()]
    if not models:
        raise SystemExit("Podaj co najmniej jeden model")

    truth: list[TruthOccurrence] | None = None
    truth_tolerance_seconds = 1.5
    if args.truth:
        truth, truth_tolerance_seconds = load_truth(args.truth)

    logger.info("Dekodowanie %s do mono PCM %d Hz", args.audio, settings.sample_rate)
    pcm = decode_audio(args.audio, settings.sample_rate, args.max_seconds)
    audio_duration = len(pcm) / 2 / settings.sample_rate
    report: dict[str, Any] = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "audio": {
            "path": str(args.audio),
            "durationSeconds": round(audio_duration, 3),
            "sampleRate": settings.sample_rate,
        },
        "config": {
            "device": settings.asr_device,
            "computeType": settings.asr_compute_type,
            "cpuThreads": settings.asr_cpu_threads,
            "beamSize": settings.asr_beam_size,
            "hotwordsVerify": settings.asr_hotwords_verify,
            "chunkSeconds": settings.chunk_seconds,
            "chunkStepSeconds": settings.chunk_step_seconds,
            "truthToleranceSeconds": truth_tolerance_seconds,
        },
        "truthCount": len(truth) if truth is not None else None,
        "models": [],
    }
    for model_name in models:
        logger.info("Uruchamianie modelu %s", model_name)
        report["models"].append(
            benchmark_model(
                model_name,
                pcm,
                settings,
                truth,
                truth_tolerance_seconds,
            )
        )

    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if not args.json_only:
        print_summary(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
        if not args.json_only:
            print(f"\nRaport zapisany w {args.output}")
    else:
        if not args.json_only:
            print("\nPełny raport JSON:\n")
        print(serialized)


if __name__ == "__main__":
    main()
