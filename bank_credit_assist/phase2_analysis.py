"""
phase2_analysis.py
Phase 2: 财务分析 + 科技型中小企业特征提取
- 从 Markdown 提取财务表格数据
- 计算基础财务指标 + 成长性指标
- 提取科技型中小企业特有指标（含数据溯源）
"""
from __future__ import annotations

import re
import io
import json
import pandas as pd
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from bs4 import BeautifulSoup


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class MetricWithSource:
    """
    带数据溯源的指标
    所有财务/科技指标统一使用此数据结构，
    确保每条数据都可追溯到来源文件。
    """
    metric: str              # 指标名称，如"研发费用占比"
    value: Any               # 指标值
    unit: str | None = None  # 单位（%、万元、个等）
    source_file: str | None = None       # 来源文件名
    source_location: str | None = None   # 文件内位置（"第3个表格"、"第5段"等）
    confidence_score: float = 1.0         # 置信度 0.0-1.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FinancialMetricsResult:
    """财务分析结果（含溯源）"""
    profitability: list[MetricWithSource] = field(default_factory=list)    # 盈利能力
    liquidity: list[MetricWithSource] = field(default_factory=list)         # 偿债能力
    leverage: list[MetricWithSource] = field(default_factory=list)          # 杠杆水平
    operation: list[MetricWithSource] = field(default_factory=list)         # 营运能力
    growth: list[MetricWithSource] = field(default_factory=list)            # 成长能力（新增）
    summary: dict[str, Any] = field(default_factory=dict)                  # 关键科目汇总


@dataclass
class TechInnovationResult:
    """科技型中小企业特征结果（含溯源）"""
    rd_expense_ratio: MetricWithSource | None = None     # 研发费用占比
    rd_expense_growth: MetricWithSource | None = None   # 研发费用增长率
    core_team_size: MetricWithSource | None = None      # 核心技术团队规模
    core_team_summary: str | None = None                # 核心团队履历摘要
    high_tech_certificate: MetricWithSource | None = None # 高新技术企业证书
    ip_patent_count: MetricWithSource | None = None     # 核心知识产权/专利数量
    software_copyright_count: MetricWithSource | None = None  # 软件著作权数量
    tech_revenue_ratio: MetricWithSource | None = None  # 高新技术产品收入占比


# ============================================================================
# 辅助函数
# ============================================================================

def _extract_tables_from_markdown(markdown_content: str) -> dict[str, list[list[str]]]:
    """
    从 Markdown 文本中提取所有表格（Markdown 格式 + HTML 格式）
    返回: {table_header: [[row1], [row2], ...]}

    提取顺序：
    1. 正则提取标准 Markdown 表格
    2. BeautifulSoup + pandas 提取 HTML <table> 标签
    """
    tables: dict[str, list[list[str]]] = {}

    # ── 1. Markdown 表格（原有正则逻辑）──────────────────────────────
    md_table_pattern = re.compile(
        r'^\|(.+?)\|\s*\n\|[-:\s|]+\|\s*\n((?:\|.+\|\s*\n)+)',
        re.MULTILINE
    )

    for match in md_table_pattern.finditer(markdown_content):
        header: str = match.group(1).strip()
        rows_text: str = match.group(2)

        rows: list[list[str]] = []
        for row_line in rows_text.strip().split('\n'):
            cells: list[str] = [
                c.strip() for c in row_line.split('|')[1:-1]
            ]
            rows.append(cells)

        tables[header] = rows

    # ── 2. HTML 表格（BeautifulSoup + pandas）───────────────────────
    html_table_pattern = re.compile(r'<table.*?>.*?</table>', re.DOTALL | re.IGNORECASE)
    html_counter = 0

    for match in html_table_pattern.finditer(markdown_content):
        html_str = match.group(0)
        try:
            dfs = pd.read_html(io.StringIO(html_str))
            if not dfs:
                continue
            df = dfs[0]

            # 列名作为 header；若列名全是默认数字索引，则取前一段上下文文字作表头
            col_names = list(df.columns)
            if all(str(c).isdigit() or c == 0 for c in col_names):
                # 从 match 位置往前找一段非表格文字作为表名
                start = max(0, match.start() - 200)
                context = markdown_content[start:match.start()].strip().split('\n')[-1]
                header = f"HTML_Table_{html_counter}_[{context[:30]}]"
            else:
                header = " | ".join(str(c) for c in col_names)

            rows: list[list[str]] = [col_names]
            for _, row in df.iterrows():
                rows.append([str(v) for v in row.tolist()])

            tables[f"HTML_Table_{html_counter}"] = rows
            html_counter += 1
        except Exception:
            # 残缺 HTML 解析失败则跳过，不影响其他提取
            pass

    return tables


