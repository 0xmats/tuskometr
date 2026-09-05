from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

CANONICAL_FORMS: dict[str, str] = {
    "tusk": "Tusk",
    "tuska": "Tuska",
    "tuskowi": "Tuskowi",
    "tuskiem": "Tuskiem",
    "tusku": "Tusku",
    "tuskowie": "Tuskowie",
    "tusków": "Tusków",
    "tuskom": "Tuskom",
    "tuskami": "Tuskami",
    "tuskach": "Tuskach",
}
HOTWORDS = "Donald Tusk Tuska Tuskowi Tuskiem Tusku Tuskowie Tusków Tuskom Tuskami Tuskach"
DERIVATIVE_SUFFIXES = (
    "tuskowy",
    "tuskowa",
    "tuskowe",
    "tuskowych",
    "tuskowym",
    "tuskowymi",
    "tuskowska",
    "tuskowski",
    "tuskowskie",
)


@dataclass(frozen=True, slots=True)
class WordToken:
    text: str
    start: float
    end: float
    probability: float


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    word_index: int
    token: WordToken
    normalized_form: str
    canonical_form: str
    exact: bool


@dataclass(frozen=True, slots=True)
class DetectedOccurrence:
    occurred_at: datetime
    source_sample: int
    form: str
    normalized_form: str
    quote: str
    confidence: float
    source_position_seconds: float


def normalize_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return "".join(character for character in normalized if character.isalpha())


def is_one_edit_away(left: str, right: str) -> bool:
    """Return true for an exact Levenshtein distance of one."""
    if left == right or abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right, strict=True)) == 1

    short_index = long_index = differences = 0
    while short_index < len(left) and long_index < len(right):
        if left[short_index] == right[long_index]:
            short_index += 1
            long_index += 1
            continue
        differences += 1
        if differences > 1:
            return False
        long_index += 1
    return True


def find_candidates(words: list[WordToken], include_fuzzy: bool = True) -> list[MatchCandidate]:
    matches: list[MatchCandidate] = []
    for index, word in enumerate(words):
        normalized = normalize_token(word.text)
        if not normalized:
            continue
        if normalized in CANONICAL_FORMS:
            matches.append(
                MatchCandidate(
                    word_index=index,
                    token=word,
                    normalized_form=normalized,
                    canonical_form=CANONICAL_FORMS[normalized],
                    exact=True,
                )
            )
            continue
        if not include_fuzzy or len(normalized) < 4:
            continue
        if any(normalized.endswith(suffix) for suffix in DERIVATIVE_SUFFIXES):
            continue
        fuzzy_form = next(
            (form for form in CANONICAL_FORMS if is_one_edit_away(normalized, form)), None
        )
        if fuzzy_form:
            matches.append(
                MatchCandidate(
                    word_index=index,
                    token=word,
                    normalized_form=fuzzy_form,
                    canonical_form=CANONICAL_FORMS[fuzzy_form],
                    exact=False,
                )
            )
    return matches


def make_quote(words: list[WordToken], target_index: int, radius: int = 9) -> str:
    start = max(0, target_index - radius)
    end = min(len(words), target_index + radius + 1)
    return " ".join(word.text.strip() for word in words[start:end]).strip()


def materialize_occurrence(
    candidate: MatchCandidate,
    words: list[WordToken],
    chunk_started_at: datetime,
    chunk_start_sample: int,
    sample_rate: int,
    verified_confidence: float | None = None,
) -> DetectedOccurrence:
    relative_seconds = max(candidate.token.start, 0)
    source_sample = chunk_start_sample + round(relative_seconds * sample_rate)
    confidence = candidate.token.probability
    if verified_confidence is not None:
        confidence = min(1.0, max(confidence, verified_confidence) * 0.95)
    return DetectedOccurrence(
        occurred_at=chunk_started_at + timedelta(seconds=relative_seconds),
        source_sample=source_sample,
        form=candidate.canonical_form,
        normalized_form=candidate.normalized_form,
        quote=make_quote(words, candidate.word_index),
        confidence=max(0.0, min(1.0, confidence)),
        source_position_seconds=source_sample / sample_rate,
    )
