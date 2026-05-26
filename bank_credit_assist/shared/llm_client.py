"""
shared/llm_client.py
Anthropic 兼容 API 客户端工厂（复用 Minimax 代理配置）
"""
from __future__ import annotations

import os
import anthropic

from shared.config import MINIMAX_API_KEY, MINIMAX_MODEL, HTTPS_PROXY

MINIMAX_API_BASE: str = "https://api.minimaxi.com/anthropic"


def create_anthropic_client(
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 120.0,
    max_retries: int = 2,
) -> anthropic.Anthropic:
    """创建 Anthropic 兼容客户端，自动应用代理配置"""
    if HTTPS_PROXY and "HTTPS_PROXY" not in os.environ:
        os.environ["HTTPS_PROXY"] = HTTPS_PROXY

    return anthropic.Anthropic(
        api_key=api_key or MINIMAX_API_KEY,
        base_url=base_url or MINIMAX_API_BASE,
        timeout=timeout,
        max_retries=max_retries,
    )


def create_async_anthropic_client(
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 120.0,
    max_retries: int = 2,
) -> anthropic.AsyncAnthropic:
    """创建异步 Anthropic 兼容客户端，自动应用代理配置"""
    if HTTPS_PROXY and "HTTPS_PROXY" not in os.environ:
        os.environ["HTTPS_PROXY"] = HTTPS_PROXY

    return anthropic.AsyncAnthropic(
        api_key=api_key or MINIMAX_API_KEY,
        base_url=base_url or MINIMAX_API_BASE,
        timeout=timeout,
        max_retries=max_retries,
    )
