"""
shared/markdown_router.py
文档分类路由（按章节挂载上下文）
解决 Phase3 Token 爆炸问题，按需路由 Markdown 内容到对应章节
"""
from __future__ import annotations

import fnmatch
from typing import Any


class MarkdownRouter:
    """
    按章节路由 Markdown 上下文
    - 结构化 JSON：全量传入（数据基座）
    - 非结构化 Markdown：按文件/章节维度按需挂载
    """

    CHAPTER_FILE_MAP: dict[int, list[str]] = {
        1: ["*公司基本情况*", "*工商信息*"],       # 申请人基本信息
        2: ["*尽调报告*", "*经营情况*"],           # 申请人经营情况
        3: ["*审计报告*", "*财务*", "*资产负债表*"], # 申请人财务状况
        4: ["*征信*", "*融资*"],                   # 申请人信用状况
        5: ["*行业*", "*市场*"],                   # 行业地位比较分析
        6: ["*诉讼*", "*舆情*", "*负面*"],         # 其他重要事项
        7: ["*授信*", "*用途*"],                   # 授信用途及还款来源
        8: ["*担保*", "*抵押*"],                   # 担保情况
        9: ["*风险*", "*收益*"],                   # 授信收益与风险分析
        10: [],  # 结论章节主要依赖结构化数据，无需额外 Markdown
    }

    def route(self, chapter: int, markdown_by_filename: dict[str, str]) -> str:
        """
        根据章节号，返回该章节相关的 Markdown 内容

        策略：
        1. 精确匹配文件名含有关键词的内容块
        2. 避免全量发送，只发送相关文件
        """
        patterns = self.CHAPTER_FILE_MAP.get(chapter, [])
        if not patterns:
            return ""  # 结论章节无需额外上下文

        relevant_chunks: list[str] = []
        for fname, content in markdown_by_filename.items():
            if any(self._match_pattern(fname, p) for p in patterns):
                relevant_chunks.append(f"\n\n## {fname}\n\n{content[:5000]}")  # 截断防爆

        return "\n".join(relevant_chunks)

    def _match_pattern(self, filename: str, pattern: str) -> bool:
        return fnmatch.fnmatch(filename.lower(), pattern.replace("*", "*"))
