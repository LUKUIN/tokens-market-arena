"""Contestant ID validation for the AI match entry points."""

import re


MAX_NAME_LENGTH = 60
CONTESTANT_HINT = "Use model-effort-agent platform (max 60 characters), e.g. DeepSeek-V3.1-high-Cursor. Use 'model undisclosed' or 'effort undisclosed' if the platform hides those details."


def parse_contestant_id(value):
    """Normalize a model-effort-platform ID, or return None if it is incomplete."""
    if not isinstance(value, str):
        return None

    clean = re.sub(r"[^\w\s\-_.()（）·]", "", value)
    fields = [" ".join(part.split()) for part in clean.rsplit("-", 2)]
    if len(fields) != 3 or any(not re.search(r"\w", field) for field in fields):
        return None

    model, effort, platform = fields
    if model.casefold() == platform.casefold():
        return None

    label = "-".join((model, effort, platform))
    return label if len(label) <= MAX_NAME_LENGTH else None
