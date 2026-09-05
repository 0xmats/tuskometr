from datetime import UTC, datetime

import pytest

from app.detection import (
    CANONICAL_FORMS,
    WordToken,
    find_candidates,
    is_one_edit_away,
    materialize_occurrence,
    normalize_token,
)


@pytest.mark.parametrize("form", list(CANONICAL_FORMS))
def test_detects_every_supported_inflection(form: str) -> None:
    words = [WordToken(text=f"{form},", start=1.25, end=1.7, probability=0.91)]

    matches = find_candidates(words)

    assert len(matches) == 1
    assert matches[0].exact is True
    assert matches[0].normalized_form == form


@pytest.mark.parametrize("word", ["tuskowy", "antytuskowy", "protuskowski", "tuskolandia"])
def test_does_not_match_derived_words(word: str) -> None:
    matches = find_candidates([WordToken(word, 0, 1, 0.9)])
    assert matches == []


def test_fuzzy_candidate_requires_a_separate_verification() -> None:
    matches = find_candidates([WordToken("Duska", 0, 1, 0.4)])
    assert len(matches) == 1
    assert matches[0].exact is False
    assert matches[0].normalized_form == "tuska"


def test_materializes_absolute_time_and_sample() -> None:
    started_at = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    words = [
        WordToken("Donald", 1.0, 1.4, 0.95),
        WordToken("Tusk", 1.5, 1.9, 0.93),
        WordToken("powiedział", 2.0, 2.7, 0.9),
    ]
    candidate = find_candidates(words)[0]

    occurrence = materialize_occurrence(
        candidate,
        words,
        chunk_started_at=started_at,
        chunk_start_sample=320_000,
        sample_rate=16_000,
    )

    assert occurrence.source_sample == 344_000
    assert occurrence.source_position_seconds == 21.5
    assert occurrence.occurred_at.isoformat() == "2026-08-29T12:00:01.500000+00:00"
    assert occurrence.quote == "Donald Tusk powiedział"


def test_normalization_and_edit_distance() -> None:
    assert normalize_token("„TUSKOWI!”") == "tuskowi"
    assert is_one_edit_away("dusk", "tusk")
    assert is_one_edit_away("tus", "tusk")
    assert not is_one_edit_away("tuskowy", "tusk")
