"""
shared/parsing.py
公共解析工具 — 数字提取、Markdown 清洗等
"""
from __future__ import annotations

import re
from typing import Any


def parse_number(value: Any) -> float | None:
    """安全解析数字，支持字符串（含中文单位 万/亿/千/%）和数值类型"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("，", "")
        multipliers = {"万": 1e4, "亿": 1e8, "千": 1e3, "%": 0.01}
        for unit, mult in multipliers.items():
            if unit in text:
                try:
                    num = float(re.sub(r"[^\d.-]", "", text))
                    return num * mult
                except ValueError:
                    return None
        try:
            return float(re.sub(r"[^\d.-]", "", text))
        except ValueError:
            return None
    return None
