"""
shared/encoding.py
Windows 终端 UTF-8 编码补丁
"""
from __future__ import annotations

import sys


def fix_windows_console_encoding() -> None:
    """在 Windows 上将 stdout/stderr 重配置为 UTF-8"""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
