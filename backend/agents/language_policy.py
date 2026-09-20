"""Shared response-language policy for course-design agents.

The current product default is Chinese until a user/system locale is
available. Generated options, feedback, and other model-produced text never
affect the decision; the resolver keeps a replaceable seam for future locale
support.
"""

import re


DEFAULT_RESPONSE_LANGUAGE = "zh-CN"


def infer_response_language(*values: object) -> str:
    """Return the product default until a user/system locale is available.

    ``values`` remains in the signature so a future locale-aware resolver can
    replace this implementation without changing Agent call sites.
    """
    _ = values
    return DEFAULT_RESPONSE_LANGUAGE


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