def _find_value_in_table(
    tables: dict[str, list[list[str]]],
    keywords: list[str],
    value_column: int = 1,
    year_columns: list[int] | None = None,
) -> dict[str, Any] | None:
    """
    在表格中搜索包含关键词的行，返回指定列的值
    """
    for header, rows in tables.items():
        for row in rows:
            if not row:
                continue
            row_text: str = " ".join(row)
            if any(kw in row_text for kw in keywords):
                if year_columns:
                    result: dict[str, Any] = {}
                    for col in year_columns:
                        if col < len(row):
                            try:
                                result[f"col_{col}"] = float(re.sub(r'[^\d.-]', '', row[col]))
                            except ValueError:
                                result[f"col_{col}"] = row[col]
                    return result
                else:
                    if value_column < len(row):
                        return {"value": row[value_column]}
    return None


def _parse_number(text: str) -> float | None:
    """从文本中解析数字"""
    if not text:
        return None
    # 处理万元、亿元等单位
    text = text.strip()
    multipliers: dict[str, float] = {"万": 1e4, "亿": 1e8, "千": 1e3, "%": 0.01}
    for unit, mult in multipliers.items():
        if unit in text:
            try:
                return float(re.sub(r'[^\d.-]', '', text)) * mult
            except ValueError:
                return None
    try:
        return float(re.sub(r'[^\d.-]', '', text))
    except ValueError:
        return None


# ============================================================================
# 核心：财务指标计算
# ============================================================================

