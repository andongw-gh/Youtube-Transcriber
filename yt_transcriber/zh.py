"""Chinese-specific helpers: script conversion and Whisper prompts."""

from __future__ import annotations

SCRIPT_CHOICES = ("keep", "simplified", "traditional")
SCRIPT_LABELS = {
    "keep": "As spoken / 不转换",
    "simplified": "Simplified / 简体",
    "traditional": "Traditional / 繁體",
}

# zhconv locales that convert characters only, without swapping regional vocabulary.
_ZHCONV_LOCALE = {"simplified": "zh-hans", "traditional": "zh-hant"}

# Whisper writes Chinese in whichever script it feels like. A short prompt in the
# wanted script nudges it the right way; the final zhconv pass guarantees it.
SCRIPT_PROMPTS = {
    "simplified": "以下是普通话的句子，使用简体中文。",
    "traditional": "以下是普通話的句子，使用繁體中文。",
}

CHINESE_LANGUAGE_CODES = {"zh", "yue"}


def is_chinese(language_code: str | None) -> bool:
    if not language_code:
        return False
    return language_code.lower().split("-")[0] in CHINESE_LANGUAGE_CODES


def convert_script(text: str, script: str) -> str:
    """Convert Chinese text to the requested script ("keep" returns it unchanged)."""
    if script not in SCRIPT_CHOICES:
        raise ValueError(f"Unknown Chinese script option: {script!r}")
    if script == "keep" or not text:
        return text
    import zhconv  # local import: only needed for Chinese output

    return zhconv.convert(text, _ZHCONV_LOCALE[script])
