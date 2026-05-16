"""
shared/utils.py
通用工具函数
"""
from __future__ import annotations
import re
import sys


def safe_print(msg: str) -> None:
    """打印到终端，自动替换无法用当前编码的字符（Windows 终端兼容）"""
    try:
        print(msg)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding if hasattr(sys.stdout, "encoding") else "utf-8"
        safe_msg = msg.encode(encoding, errors="replace").decode(encoding)
        print(safe_msg)


def strip_markdown_fences(text: str) -> str:
    """去除 Markdown 代码块标记（```json ... ```）"""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    return text
