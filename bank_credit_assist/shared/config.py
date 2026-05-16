"""
shared/config.py
配置中心（代理 + API Keys + 目录）
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# 网络代理配置（解决本地开发 Timeout 问题）
# ─────────────────────────────────────────────
HTTP_PROXY: str | None = os.getenv("HTTP_PROXY")   # 如 "http://127.0.0.1:15236"
HTTPS_PROXY: str | None = os.getenv("HTTPS_PROXY")  # 如 "http://127.0.0.1:15236"
NO_PROXY: str | None = os.getenv("NO_PROXY", "localhost,127.0.0.1")

# ─────────────────────────────────────────────
# API 配置
# ─────────────────────────────────────────────
MINERU_API_TOKEN: str = os.getenv("MINERU_API_TOKEN", "")
MINERU_API_BASE: str = "https://mineru.net/api/v4"

# Minimax API（Anthropic 兼容协议）
MINIMAX_API_KEY: str = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_MODEL: str = os.getenv("MINIMAX_MODEL", "claude-3.5-sonnet-20240620")

# ─────────────────────────────────────────────
# 目录配置
# ─────────────────────────────────────────────
# PROJECT_ROOT 为项目根目录（index.html 所在目录）
# __file__ = bank_credit_assist/shared/config.py
# .parent = bank_credit_assist/shared
# .parent.parent = bank_credit_assist
# .parent.parent.parent = 项目根目录
PROJECT_ROOT: Path = Path(__file__).parent.parent.parent
TEMPLATE_DIR: Path = PROJECT_ROOT / "bank_credit_assist" / "templates"
OUTPUT_DIR: Path = PROJECT_ROOT / "bank_credit_assist" / "output"
TEMP_DIR: Path = PROJECT_ROOT / "bank_credit_assist" / "temp"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
