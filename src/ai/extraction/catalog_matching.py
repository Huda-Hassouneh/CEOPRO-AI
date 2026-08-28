import re
from typing import List, Tuple
from src.ai.pricing.matching import similarity
from src.ai.extraction.regex_patterns import ExtractedEntity
DEFAULT_MATCH_THRESHOLD = 0.80
def find_catalog_mentions(
    text: str, known_names: List[str], entity_type: str, threshold: float = None
) -> List[ExtractedEntity]:
    threshold = DEFAULT_MATCH_THRESHOLD if threshold is None else threshold
    if not known_names:
        return []
    candidate_spans = _candidate_spans(text)
    entities = []
    for start, end, candidate_text in candidate_spans:
        best_name, best_score = None, 0.0
        for name in known_names:
            score = similarity(candidate_text, name)
            if score > best_score:
                best_name, best_score = name, score
        if best_score >= threshold:
            entities.append(
                ExtractedEntity(
                    entity_type=entity_type, text=candidate_text, start=start, end=end,
                    normalized_value=best_name, confidence=round(best_score, 3),
                )
            )
    return entities
_CAPITALIZED_RUN_PATTERN = re.compile(r"\b[A-Z][\w'-]*(?:\s+[A-Z0-9][\w'-]*)*\b")
_ARABIC_RUN_PATTERN = re.compile(r"[\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+){0,4}")
def _candidate_spans(text: str) -> List[Tuple[int, int, str]]:
    spans = list(_capitalized_run_spans(text)) + list(_arabic_run_spans(text))
    spans.sort(key=lambda s: s[0])
    return _merge_adjacent_spans(spans, text)
def _capitalized_run_spans(text: str):
    for m in _CAPITALIZED_RUN_PATTERN.finditer(text):
        yield m.start(), m.end(), m.group(0)
def _arabic_run_spans(text: str):
    for m in _ARABIC_RUN_PATTERN.finditer(text):
        yield m.start(), m.end(), m.group(0)
def _merge_adjacent_spans(
    spans: List[Tuple[int, int, str]], text: str
) -> List[Tuple[int, int, str]]:
    if not spans:
        return spans
    spans = sorted(spans, key=lambda s: s[0])
    merged = [spans[0]]
    for start, end, candidate_text in spans[1:]:
        prev_start, prev_end, _ = merged[-1]
        if start <= prev_end:
            new_end = max(prev_end, end)
            merged[-1] = (prev_start, new_end, text[prev_start:new_end])
            continue
        gap = text[prev_end:start]
        if gap.strip() == "":
            merged[-1] = (prev_start, end, text[prev_start:end])
        else:
            merged.append((start, end, candidate_text))
    return merged
