"""Contestant ID validation for the AI match entry points."""

import re


MAX_NAME_LENGTH = 60
CONTESTANT_HINT = "请填实际模型-思考强度-Agent平台（最多 60 字符），例如 DeepSeek-V3.1-深度思考-Cursor。平台未公开时可写「模型未公开」或「推理档未公开」。"


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