async def compute_financial_metrics(
    markdown_content: str,
    source_file: str = "企业尽调资料.md",
) -> FinancialMetricsResult:
    """
    从 Markdown 内容计算财务指标（含数据溯源）
    """
    tables: dict[str, list[list[str]]] = _extract_tables_from_markdown(markdown_content)
    result: FinancialMetricsResult = FinancialMetricsResult()

    # ── 1. 盈利能力 ──
    income_keywords: list[str] = ["损益表", "利润表", "利润及利润分配表"]
    for kw in income_keywords:
        if kw in tables:
            rows: list[list[str]] = tables[kw]
            for row in rows:
                row_text: str = " ".join(row)
                # 净利润
                if "净利润" in row_text and len(row) >= 2:
                    try:
                        net_profit: float = _parse_number(row[-1])
                        result.profitability.append(MetricWithSource(
                            metric="净利润",
                            value=net_profit,
                            unit="万元",
                            source_file=source_file,
                            source_location=f"{kw}第{rows.index(row)+1}行",
                            confidence_score=0.95,
                        ))
                    except (ValueError, IndexError):
                        pass
                # 营业收入
                if "营业收入" in row_text or "营业总收入" in row_text:
                    try:
                        revenue: float = _parse_number(row[-1])
                        result.profitability.append(MetricWithSource(
                            metric="营业收入",
                            value=revenue,
                            unit="万元",
                            source_file=source_file,
                            source_location=f"{kw}第{rows.index(row)+1}行",
                            confidence_score=0.95,
                        ))
                    except (ValueError, IndexError):
                        pass
                # 毛利率
                if "毛利" in row_text:
                    try:
                        gross_margin: float = _parse_number(row[-1])
                        result.profitability.append(MetricWithSource(
                            metric="毛利率",
                            value=gross_margin,
                            unit="%",
                            source_file=source_file,
                            source_location=f"{kw}第{rows.index(row)+1}行",
                            confidence_score=0.90,
                        ))
                    except (ValueError, IndexError):
                        pass

    # ── 2. 偿债能力（从资产负债表提取） ──
    balance_keywords: list[str] = ["资产负债表", "财务状况表"]
    for kw in balance_keywords:
        if kw in tables:
            rows: list[list[str]] = tables[kw]
            for row in rows:
                row_text: str = " ".join(row)
                # 流动资产/流动负债（计算流动比率）
                if "流动资产" in row_text:
                    try:
                        current_assets: float = _parse_number(row[-1])
                        for r2 in rows:
                            if "流动负债" in " ".join(r2):
                                current_liab: float = _parse_number(r2[-1])
                                if current_liab and current_liab > 0:
                                    ratio: float = current_assets / current_liab
                                    result.liquidity.append(MetricWithSource(
                                        metric="流动比率",
                                        value=round(ratio, 2),
                                        unit="倍",
                                        source_file=source_file,
                                        source_location=f"{kw}流动资产/流动负债",
                                        confidence_score=0.90,
                                    ))
                                break
                    except (ValueError, IndexError):
                        pass

                # 资产负债率
                if "负债合计" in row_text or "总负债" in row_text:
                    try:
                        total_liab: float = _parse_number(row[-1])
                        for r2 in rows:
                            if "资产总计" in " ".join(r2):
                                total_assets: float = _parse_number(r2[-1])
                                if total_assets and total_assets > 0:
                                    debt_ratio: float = (total_liab / total_assets) * 100
                                    result.leverage.append(MetricWithSource(
                                        metric="资产负债率",
                                        value=round(debt_ratio, 2),
                                        unit="%",
                                        source_file=source_file,
                                        source_location=f"{kw}负债合计/资产总计",
                                        confidence_score=0.95,
                                    ))
                                break
                    except (ValueError, IndexError):
                        pass

    # ── 3. 成长性指标 ──
    revenue_history: list[float] = []
    for kw in income_keywords:
        if kw in tables:
            for row in tables[kw]:
                if "营业收入" in " ".join(row) and len(row) >= 4:
                    for col_idx in range(1, min(len(row), 4)):
                        val: float | None = _parse_number(row[-col_idx])
                        if val and val > 0:
                            revenue_history.append(val)
                            break

    if len(revenue_history) >= 2:
        cagr: float = (revenue_history[0] / revenue_history[-1]) ** (1.0 / (len(revenue_history) - 1)) - 1
        result.growth.append(MetricWithSource(
            metric="近三年营收复合增长率(CAGR)",
            value=round(cagr * 100, 2),
            unit="%",
            source_file=source_file,
            source_location=f"{income_keywords[0]}营业收入历史数据",
            confidence_score=0.85,
        ))

    return result


# ============================================================================
# 核心：科技型中小企业特征提取
# ============================================================================

