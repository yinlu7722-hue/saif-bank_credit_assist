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
import unicodedata
import pandas as pd
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from shared.utils import safe_print as _safe_print


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

    # ── Unicode 规范化：CJK 兼容表意文字 → 标准 Unicode ─────────
    # 如 \uf9dd (利) → \u5229，解决 MinerU 输出中非标准字符匹配问题
    markdown_content = unicodedata.normalize('NFKC', markdown_content)

    # ── 1. Markdown 表格（增强版：识别表格前标题文本作为表名）──────
    md_table_pattern = re.compile(
        r'^\|(.+?)\|\s*\n\|[-:\s|]+\|\s*\n((?:\|.+\|\s*\n)+)',
        re.MULTILINE
    )

    for match in md_table_pattern.finditer(markdown_content):
        header: str = match.group(1).strip()
        rows_text: str = match.group(2)

        # 解析数据行
        rows: list[list[str]] = []
        data_lines = [l for l in rows_text.strip().split('\n') if l.strip()]
        for row_line in data_lines:
            cells: list[str] = [
                c.strip() for c in row_line.split('|')[1:-1]
            ]
            if any(c for c in cells):
                rows.append(cells)

        # ── 表名智能识别 ──────────────────────────────────
        # 如果 header 全是数字索引 (0, 1, 2...) 或列索引，往前查找真实表名
        is_numeric_header = all(
            c.strip().isdigit() or c.strip() == '' or c.strip() in ('0', '1', '2', '3', '4', '5', '6', '7', '8', '9')
            for c in header.split('|')
        )

        actual_table_name = header
        if is_numeric_header:
            # 向前搜索：找到最近的含中文或括号的非表格行
            start = max(0, match.start() - 500)
            context_lines = markdown_content[start:match.start()].split('\n')
            found_name = None
            for line in reversed(context_lines):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                if line_stripped.startswith('|') or line_stripped.startswith('!'):
                    continue
                # 包含中文字符或括号 → 很可能是表名
                if any('\u4e00' <= c <= '\u9fff' for c in line_stripped):
                    found_name = line_stripped
                    # 清理 Markdown 标题标记 (##, ###等)
                    found_name = re.sub(r'^#+\s*', '', found_name)
                    break
            if found_name:
                actual_table_name = found_name
            elif data_lines:
                # 回退：用第一数据行作为标识
                first_cells = [c.strip() for c in data_lines[0].split('|')[1:-1]]
                real_headers = [c for c in first_cells if c]
                if real_headers:
                    actual_table_name = " | ".join(real_headers)

        tables[actual_table_name] = rows

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


from shared.parsing import parse_number


