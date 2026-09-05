import json

from app.benchmark import (
    AudioWindow,
    BenchmarkDetection,
    TruthOccurrence,
    deduplicate_detections,
    evaluate_detections,
    iter_audio_windows,
    load_truth,
    percentile,
    simulated_lag,
)


def test_audio_windows_match_worker_overlap_and_final_fragment() -> None:
    sample_rate = 10
    pcm = b"\0" * (65 * sample_rate * 2)

    windows = iter_audio_windows(
        pcm,
        sample_rate=sample_rate,
        chunk_seconds=25,
        step_seconds=20,
    )

    assert [window.offset_seconds for window in windows] == [0, 20, 40, 60]
    assert [window.duration_seconds for window in windows] == [25, 25, 25, 5]


def test_deduplicates_overlapping_detection_of_the_same_form() -> None:
    detections = [
        BenchmarkDetection(21.0, "Tusk", "tusk", 0.9, "Donald Tusk"),
        BenchmarkDetection(21.5, "Tusk", "tusk", 0.8, "Tusk powiedział"),
        BenchmarkDetection(21.5, "Tuska", "tuska", 0.8, "Donalda Tuska"),
    ]

    unique = deduplicate_detections(detections)

    assert [(item.position_seconds, item.normalized_form) for item in unique] == [
        (21.0, "tusk"),
        (21.5, "tuska"),
    ]


def test_evaluation_matches_each_detection_only_once() -> None:
    detections = [
        BenchmarkDetection(10.2, "Tusk", "tusk", 0.9, "Tusk"),
        BenchmarkDetection(30.0, "Tuska", "tuska", 0.9, "Tuska"),
        BenchmarkDetection(50.0, "Tusk", "tusk", 0.9, "Tusk"),
    ]
    truth = [
        TruthOccurrence(10.0, "tusk"),
        TruthOccurrence(30.5, "tuska"),
        TruthOccurrence(70.0, "tusk"),
    ]

    result = evaluate_detections(detections, truth, tolerance_seconds=1.5)

    assert result["truePositives"] == 2
    assert result["falsePositives"] == 1
    assert result["falseNegatives"] == 1
    assert result["precision"] == 0.6667
    assert result["recall"] == 0.6667


def test_load_truth_normalizes_forms(tmp_path) -> None:
    path = tmp_path / "truth.json"
    path.write_text(
        json.dumps(
            {
                "toleranceSeconds": 2,
                "occurrences": [
                    {"positionSeconds": 8.5, "form": "TUSKA!"},
                    {"positionSeconds": 4.0},
                ],
            }
        ),
        encoding="utf-8",
    )

    truth, tolerance = load_truth(path)

    assert tolerance == 2
    assert truth == [TruthOccurrence(4.0, None), TruthOccurrence(8.5, "tuska")]


def test_percentile_and_simulated_lag() -> None:
    windows = [
        AudioWindow(0, 25, b""),
        AudioWindow(20, 25, b""),
        AudioWindow(40, 25, b""),
    ]

    assert percentile([1, 2, 3, 20], 95) == 20
    assert simulated_lag(windows, [5, 25, 5]) == (25, 10)
