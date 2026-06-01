import re


SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")


def split_sentences(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    parts = [part.strip() for part in SENTENCE_SPLIT_RE.split(stripped) if part.strip()]
    return parts or [stripped]


def build_stream_tts_segments(text: str, response_kind: str = "") -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    if response_kind.startswith("refused") or response_kind in {"invalid_input", "gps:awaiting_landmarks", "chat"}:
        return [normalized]
    return split_sentences(normalized)