def _extract_from_text(markdown_content: str) -> dict[str, float | None]:
    """
    从 Markdown 纯文本中提取财务指标（后备方案）
    当表格解析失败时，通过正则表达式从文本中提取
    """
    extracted: dict[str, float | None] = {}

    # 通用数字匹配模式（处理负数、括号、逗号分隔等）
    NUM = r'[（-]?\s*[\d，,，.。·\s]+\s*[）%]?\s*[万元]?'  # 宽松数字模式
    # 严格数字模式
    STRICT_NUM = r'-?\s*[\d,，]+(?:\.\d+)?'

    # ── 净利润 ──
    patterns = [
        r'净利润[：:\s　]*' + STRICT_NUM,  # 净利润：1234.56
        r'净利润[^\d\n]*?(' + STRICT_NUM.replace('?', '') + r')',
        r'归属.*?净利润[^\d\n]*?(' + STRICT_NUM.replace('?', '') + r')',
    ]
    for pat in patterns:
        m = re.search(pat, markdown_content)
        if m:
            raw = m.group(1) if m.lastindex else m.group(0).split('净利润')[1].lstrip('：: \t　')
            val = parse_number(raw)
            if val is not None:
                extracted["net_profit"] = val
                break

    # ── 营业收入 ──
    patterns = [
        r'营业收入[：:\s　]*' + STRICT_NUM,
        r'营业总收入[：:\s　]*' + STRICT_NUM,
        r'营业收(?:入|总收入)[^\d\n]*?(' + STRICT_NUM.replace('?', '') + r')',
    ]
    for pat in patterns:
        m = re.search(pat, markdown_content)
        if m:
            raw = m.group(1) if m.lastindex else re.split(r'营业收(?:入|总收入)', m.group(0))[-1].lstrip('：: \t　')
            val = parse_number(raw)
            if val is not None:
                extracted["operating_revenue"] = val
                break

    # ── 毛利率 ──
    patterns = [
        r'毛利率[：:\s　]*' + r'(-?\s*[\d.]+)\s*%?',
        r'毛利率[^\d\n]*?(-?\s*[\d.]+)',
    ]
    for pat in patterns:
        m = re.search(pat, markdown_content)
        if m:
            val = parse_number(m.group(1))
            if val is not None:
                extracted["gross_margin"] = val
                break

    # ── 流动比率 ──
    patterns = [
        r'流动比率[：:\s　]*' + r'(-?\s*[\d.]+)',
        r'流动比率[^\d\n]*?(-?\s*[\d.]+)',
    ]
    for pat in patterns:
        m = re.search(pat, markdown_content)
        if m:
            val = parse_number(m.group(1))
            if val is not None:
                extracted["current_ratio"] = val
                break

    # ── 资产负债率 ──
    patterns = [
        r'资产负债率[：:\s　]*' + r'(-?\s*[\d.]+)\s*%?',
        r'资产负债率[^\d\n]*?(-?\s*[\d.]+)',
    ]
    for pat in patterns:
        m = re.search(pat, markdown_content)
        if m:
            val = parse_number(m.group(1))
            if val is not None:
                extracted["debt_to_asset_ratio"] = val
                break

    # ── 研发费用占比 ──
    rd_patterns = [
        # 直接匹配占比数值（各种说法）
        r'研发费用[^\d\n]*?占比[^\d\n]*?(' + STRICT_NUM.replace('?', '') + r')\s*%?',
        r'研发投入[^\d\n]*?占比[^\d\n]*?(' + STRICT_NUM.replace('?', '') + r')\s*%?',
        r'研发支出[^\d\n]*?占比[^\d\n]*?(' + STRICT_NUM.replace('?', '') + r')\s*%?',
        r'研发费用占营业收入[^\d\n]*?比重[^\d\n]*?(' + STRICT_NUM.replace('?', '') + r')\s*%?',
        r'研发费用占营业收入比例[^\d\n]*?(' + STRICT_NUM.replace('?', '') + r')\s*%?',
        # 研发费用/营业收入 直接比值
        r'研发费用[^\d]*?(' + STRICT_NUM.replace('?', '') + r')[^\d\n]*?营业收入[^\d]*?(' + STRICT_NUM.replace('?', '') + r')',
        # 研发投入/营业收入 比值
        r'研发投入[^\d]*?(' + STRICT_NUM.replace('?', '') + r')[^\d\n]*?营业收入[^\d]*?(' + STRICT_NUM.replace('?', '') + r')',
    ]
    for pat in rd_patterns:
        m = re.search(pat, markdown_content)
        if m:
            if m.lastindex == 2:
                # 两组数字：研发费用 和 营业收入
                rd = parse_number(m.group(1))
                rev = parse_number(m.group(2))
                if rd and rev and rev > 0:
                    extracted["rd_expense_ratio"] = round((rd / rev) * 100, 2)
                    break
            else:
                # 单个数值：直接是占比
                val = parse_number(m.group(1))
                if val is not None:
                    extracted["rd_expense_ratio"] = val
                    break

    # ── 营收CAGR（复合增长率） ──
    cagr_patterns = [
        r'CAGR[^\d]*?(' + STRICT_NUM.replace('?', '') + r')\s*%?',  # CAGR 30%
        r'复合增长率[^\d]*?(' + STRICT_NUM.replace('?', '') + r')\s*%?',  # 复合增长率 25%
        r'营收.*?复合增长率[^\d]*?(' + STRICT_NUM.replace('?', '') + r')\s*%?',  # 营收复合增长率 25%
        r'营业收.*?复合增长.*?(' + STRICT_NUM.replace('?', '') + r')\s*%?',  # 营业收入复合增长率 25%
        r'近[一二三四两\d]+年.*?复合增长.*?(' + STRICT_NUM.replace('?', '') + r')\s*%?',  # 近三年复合增长率 25%
        r'复合增长.*?年.*?(' + STRICT_NUM.replace('?', '') + r')\s*%?',  # 复合增长率（年）25%
    ]
    for pat in cagr_patterns:
        m = re.search(pat, markdown_content)
        if m:
            val = parse_number(m.group(1))
            if val is not None and 0 < val < 100:  # CAGR 通常在 0-100% 之间
                extracted["revenue_cagr"] = val
                break

    _safe_print(f"[_extract_from_text] Extracted: {extracted}")
    return extracted


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

    # ── 年份识别 ───────────────────────────────────────────────
    year_pattern = re.compile(r'(20\d{2})')
    import datetime as _dt
    _target_year = _dt.date.today().year - 1

    def _find_target_column(rows_t: list[list[str]]) -> int:
        for row_idx in range(min(3, len(rows_t))):
            for col_idx in range(1, len(rows_t[row_idx])):
                m = year_pattern.search(str(rows_t[row_idx][col_idx]))
                if m and int(m.group(1)) == _target_year:
                    return col_idx
        candidates: list[tuple[int, int]] = []
        for row_idx in range(min(3, len(rows_t))):
            for col_idx in range(1, len(rows_t[row_idx])):
                m = year_pattern.search(str(rows_t[row_idx][col_idx]))
                if m:
                    y = int(m.group(1))
                    if y <= _target_year:
                        candidates.append((y, col_idx))
        if candidates:
            candidates.sort(key=lambda x: -x[0])
            return candidates[0][1]
        return -1

    def _find_all_tables(keywords: list[str]) -> list[tuple[str, list[list[str]]]]:
        """按表名关键词匹配，合并表优先"""
        matches: list[tuple[int, str, list[list[str]]]] = []
        for k in tables:
            for kw in keywords:
                if kw in k:
                    matches.append((0 if "合并" in k else 1, k, tables[k]))
                    break
        matches.sort(key=lambda x: x[0])
        return [(name, rows) for _, name, rows in matches]

    def _find_table_by_content(content_keywords: list[str]) -> tuple[str, list[list[str]]] | None:
        """按表内容匹配：扫描第一列，若含指定科目则识别为该类报表。合并表优先。"""
        candidates: list[tuple[int, str, list[list[str]]]] = []
        for k, rows in tables.items():
            first_col_text = " ".join([r[0] for r in rows if r])
            if any(kw in first_col_text for kw in content_keywords):
                candidates.append((0 if "合并" in k else 1, k, rows))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        _, name, rows = candidates[0]
        return name, rows

    def _col_val(row: list[str], col_idx: int | None = None) -> float | None:
        if col_idx is not None and 0 <= col_idx < len(row):
            return parse_number(row[col_idx])
        for i in range(len(row) - 1, 0, -1):
            v = parse_number(row[i])
            if v is not None:
                return v
        return None

    
    # ── 选择最佳报表（内容匹配优先，表名匹配回退）──────────
    # 资产负债表：内容匹配（资产总计/负债合计）优先，表名匹配回退
    bs_table = (_find_table_by_content(["资产总计", "总资产", "负债合计", "所有者权益"])
                or (_find_all_tables(["资产负债表", "财务状况表"]) or [None])[0])
    # 利润表：内容匹配（营业收入/净利润）优先
    is_table = (_find_table_by_content(["营业收入", "净利润", "利润总额"])
                or (_find_all_tables(["损益表", "利润表", "利润及利润分配表"]) or [None])[0])
    # 现金流量表
    cf_table = (_find_table_by_content(["经营活动", "投资活动", "筹资活动"])
                or (_find_all_tables(["现金流量表", "现金流"]) or [None])[0])

    bs_name, bs_rows = bs_table if bs_table else ("", [])
    is_name, is_rows = is_table if is_table else ("", [])
    cf_name, cf_rows = cf_table if cf_table else ("", [])

    bs_col = _find_target_column(bs_rows) if bs_rows else -1
    is_col = _find_target_column(is_rows) if is_rows else -1
    cf_col = _find_target_column(cf_rows) if cf_rows else -1
    if bs_col < 0 and bs_rows and bs_rows[0]: bs_col = len(bs_rows[0]) - 1
    if is_col < 0 and is_rows and is_rows[0]: is_col = len(is_rows[0]) - 1
    if cf_col < 0 and cf_rows and cf_rows[0]: cf_col = len(cf_rows[0]) - 1

    report_type = "consolidated" if (bs_name and "合并" in bs_name) else ("standalone" if bs_table else "unknown")

    _safe_print(f"[compute_financial_metrics] BS={bs_name[:40] if bs_name else 'N/A'} col={bs_col}, IS={is_name[:40] if is_name else 'N/A'} col={is_col}, CF={cf_name[:40] if cf_name else 'N/A'} col={cf_col}, type={report_type}")
    result.summary["report_type"] = report_type

    # ── 1. 利润表提取 ────────────────────────────────────
    if is_table:
        for row in is_rows:
            label = row[0].strip() if row else ""
            val = _col_val(row, is_col)
            if val is None:
                continue
            if "净利润" in label and "归属于" not in label:
                result.profitability.append(MetricWithSource(metric="净利润", value=val, unit="万元", source_file=source_file, source_location=f"{is_name}", confidence_score=0.95))
            if any(kw in label for kw in ["营业收入", "营业总收入"]) and "营业总成本" not in label:
                result.profitability.append(MetricWithSource(metric="营业收入", value=val, unit="万元", source_file=source_file, source_location=f"{is_name}", confidence_score=0.95))
            if any(kw in label for kw in ["利润总额", "税前利润"]):
                result.profitability.append(MetricWithSource(metric="利润总额", value=val, unit="万元", source_file=source_file, source_location=f"{is_name}", confidence_score=0.95))
            if "营业成本" in label:
                result.profitability.append(MetricWithSource(metric="营业成本", value=val, unit="万元", source_file=source_file, source_location=f"{is_name}", confidence_score=0.95))

    # ── 2. 资产负债表提取 ────────────────────────────────
    if bs_table:
        for row in bs_rows:
            label = row[0].strip() if row else ""
            val = _col_val(row, bs_col)
            if val is None:
                continue

            if any(kw in label for kw in ["资产总计", "总资产"]):
                result.leverage.append(MetricWithSource(metric="总资产", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.95))
            if any(kw in label for kw in ["负债合计", "总负债"]) and "流动" not in label and "非流动" not in label:
                result.leverage.append(MetricWithSource(metric="总负债", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.95))
                for r2 in bs_rows:
                    if any(kw in " ".join(r2) for kw in ["资产总计", "总资产"]):
                        ta = _col_val(r2, bs_col)
                        if ta and ta > 0:
                            result.leverage.append(MetricWithSource(metric="资产负债率", value=round(val / ta * 100, 2), unit="%", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.95))
                            break
            if any(kw in label for kw in ["所有者权益", "股东权益", "净资产"]):
                result.leverage.append(MetricWithSource(metric="所有者权益", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.95))
            if "流动资产合计" in label:
                result.summary["current_assets"] = val
            if "流动负债合计" in label:
                result.summary["current_liabilities"] = val
            if "应收账款" in label and "坏账" not in label and "周转" not in label:
                result.operation.append(MetricWithSource(metric="应收账款", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.90))
            if "应付账款" in label and "周转" not in label:
                result.operation.append(MetricWithSource(metric="应付账款", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.90))
            if "存货" in label and "跌价" not in label and "周转" not in label:
                result.operation.append(MetricWithSource(metric="存货", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.90))
            if any(kw in label for kw in ["货币资金", "现金及"]):
                result.operation.append(MetricWithSource(metric="货币资金", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.90))
            if "交易性金融资产" in label:
                result.operation.append(MetricWithSource(metric="交易性金融资产", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.90))
            if "应收票据" in label:
                result.operation.append(MetricWithSource(metric="应收票据", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.90))
            if "短期借款" in label:
                result.leverage.append(MetricWithSource(metric="短期借款", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.90))
            if "应付票据" in label:
                result.leverage.append(MetricWithSource(metric="应付票据", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.90))
            if "长期借款" in label:
                result.leverage.append(MetricWithSource(metric="长期借款", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.90))
            if "应付债券" in label:
                result.leverage.append(MetricWithSource(metric="应付债券", value=val, unit="万元", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.90))

        ca = result.summary.get("current_assets")
        cl = result.summary.get("current_liabilities")
        if ca and cl and cl > 0:
            result.liquidity.append(MetricWithSource(metric="流动比率", value=round(ca / cl, 2), unit="倍", source_file=source_file, source_location=f"{bs_name}", confidence_score=0.90))

    # ── 3. 成长性 ──────────────────────────────────────
    revenue_history: list[float] = []
    if is_table:
        for row in is_rows:
            if "营业收入" in " ".join(row) and len(row) >= 4:
                for col_idx in range(1, len(row)):
                    val = parse_number(row[col_idx])
                    if val and 0 < val < 1e9:
                        revenue_history.append(val)
    if len(revenue_history) >= 2 and revenue_history[-1] > 0:
        cagr = (revenue_history[0] / revenue_history[-1]) ** (1.0 / (len(revenue_history) - 1)) - 1
        result.growth.append(MetricWithSource(metric="近三年营收复合增长率(CAGR)", value=round(cagr * 100, 2), unit="%", source_file=source_file, source_location="利润表历史数据", confidence_score=0.85))

    # ── 4. 现金流量表（正则匹配）─────────────────────────
    if cf_table:
        cf_patterns = [
            (r'经营.*?(?:净流量|净额|现金流量净额)', "经营性净现金流"),
            (r'投资.*?(?:净流量|净额|现金流量净额)', "投资性净现金流"),
            (r'(?:筹资|融资).*?(?:净流量|净额|现金流量净额)', "融资性净现金流"),
        ]
        for row in cf_rows:
            row_text = " ".join(row)
            for pat, metric_name in cf_patterns:
                if re.search(pat, row_text):
                    val = _col_val(row, cf_col)
                    if val is not None:
                        result.operation.append(MetricWithSource(metric=metric_name, value=val, unit="万元", source_file=source_file, source_location=f"{cf_name}", confidence_score=0.90))
                        break

    return result
