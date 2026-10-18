"""Conservative prompt-injection flags for untrusted external text."""

import re

_PATTERNS = {
    "instruction_override": re.compile(r"\b(ignore|disregard|forget)\b.{0,40}\b(instruction|prompt|system)\b", re.I),
    "role_impersonation": re.compile(r"\b(system|assistant|developer)\s*:", re.I),
    "secret_request": re.compile(r"\b(api[-_ ]?key|password|access token|system prompt)\b", re.I),
    "tool_request": re.compile(r"\b(run|execute|call)\b.{0,30}\b(command|tool|shell|script)\b", re.I),
}


def scan_external_text(text: str) -> list[str]:
    return [name for name, pattern in _PATTERNS.items() if pattern.search(text or "")]
