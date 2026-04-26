"""
shared/gemini_client.py
Gemini 客户端（代理支持）
"""
from __future__ import annotations

import os
import google.generativeai as genai

from shared.config import GEMINI_API_KEY, GEMINI_MODEL, HTTPS_PROXY

# 配置代理
if HTTPS_PROXY:
    os.environ["HTTPS_PROXY"] = HTTPS_PROXY

# 配置 API Key
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


def get_model(model_name: str | None = None):
    """获取 Gemini 模型实例"""
    return genai.GenerativeModel(model_name or GEMINI_MODEL)
