"""Shared response-language policy for course-design agents.

The policy explicitly identifies Chinese, Japanese, and Korean. Other
languages use ``same-as-user`` so the model follows the persisted original
topic instead of being incorrectly forced into English. Generated options,
feedback, and other model-produced text never affect the decision.
"""

import re


_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_KANA = re.compile(r"[\u3040-\u30ff\uff66-\uff9f]")
_HANGUL = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")


def infer_response_language(*values: object) -> str:
    """Infer the learner's natural language while allowing English terminology."""
    text = " ".join(str(value or "") for value in values)
    if _KANA.search(text):
        return "ja"
    if _HANGUL.search(text):
        return "ko"
    if _CJK.search(text):
        return "zh-CN"
    return "same-as-user"


def response_language_instruction(language: str) -> str:
    if language == "zh-CN":
        return (
            "responseLanguage=zh-CN。所有自然语言响应（问题、描述、选项、总结、标题、目标和助手消息）必须使用中文；"
            "Kubernetes、Operator、CRD 等技术专名可以保留英文。"
        )
    if language == "ja":
        return "responseLanguage=ja。所有自然语言响应必须使用日文；技术专名可以保留原文。"
    if language == "ko":
        return "responseLanguage=ko。所有自然语言响应必须使用韩文；技术专名可以保留原文。"
    return (
        "responseLanguage=same-as-user。所有自然语言响应（问题、描述、选项、总结、标题、目标和助手消息）"
        "必须严格跟随持久化原始 topic 的自然语言；不得因 Kubernetes、Operator、CRD 等技术专名改变语言。"
    )
