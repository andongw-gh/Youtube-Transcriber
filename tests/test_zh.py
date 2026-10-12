import pytest

from yt_transcriber.zh import SCRIPT_CHOICES, SCRIPT_PROMPTS, convert_script, is_chinese


def test_convert_to_simplified():
    assert convert_script("繁體中文的句子，電腦軟體", "simplified") == "繁体中文的句子，电脑软体"


def test_convert_to_traditional():
    assert convert_script("简体中文的句子", "traditional") == "簡體中文的句子"


def test_keep_is_identity():
    assert convert_script("隨便", "keep") == "隨便"
    assert convert_script("", "simplified") == ""


def test_unknown_script():
    with pytest.raises(ValueError):
        convert_script("x", "pinyin")


def test_is_chinese():
    assert is_chinese("zh")
    assert is_chinese("ZH-TW")
    assert is_chinese("yue")
    assert not is_chinese("en")
    assert not is_chinese(None)


def test_prompts_exist_for_conversions():
    assert set(SCRIPT_PROMPTS) == set(SCRIPT_CHOICES) - {"keep"}
