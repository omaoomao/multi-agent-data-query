"""Agent 共享工具函数。"""

import re


def llm_to_str(result) -> str:
    """从 LLM 返回值中安全提取纯文本，清理 <think> 标签。"""
    if isinstance(result, str):
        text = result
    elif hasattr(result, "content"):
        text = str(result.content)
    elif hasattr(result, "text"):
        text = str(result.text)
    else:
        text = str(result)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    text = re.sub(r"</think>", "", text).strip()
    return text