# ============================================================================
# 核心：科技型中小企业特征提取
# ============================================================================

async def extract_tech_innovation_metrics(
    markdown_content: str,
    source_file: str = "企业尽调资料.md",
) -> dict[str, Any]:
    """
    从 Markdown 中提取科技型中小企业特有指标
    返回 dict 结构（供 FastAPI JSON 序列化）
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
                rd_expense = parse_number(row[-1])
            if ("营业收入" in row_text or "营业总收入" in row_text) and "研发" not in row_text:
                revenue = parse_number(row[-1])

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

    # ── 5. 文本后备提取（表格提取失败时） ──
    # 从全文文本中提取研发费用占比
    m_rd = re.search(r'研发费用[^\d]*([\d,]+\.?\d*)[^\d]*营业收入[^\d]*([\d,]+\.?\d*)', markdown_content)
    if m_rd and not result.rd_expense_ratio:
        rd_val = parse_number(m_rd.group(1))
        rev_val = parse_number(m_rd.group(2))
        if rd_val and rev_val and rev_val > 0:
            rd_ratio_text = round((rd_val / rev_val) * 100, 2)
            result.rd_expense_ratio = MetricWithSource(
                metric="研发费用占营业收入比例",
                value=rd_ratio_text,
                unit="%",
                source_file=source_file,
                source_location="文本正则提取",
                confidence_score=0.80,
            )

    # ── 返回扁平化 dict（兼容前端 JSON 展示） ──
    def _to_dict(ms: MetricWithSource | None) -> dict | None:
        if ms is None:
            return None
        return ms.to_dict()

    return {
        # 原始结构（保持兼容）
        "rd_expense_ratio": _to_dict(result.rd_expense_ratio),
        "rd_expense_growth": _to_dict(result.rd_expense_growth),
        "core_team_size": _to_dict(result.core_team_size),
        "core_team_summary": result.core_team_summary,
        "high_tech_cert": _to_dict(result.high_tech_certificate),
        "patent_count": (
            int(result.ip_patent_count.value)
            if result.ip_patent_count else None
        ),
        "team_size": (
            int(result.core_team_size.value)
            if result.core_team_size else None
        ),
    }


# ============================================================================
# 便捷封装
# ============================================================================

async def run_financial_analysis(
    markdown_content: str,
    source_file: str = "企业尽调资料.md",
) -> dict[str, Any]:
    """
    执行完整财务分析
    提取：资产负债表(总资产/总负债/所有者权益 + 细项) +
          利润表(营业收入/营业成本/利润总额/净利润) +
          现金流量表(经营/投资/融资净现金流)
    返回扁平化结构，兼容前端展示
    """
    result: FinancialMetricsResult = await compute_financial_metrics(
        markdown_content, source_file
    )

    def _get_metric_value(category: list, metric_name: str) -> float | None:
        """从 MetricWithSource 列表中查找指定指标名的值"""
        for m in category:
            name = m.metric if hasattr(m, "metric") else m.get("metric", "")
            if metric_name in name:
                v = m.value if hasattr(m, "value") else m.get("value")
                if v is not None:
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        pass
        return None

    text_extracted = _extract_from_text(markdown_content)

    def _merge(primary: float | None, secondary: float | None) -> float | None:
        return primary if primary is not None else secondary

    # ── 合并/非合并报表识别 ──
    is_consolidated = False
    for keyword in ["合并", "合并报表", "合并财务报表", "合并资产负债表"]:
        if keyword in markdown_content:
            is_consolidated = True
            break

    return {
        "profitability": [m.to_dict() for m in result.profitability],
        "liquidity": [m.to_dict() for m in result.liquidity],
        "leverage": [m.to_dict() for m in result.leverage],
        "operation": [m.to_dict() for m in result.operation],
        "growth": [m.to_dict() for m in result.growth],
        "summary": result.summary,
        # ── 资产负债表 ──
        "total_assets": _get_metric_value(result.leverage, "总资产"),
        "total_liabilities": _get_metric_value(result.leverage, "总负债"),
        "total_equity": _get_metric_value(result.leverage, "所有者权益"),
        "current_assets": result.summary.get("current_assets"),
        "current_liabilities": result.summary.get("current_liabilities"),
        "accounts_receivable": _get_metric_value(result.operation, "应收账款"),
        "accounts_payable": _get_metric_value(result.operation, "应付账款"),
        "inventory": _get_metric_value(result.operation, "存货"),
        "cash_equivalents": _get_metric_value(result.operation, "货币资金"),
        "trading_financial_assets": _get_metric_value(result.operation, "交易性金融资产"),
        "notes_receivable": _get_metric_value(result.operation, "应收票据"),
        "short_term_borrowing": _get_metric_value(result.leverage, "短期借款"),
        "notes_payable": _get_metric_value(result.leverage, "应付票据"),
        "long_term_borrowing": _get_metric_value(result.leverage, "长期借款"),
        "bonds_payable": _get_metric_value(result.leverage, "应付债券"),
        # ── 利润表 ──
        "operating_revenue": _merge(_get_metric_value(result.profitability, "营业收入"), text_extracted.get("operating_revenue")),
        "operating_cost": _get_metric_value(result.profitability, "营业成本"),
        "total_profit": _get_metric_value(result.profitability, "利润总额"),
        "net_profit": _merge(_get_metric_value(result.profitability, "净利润"), text_extracted.get("net_profit")),
        "gross_margin": _merge(_get_metric_value(result.profitability, "毛利率"), text_extracted.get("gross_margin")),
        # ── 现金流量表 ──
        "operating_cash_flow": _get_metric_value(result.operation, "经营性净现金流"),
        "investing_cash_flow": _get_metric_value(result.operation, "投资性净现金流"),
        "financing_cash_flow": _get_metric_value(result.operation, "融资性净现金流"),
        # ── 比率（从 compute_financial_metrics 已计算）──
        "current_ratio": _merge(_get_metric_value(result.liquidity, "流动比率"), text_extracted.get("current_ratio")),
        "debt_to_asset_ratio": _merge(_get_metric_value(result.leverage, "资产负债率"), text_extracted.get("debt_to_asset_ratio")),
        "revenue_cagr": _merge(_get_metric_value(result.growth, "CAGR"), text_extracted.get("revenue_cagr")),
        "rd_expense_ratio": text_extracted.get("rd_expense_ratio"),
        "enterprise_name": _extract_enterprise_name_from_markdown(markdown_content),
        # ── 报表类型 ──
        "is_consolidated": is_consolidated,
        "report_type": result.summary.get("report_type", "unknown"),
    }


# ============================================================================
# 新增：营业执照信息提取
# ============================================================================

def _extract_enterprise_name_from_markdown(markdown: str) -> str | None:
    """从 markdown 文本中尝试提取企业名称（财报/银行流水等文件可能含企业名）"""
    patterns = [
        r'(?:公司名称|企业名称|单位名称|编制单位|纳税人名称)[：:\s　]*([^\n]{2,40})',
        r'报表名称[：:\s　]*([^\n]{2,40})',
    ]
    for pat in patterns:
        m = re.search(pat, markdown)
        if m:
            name = m.group(1).strip()
            if len(name) >= 4:
                return name
    return None


def extract_business_license(text: str) -> dict[str, str]:
    """
    从营业执照文本提取基本信息
    返回: {field_name: value, ...}
    """
    patterns: dict[str, list[str]] = {
        "company_name": [
            r"(?:公司|企业)名称[：:\s　]*(\S{2,30}?(?:公司|企业|集团|厂|社|行|中心))",
            r"(?:公司|企业)名称[：:\s　]*([^\n]{2,30})",
        ],
        "unified_social_credit_code": [
            r"统一社会信用代码[：:\s　]*([A-Z0-9]{18})",
            r"信用代码[：:\s　]*([A-Z0-9]{18})",
        ],
        "legal_representative": [
            r"法定代表人[：:\s　]*([^\n]{2,10})",
            r"法人代表[：:\s　]*([^\n]{2,10})",
        ],
        "registered_capital": [
            r"注册资本[：:\s　]*([\d，,，.。·\s]+(?:万|亿)?[元]?)",
        ],
        "registration_date": [
            r"注册日期[：:\s　]*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)",
            r"成立日期[：:\s　]*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)",
            r"开业日期[：:\s　]*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)",
        ],
        "business_scope": [
            r"经营范围[：:\s　]*([^\n]{10,200})",
        ],
        "registration_authority": [
            r"登记机关[：:\s　]*([^\n]{4,30})",
        ],
        "enterprise_type": [
            r"企业类型[：:\s　]*([^\n]{4,30})",
            r"公司类型[：:\s　]*([^\n]{4,30})",
        ],
    }

    result: dict[str, str] = {}
    for field, pat_list in patterns.items():
        for pat in pat_list:
            m = re.search(pat, text)
            if m:
                result[field] = m.group(1).strip()
                break

    # ── 表格回退：在 Markdown 表格中搜索 ──────────────────────
    if "company_name" not in result:
        tables = _extract_tables_from_markdown(text)
        for header, rows in tables.items():
            for row in rows:
                row_text = " ".join(row)
                if any(kw in row_text for kw in ["公司名称", "企业名称", "名称"]):
                    for cell in row:
                        cell_clean = cell.strip()
                        if any(kw in cell_clean for kw in ["公司", "企业", "集团", "有限", "股份"]) and len(cell_clean) >= 4:
                            result["company_name"] = cell_clean[:60]
                            break
                if "company_name" in result:
                    break
            if "company_name" in result:
                break

    _safe_print(f"[extract_business_license] Extracted: {list(result.keys())}")
    return result


# ============================================================================
# 新增：公司章程提取（股东结构、实际控制人）
# ============================================================================

def extract_from_articles_of_association(text: str) -> dict[str, str]:
    """
    从公司章程提取股东结构、实际控制人等信息
    返回: {field_name: value, ...}
    """
    result: dict[str, str] = {}

    # 股东结构
    shareholder_patterns: list[str] = [
        r"股东[：:]\s*([^\n]{10,200})",
        r"股权结构[：:]\s*([^\n]{10,200})",
        r"股东持股[比例结构]+[：:]\s*([^\n]{10,300})",
    ]
    for pat in shareholder_patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            result["shareholder_structure_raw"] = m.group(1).strip()
            # 进一步解析：股东名(持股比例) 格式
            shares: list[str] = []
            share_items = re.findall(r"([^，,；;。\n]{2,30}?)\s*[（(]\s*(\d+(?:\.\d+)?)\s*%\s*[）)]", m.group(1))
            if share_items:
                shares = [f"{name}({pct}%)" for name, pct in share_items]
            elif share_items := re.findall(r"(\S+)\s+持股\s+(\d+(?:\.\d+)?)\s*%", m.group(1)):
                shares = [f"{name}({pct}%)" for name, pct in share_items]
            if shares:
                result["shareholder_structure"] = "，".join(shares[:10])  # 最多10个股东
            break

    # 实际控制人
    controller_patterns: list[str] = [
        r"实际控制人[：:]\s*([^\n，,;；]{2,30})",
        r"控制人[：:]\s*([^\n，,;；]{2,30})",
        r"控股股东[：:]\s*([^\n，,;；]{2,30})",
    ]
    for pat in controller_patterns:
        m = re.search(pat, text)
        if m:
            result["actual_controller"] = m.group(1).strip()
            break

    # 股权穿透说明
    if "shareholder_structure" not in result:
        # 尝试从文本中找到股东列表
        share_lines: list[str] = []
        for line in text.split("\n"):
            if any(kw in line for kw in ["股东", "持股", "股权"]) and len(line) < 200:
                share_lines.append(line.strip())
        if share_lines:
            result["shareholder_structure_raw"] = "\n".join(share_lines[:5])

    _safe_print(f"[extract_from_articles_of_association] Extracted: {list(result.keys())}")
    return result


# ============================================================================
# 新增：担保合同信息提取
# ============================================================================

def extract_guarantee_info(text: str) -> dict[str, str]:
    """
    从担保合同文本提取担保详情
    返回: {field_name: value, ...}
    """
    result: dict[str, str] = {}

    # 法人保证担保
    legal_guarantee_patterns: list[str] = [
        r"法人保证担保[：:]\s*([^\n]{10,200})",
        r"法人担保[：:]\s*([^\n]{10,200})",
        r"保证人[：:]\s*([^\n]{10,200})",
    ]
    for pat in legal_guarantee_patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            result["legal_guarantee"] = m.group(1).strip()
            break

    # 自然人保证担保
    natural_guarantee_patterns: list[str] = [
        r"自然人保证担保[：:]\s*([^\n]{10,200})",
        r"自然人担保[：:]\s*([^\n]{10,200})",
        r"个人担保[：:]\s*([^\n]{10,200})",
    ]
    for pat in natural_guarantee_patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            result["natural_person_guarantee"] = m.group(1).strip()
            break

    # 抵押质押担保
    collateral_patterns: list[str] = [
        r"抵押担保[：:]\s*([^\n]{10,200})",
        r"质押担保[：:]\s*([^\n]{10,200})",
        r"抵押物[：:]\s*([^\n]{10,200})",
        r"抵押物详情[：:]\s*([^\n]{10,200})",
    ]
    for pat in collateral_patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            result["collateral_pledge"] = m.group(1).strip()
            break

    # 担保金额
    guarantee_amount_patterns: list[str] = [
        r"担保金额[：:]\s*([\d，,，.。·\s]+(?:万|亿)?[元]?)",
        r"担保总额[：:]\s*([\d，,，.。·\s]+(?:万|亿)?[元]?)",
    ]
    for pat in guarantee_amount_patterns:
        m = re.search(pat, text)
        if m:
            result["guarantee_amount"] = m.group(1).strip()
            break

    _safe_print(f"[extract_guarantee_info] Extracted: {list(result.keys())}")
    return result


# ============================================================================
# 新增：从 Markdown 格式财务报表提取结构化数据
# ============================================================================

def extract_from_financial_tables(markdown_text: str) -> dict[str, Any]:
    """
    从 Markdown 格式财务报表提取结构化数据
    支持标准 Markdown 表格格式

    返回：
    {
        "balance_sheet": {row_name: value, ...},
        "income_statement": {row_name: value, ...},
        "cash_flow": {row_name: value, ...},
    }
    """
    import io as _io
    tables: dict[str, list[list[str]]] = _extract_tables_from_markdown(markdown_text)

    result: dict[str, dict[str, float]] = {
        "balance_sheet": {},
        "income_statement": {},
        "cash_flow": {},
    }

    for header, rows in tables.items():
        header_lower = header.lower()
        target_dict: dict[str, dict[str, float]] | None = None

        if any(kw in header_lower for kw in ["资产负债", "财务状况", "balance"]):
            target_dict = result["balance_sheet"]
        elif any(kw in header_lower for kw in ["损益", "利润", "income", "profit"]):
            target_dict = result["income_statement"]
        elif any(kw in header_lower for kw in ["现金流", "cash flow"]):
            target_dict = result["cash_flow"]

        if target_dict is None:
            continue

        # 解析表格行：第一列为科目名，后续列为数值
        for row in rows[1:]:  # 跳过表头行
            if len(row) < 2:
                continue
            item_name = row[0].strip()
            if not item_name:
                continue
            # 取最后一个非空数值列
            for col_idx in range(1, len(row)):
                val_str = row[col_idx].strip()
                if val_str:
                    parsed = parse_number(val_str)
                    if parsed is not None:
                        target_dict[item_name] = parsed
                        break

    # 扁平化：把所有科目汇总
    flat: dict[str, float] = {}
    for section_data in result.values():
        flat.update(section_data)

    _safe_print(f"[extract_from_financial_tables] Extracted: {len(flat)} financial items")
    return {
        "balance_sheet": result["balance_sheet"],
        "income_statement": result["income_statement"],
        "cash_flow": result["cash_flow"],
        "flat": flat,
    }


# ============================================================================
# 新增：综合提取（整合所有新增提取器）
# ============================================================================

async def extract_enterprise_basic_info(markdown_content: str) -> dict[str, Any]:
    """
    综合提取企业基本信息（营业执照、公司章程等）
    返回扁平化字典
    """
    # 营业执照提取
    license_info = extract_business_license(markdown_content)

    # 公司章程提取
    association_info = extract_from_articles_of_association(markdown_content)

    # 担保信息提取
    guarantee_info = extract_guarantee_info(markdown_content)

    # 财务报表提取
    financial_tables = extract_from_financial_tables(markdown_content)

    # 合并结果
    merged: dict[str, Any] = {}
    merged.update(license_info)
    merged.update(association_info)
    merged.update(guarantee_info)
    merged.update(financial_tables.get("flat", {}))

    # 特殊处理：股东结构
    if "shareholder_structure" in association_info:
        merged["shareholder_structure"] = association_info["shareholder_structure"]
    elif "shareholder_structure_raw" in association_info:
        merged["shareholder_structure"] = association_info["shareholder_structure_raw"]

    # 特殊处理：实际控制人
    if "actual_controller" in association_info:
        merged["actual_controller"] = association_info["actual_controller"]

    # 特殊处理：法人保证担保
    if "legal_guarantee" in guarantee_info:
        merged["legal_guarantee"] = guarantee_info["legal_guarantee"]

    # 特殊处理：自然人保证担保
    if "natural_person_guarantee" in guarantee_info:
        merged["natural_person_guarantee"] = guarantee_info["natural_person_guarantee"]

    return merged


# ============================================================================
# 新增：收入交叉核验
# ============================================================================

async def run_income_verification(
    markdown_content: str,
    financial_data: dict[str, Any],
) -> dict[str, Any]:
    """
    收入交叉核验：财务报表营收 vs 银行流水 vs 纳税申报
    返回核验结论和偏差率

    数据源：
    - 报表营收：financial_data["operating_revenue"]
    - 银行流水：从 markdown 中提取银行流水的贷方发生额合计
    - 纳税申报：从 markdown 中提取纳税申报表营业收入
    """
    result: dict[str, Any] = {
        "report_revenue": financial_data.get("operating_revenue"),
        "bank_inflow": None,
        "tax_revenue": None,
        "bank_deviation_pct": None,
        "tax_deviation_pct": None,
        "bank_result": "未核验",
        "tax_result": "未核验",
        "conclusion": "",
    }

    report_rev = result["report_revenue"]

    # ── 1. 从银行流水提取贷方发生额 ──
    bank_keywords = ["银行流水", "银行对账单", "账户流水", "银行明细"]
    for kw in bank_keywords:
        if kw not in markdown_content:
            continue
        # 尝试多种匹配模式
        bank_patterns = [
            r'贷方发生额[合计总计]*[：:\s　]*([\d,，]+\.?\d*)\s*[万元]?',
            r'贷方[合计总计]*[：:\s　]*([\d,，]+\.?\d*)\s*[万元]?',
            r'收入[合计总计]*[：:\s　]*([\d,，]+\.?\d*)\s*[万元]?',
            r'本年累计[流入收入]*[：:\s　]*([\d,，]+\.?\d*)\s*[万元]?',
        ]
        for pat in bank_patterns:
            m = re.search(pat, markdown_content)
            if m:
                val = parse_number(m.group(1))
                if val and val > 0:
                    result["bank_inflow"] = val
                    break
        if result["bank_inflow"] is not None:
            break

    # ── 2. 从纳税申报表提取申报营收 ──
    tax_keywords = ["纳税申报", "税务申报", "企业所得税", "增值税申报"]
    for kw in tax_keywords:
        if kw not in markdown_content:
            continue
        tax_patterns = [
            r'营业收入[：:\s　]*([\d,，]+\.?\d*)\s*[万元]?',
            r'申报[营收销售额]*[：:\s　]*([\d,，]+\.?\d*)\s*[万元]?',
            r'计税[营收销售额]*[：:\s　]*([\d,，]+\.?\d*)\s*[万元]?',
        ]
        for pat in tax_patterns:
            m = re.search(pat, markdown_content)
            if m:
                val = parse_number(m.group(1))
                if val and val > 0:
                    result["tax_revenue"] = val
                    break
        if result["tax_revenue"] is not None:
            break

    # ── 3. 计算偏差率并给出结论 ──
    if report_rev and report_rev > 0:
        # 报表 vs 银行流水
        if result["bank_inflow"] is not None and result["bank_inflow"] > 0:
            bank_dev = abs(report_rev - result["bank_inflow"]) / report_rev * 100
            result["bank_deviation_pct"] = round(bank_dev, 2)
            if bank_dev <= 10:
                result["bank_result"] = "基本吻合"
            elif bank_dev <= 30:
                result["bank_result"] = "存在偏差"
            else:
                result["bank_result"] = "重大偏差，需关注"

        # 报表 vs 纳税申报
        if result["tax_revenue"] is not None and result["tax_revenue"] > 0:
            tax_dev = abs(report_rev - result["tax_revenue"]) / report_rev * 100
            result["tax_deviation_pct"] = round(tax_dev, 2)
            if tax_dev <= 5:
                result["tax_result"] = "基本一致"
            elif tax_dev <= 15:
                result["tax_result"] = "存在差异"
            else:
                result["tax_result"] = "重大差异，需关注"

    # ── 4. 综合结论 ──
    parts: list[str] = []
    has_bank = result["bank_inflow"] is not None
    has_tax = result["tax_revenue"] is not None

    if has_bank and has_tax:
        bank_ok = result["bank_result"] == "基本吻合"
        tax_ok = result["tax_result"] == "基本一致"
        if bank_ok and tax_ok:
            parts.append("收入真实性验证通过，财务报表营收与银行流水、纳税申报三方数据基本一致。")
        elif not bank_ok and not tax_ok:
            parts.append(f"收入数据存在较大偏差（银行流水偏差{result['bank_deviation_pct']}%、纳税申报偏差{result['tax_deviation_pct']}%），三方数据不一致，建议实地核实。")
        else:
            parts.append(f"收入数据部分核验通过：银行流水{result['bank_result']}（偏差{result['bank_deviation_pct']}%），纳税申报{result['tax_result']}（偏差{result['tax_deviation_pct']}%）。")
    elif has_bank:
        parts.append(f"报表营收与银行流水{result['bank_result']}（偏差{result['bank_deviation_pct']}%）。纳税申报未提供，无法比对。")
    elif has_tax:
        parts.append(f"报表营收与纳税申报{result['tax_result']}（偏差{result['tax_deviation_pct']}%）。银行流水未提供，无法比对。")
    else:
        parts.append("因缺少银行流水和纳税申报资料，无法进行收入交叉核验，建议补充相关资料后重新核验。")

    # 口径差异提示
    parts.append("注：银行流水的贷方发生额可能包含非经营性流入（如借款、投资回收），纳税申报营收与报表营收可能存在税法/会计口径差异，偏差率仅供参考。")

    result["conclusion"] = "".join(parts)

    _safe_print(f"[run_income_verification] report={report_rev}, bank={result['bank_inflow']}, tax={result['tax_revenue']}")
    _safe_print(f"[run_income_verification] {result['conclusion'][:80]}")

    return result


# ============================================================================
# 新增：按年度提取财务报表数据
# ============================================================================

def extract_annual_financial_data(markdown_content: str) -> dict[int, dict[str, float]]:
    """
    从 Phase1 markdown 中按年度提取资产负债表/利润表数据

    返回：{2023: {"total_assets": xxx, "total_liabilities": xxx, ...}, 2024: {...}}

    逻辑：
    1. pd.read_html() 解析表格
    2. 识别列头年份（仅取完整年度 12 个月，跳过"最新一期"/季度/月度列）
    3. 按科目行匹配各年数值
    """
    import io as _io

    annual_data: dict[int, dict[str, float]] = {}

    try:
        all_tables = pd.read_html(_io.StringIO(markdown_content))
    except Exception:
        return annual_data

    # ── 年份识别正则 ──────────────────────────────────────────
    year_pattern = re.compile(r'(20\d{2})')

    # ── 科目匹配映射 ──────────────────────────────────────────
    bs_mapping = {
        "total_assets": ["资产总计", "总资产", "资产合计"],
        "total_liabilities": ["负债总计", "总负债", "负债合计"],
        "total_equity": ["所有者权益", "股东权益", "净资产"],
        "current_assets": ["流动资产合计", "流动资产"],
        "current_liabilities": ["流动负债合计", "流动负债"],
        "inventory": ["存货", "存货净额"],
        "accounts_receivable": ["应收账款", "应收款项"],
        "accounts_payable": ["应付账款", "应付款项"],
        "short_term_borrowing": ["短期借款"],
        "notes_payable": ["应付票据"],
        "long_term_borrowing": ["长期借款"],
        "bonds_payable": ["应付债券"],
        "cash_equivalents": ["货币资金"],
        "trading_financial_assets": ["交易性金融资产"],
        "notes_receivable": ["应收票据"],
    }

    is_mapping = {
        "operating_revenue": ["营业收入", "营业总收入"],
        "operating_cost": ["营业成本", "营业总成本"],
        "total_profit": ["利润总额", "税前利润"],
        "net_profit": ["净利润", "净利率", "归属于.*净利润"],
    }

    for table in all_tables:
        df = table.copy()
        # 尝试将第一列设为索引
        if df.shape[1] < 2:
            continue
        first_col = df.iloc[:, 0].astype(str)
        combined = first_col.str.cat(sep=" ")

        # 判断表格类型
        is_bs = any(kw in combined for kw in ["资产总计", "总资产", "负债合计", "负债总计", "所有者权益"])
        is_is_ = any(kw in combined for kw in ["营业收入", "营业总收入", "利润总额", "净利润"])
        is_cf = any(kw in combined for kw in ["经营活动", "投资活动", "现金流量"])

        if not (is_bs or is_is_):
            continue

        mapping = bs_mapping if is_bs else is_mapping

        # 识别年份列
        year_cols: dict[int, int] = {}  # {year: column_index}
        header_row_idx = 0
        for row_idx in range(min(3, len(df))):
            for col_idx in range(1, df.shape[1]):
                cell_text = str(df.iloc[row_idx, col_idx])
                m = year_pattern.search(cell_text)
                if m:
                    year = int(m.group(1))
                    # 仅保留完整年度（2020-2026），排除异常值
                    if 2020 <= year <= 2026 and year not in year_cols:
                        year_cols[year] = col_idx
            if year_cols:
                break

        if not year_cols:
            continue

        # 提取各科目每年数值
        for row_idx in range(len(df)):
            label = str(df.iloc[row_idx, 0])
            for key, keywords in mapping.items():
                if any(kw in label for kw in keywords):
                    for year, col_idx in year_cols.items():
                        if col_idx < df.shape[1]:
                            val = parse_number(df.iloc[row_idx, col_idx])
                            if val is not None:
                                if year not in annual_data:
                                    annual_data[year] = {}
                                annual_data[year][key] = val
                    break

    # 只保留至少有 5 个科目的年份
    annual_data = {y: d for y, d in annual_data.items() if len(d) >= 5}

    _safe_print(f"[extract_annual_financial_data] Years: {sorted(annual_data.keys())}, keys per year: {[len(v) for v in annual_data.values()]}")
    return annual_data
