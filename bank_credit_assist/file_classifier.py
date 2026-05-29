"""
file_classifier.py
智能文件分类器 — 混合策略（文件名规则 + LLM + MinerU 解析内容）
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from shared.data_schema import (
    UNIFIED_DOCUMENT_LIST,
    CLASSIFICATION_KEYWORDS,
    CLASSIFICATION_EXTENSION_HINTS,
    CLASSIFICATION_CONFIDENCE_HIGH,
    CLASSIFICATION_CONFIDENCE_MEDIUM,
    CLASSIFICATION_CONFIDENCE_LOW,
)
from shared.llm_client import create_async_anthropic_client
from shared.config import MINIMAX_MODEL

logger = logging.getLogger("file_classifier")


@dataclass
class ClassificationResult:
    """单个文件的分类结果"""
    filename: str
    suggested_code: Optional[str] = None
    suggested_name: Optional[str] = None
    confidence: str = CLASSIFICATION_CONFIDENCE_LOW
    method: str = ""
    all_scores: dict[str, float] = field(default_factory=dict)
    error: Optional[str] = None


class FileClassifier:
    """两层分类器：规则引擎 + LLM 内容分析"""

    def __init__(self, use_llm: bool = True) -> None:
        self.use_llm = use_llm
        self._code_map: dict[str, str] = {
            doc["code"]: doc["name"] for doc in UNIFIED_DOCUMENT_LIST
        }
        # 预处理关键词：小写、按长度降序（长关键词优先）
        self._keywords: list[tuple[str, list[str]]] = sorted(
            [(kw.lower(), codes) for kw, codes in CLASSIFICATION_KEYWORDS.items()],
            key=lambda x: -len(x[0]),
        )

    # ------------------------------------------------------------------
    # Layer 1: 文件名规则匹配（同步）
    # ------------------------------------------------------------------

    def classify_by_filename(self, filename: str) -> ClassificationResult:
        stem, ext = self._split_filename(filename)
        stem_lower = stem.lower()
        candidates: dict[str, float] = {}

        # (a) 关键词匹配
        for kw, codes in self._keywords:
            if kw in stem_lower:
                score = self._keyword_score(kw, stem_lower)
                for code in codes:
                    candidates[code] = max(candidates.get(code, 0.0), score)

        # (b) 扩展名提示
        ext_lower = ext.lower()
        hint_codes = CLASSIFICATION_EXTENSION_HINTS.get(ext_lower, [])
        for code in hint_codes:
            candidates[code] = max(candidates.get(code, 0.0), 0.3)

        if not candidates:
            return ClassificationResult(
                filename=filename,
                confidence=CLASSIFICATION_CONFIDENCE_LOW,
                method="rule_filename",
            )

        sorted_codes = sorted(candidates.items(), key=lambda x: -x[1])
        best_code, best_score = sorted_codes[0]
        second_score = sorted_codes[1][1] if len(sorted_codes) > 1 else 0.0

        if best_score >= 0.9 and (best_score - second_score) > 0.2:
            confidence = CLASSIFICATION_CONFIDENCE_HIGH
        elif best_score >= 0.5:
            confidence = CLASSIFICATION_CONFIDENCE_MEDIUM
        else:
            confidence = CLASSIFICATION_CONFIDENCE_LOW

        return ClassificationResult(
            filename=filename,
            suggested_code=best_code,
            suggested_name=self._code_map.get(best_code),
            confidence=confidence,
            method="rule_filename",
            all_scores={code: round(score, 2) for code, score in sorted_codes[:3]},
        )

    def _keyword_score(self, keyword: str, stem: str) -> float:
        kw_len = len(keyword)
        stem_len = len(stem)
        if kw_len == stem_len:
            return 1.0
        if stem.startswith(keyword):
            return 0.95
        base = 0.85
        ratio = kw_len / max(stem_len, 1)
        if ratio < 0.3:
            base -= 0.15
        return base

    def _split_filename(self, filename: str) -> tuple[str, str]:
        p = Path(filename)
        return p.stem, p.suffix.lower()

    # ------------------------------------------------------------------
    # Layer 2: LLM + MinerU Markdown 内容（异步）
    # ------------------------------------------------------------------

    async def classify_by_content(
        self, filename: str, markdown_content: str
    ) -> ClassificationResult:
        """使用 LLM 基于 MinerU 解析后的 Markdown 内容进行分类"""
        category_desc = "\n".join(
            f"  - {doc['code']}: {doc['name']}（类别{doc['category']}）"
            for doc in UNIFIED_DOCUMENT_LIST
        )
        content_preview = markdown_content[:3000]

        prompt = (
            "你是一个银行对公信贷系统的档案分类专家。根据文件名和文件解析后的文本内容，"
            "判断该文件属于哪个文档类别。\n\n"
            f"可用类别：\n{category_desc}\n\n"
            f"文件名：{filename}\n\n"
            f"文件内容（前3000字符）：\n{content_preview}\n\n"
            "请只返回 JSON 格式，不要包含其他文字：\n"
            '{"code": "A1", "reason": "文件内容包含营业执照信息，如统一社会信用代码等"}'
        )

        try:
            client = create_async_anthropic_client(timeout=30.0)
            resp = await client.messages.create(
                model=MINIMAX_MODEL,
                max_tokens=200,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text if resp.content else "{}"
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("\n```", 1)[0]

            result = json.loads(text)
            code = result.get("code")
            if code and code in self._code_map:
                return ClassificationResult(
                    filename=filename,
                    suggested_code=code,
                    suggested_name=self._code_map[code],
                    confidence=CLASSIFICATION_CONFIDENCE_MEDIUM,
                    method="llm_content",
                    all_scores={code: 0.7},
                )
            return ClassificationResult(
                filename=filename,
                confidence=CLASSIFICATION_CONFIDENCE_LOW,
                method="llm_content",
                error=result.get("reason", "LLM 无法分类"),
            )
        except Exception as e:
            logger.warning(f"LLM classification failed for {filename}: {e}")
            return ClassificationResult(
                filename=filename,
                confidence=CLASSIFICATION_CONFIDENCE_LOW,
                method="llm_content",
                error=str(e),
            )

    # ------------------------------------------------------------------
    # 批量入口
    # ------------------------------------------------------------------

    async def classify_batch(
        self,
        parsed_files: dict[str, str],
    ) -> list[ClassificationResult]:
        """
        批量分类已通过 MinerU 解析的文件。

        参数:
            parsed_files: {filename: markdown_content}

        返回:
            [ClassificationResult, ...]
        """
        # Layer 1: 同步规则匹配
        results: dict[str, ClassificationResult] = {}
        for fname in parsed_files:
            results[fname] = self.classify_by_filename(fname)

        # 找出需要 LLM 兜底的文件
        low_conf_files = [
            (fname, parsed_files[fname])
            for fname, r in results.items()
            if r.confidence == CLASSIFICATION_CONFIDENCE_LOW and self.use_llm
        ]

        if low_conf_files:
            sem = asyncio.Semaphore(5)

            async def classify_one(fname: str, md: str) -> None:
                async with sem:
                    results[fname] = await self.classify_by_content(fname, md)

            await asyncio.gather(
                *(classify_one(fname, md) for fname, md in low_conf_files),
                return_exceptions=True,
            )

        return [results[fname] for fname in parsed_files]