async def extract_tech_innovation_metrics(
    markdown_content: str,
    source_file: str = "企业尽调资料.md",
) -> TechInnovationResult:
    """
    从 Markdown 中提取科技型中小企业特有指标
    """
    result: TechInnovationResult = TechInnovationResult()
    tables: dict[str, list[list[str]]] = _extract_tables_from_markdown(markdown_content)

    # ── 1. 研发费用占比 ──
    rd_expense: float | None = None
    revenue: float | None = None

    for header, rows in tables.items():
        for row in rows:
            row_text: str = " ".join(row)
            if "研发费用" in row_text or "研究开发费" in row_text:
                rd_expense = _parse_number(row[-1])
            if ("营业收入" in row_text or "营业总收入" in row_text) and "研发" not in row_text:
                revenue = _parse_number(row[-1])

    if rd_expense and revenue and revenue > 0:
        rd_ratio: float = (rd_expense / revenue) * 100
        result.rd_expense_ratio = MetricWithSource(
            metric="研发费用占营业收入比例",
            value=round(rd_ratio, 2),
            unit="%",
            source_file=source_file,
            source_location="损益表（研发费用/营业收入）",
            confidence_score=0.95,
        )

    # ── 2. 核心技术团队履历摘要 ──
    team_keywords: list[str] = ["核心技术团队", "研发团队", "管理团队", "董事", "监事", "高级管理人员"]

    team_size_patterns: list[re.Pattern] = [
        re.compile(r'研发人员[：:]\s*(\d+)'),
        re.compile(r'技术人员[：:]\s*(\d+)'),
        re.compile(r'硕士以上[：:]\s*(\d+)'),
        re.compile(r'博士[：:]\s*(\d+)'),
    ]
    for pat in team_size_patterns:
        m: re.Match | None = pat.search(markdown_content)
        if m:
            result.core_team_size = MetricWithSource(
                metric="核心技术团队规模",
                value=int(m.group(1)),
                unit="人",
                source_file=source_file,
                source_location="团队相关表格",
                confidence_score=0.90,
            )
            break

    # ── 3. 高新技术企业证书有效性 ──
    cert_patterns: list[re.Pattern] = [
        re.compile(r'高新技术企业证书[^\n\d]*[（(]\s*证书编号[）)][^\n\d]*[：:]\s*([A-Z0-9]+)'),
        re.compile(r'高新技术企业[^\n]*?有效期[^\n]*?至\s*(\d{4})[年/](\d{1,2})[月/]?(\d{0,2})'),
        re.compile(r'高新证书[^\n]*?编号[：:]\s*([A-Z0-9]+)'),
    ]
    for pat in cert_patterns:
        m: re.Match | None = pat.search(markdown_content)
        if m:
            if len(m.groups()) >= 3:
                year: int = int(m.group(1))
                month: int = int(m.group(2))
                is_valid: bool = (year > 2026) or (year == 2026 and month >= 4)
                result.high_tech_certificate = MetricWithSource(
                    metric="高新技术企业证书",
                    value="有效" if is_valid else f"有效期至{year}年{month}月",
                    unit="",
                    source_file=source_file,
                    source_location="资质证书表格",
                    confidence_score=0.95,
                )
            else:
                result.high_tech_certificate = MetricWithSource(
                    metric="高新技术企业证书编号",
                    value=m.group(1),
                    unit="",
                    source_file=source_file,
                    source_location="资质证书表格",
                    confidence_score=0.90,
                )
            break

    # ── 4. 核心知识产权/专利数量 ──
    ip_patterns: list[re.Pattern] = [
        re.compile(r'专利[^\n]*?共[^\n]*?(\d+)\s*项'),
        re.compile(r'发明专利[^\n]*?(\d+)\s*项'),
        re.compile(r'实用新型专利[^\n]*?(\d+)\s*项'),
        re.compile(r'软件著作权[^\n]*?(\d+)\s*项'),
        re.compile(r'知识产权[^\n]*?(\d+)\s*项'),
    ]
    for pat in ip_patterns:
        m = pat.search(markdown_content)
        if m:
            count: int = int(m.group(1))
            if "专利" in pat.pattern and "发明" in pat.pattern:
                result.ip_patent_count = MetricWithSource(
                    metric="发明专利数量",
                    value=count,
                    unit="项",
                    source_file=source_file,
                    source_location="知识产权相关表格",
                    confidence_score=0.90,
                )
            elif "软件著作权" in pat.pattern:
                result.software_copyright_count = MetricWithSource(
                    metric="软件著作权数量",
                    value=count,
                    unit="项",
                    source_file=source_file,
                    source_location="知识产权相关表格",
                    confidence_score=0.90,
                )
            else:
                result.ip_patent_count = MetricWithSource(
                    metric="知识产权/专利数量",
                    value=count,
                    unit="项",
                    source_file=source_file,
                    source_location="知识产权相关表格",
                    confidence_score=0.90,
                )
            break

    return result


# ============================================================================
# 便捷封装
# ============================================================================

async def run_financial_analysis(
    markdown_content: str,
    source_file: str = "企业尽调资料.md",
) -> dict[str, Any]:
    """
    执行完整财务分析（基础指标 + 成长性指标）
    """
    result: FinancialMetricsResult = await compute_financial_metrics(
        markdown_content, source_file
    )

    return {
        "profitability": [m.to_dict() for m in result.profitability],
        "liquidity": [m.to_dict() for m in result.liquidity],
        "leverage": [m.to_dict() for m in result.leverage],
        "operation": [m.to_dict() for m in result.operation],
        "growth": [m.to_dict() for m in result.growth],
        "summary": result.summary,
    }
