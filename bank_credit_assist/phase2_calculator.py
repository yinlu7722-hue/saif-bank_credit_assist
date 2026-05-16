"""
phase2_calculator.py
财务指标计算器（精准计算，不依赖AI估算）

在 Phase2 提取原始财务数据后，
用 Python 精准计算衍生指标（比例、增速、杜邦分析、年度指标等），
确保财务指标 100% 精准。
"""
from __future__ import annotations

from typing import Any

from shared.utils import safe_print as _safe_print


def _parse_number(value: Any) -> float | None:
    """安全解析数字，支持字符串和数值类型"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        import re
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


def compute_financial_ratios(raw_financials: dict[str, Any]) -> dict[str, Any]:
    """
    输入：Phase2 提取的原始财务数据
    输出：计算后的衍生指标字典

    新增计算：
      - 杜邦分析（ROE 拆解）
      - 11 项年度财务指标
      - 原有的盈利能力/偿债能力/杠杆/营运/成长指标
    """
    computed: dict[str, Any] = {}

    # ── 原始值解析 ────────────────────────────────────────────────
    revenue = _parse_number(raw_financials.get("operating_revenue"))
    cost = _parse_number(raw_financials.get("operating_cost"))
    net_profit = _parse_number(raw_financials.get("net_profit"))
    total_profit = _parse_number(raw_financials.get("total_profit"))

    current_assets = _parse_number(raw_financials.get("current_assets"))
    current_liabilities = _parse_number(raw_financials.get("current_liabilities"))
    inventory = _parse_number(raw_financials.get("inventory"))

    total_assets = _parse_number(raw_financials.get("total_assets"))
    total_liabilities = _parse_number(raw_financials.get("total_liabilities"))
    total_equity = _parse_number(raw_financials.get("total_equity"))

    accounts_receivable = _parse_number(raw_financials.get("accounts_receivable"))
    accounts_payable = _parse_number(raw_financials.get("accounts_payable"))

    short_term_borrowing = _parse_number(raw_financials.get("short_term_borrowing"))
    notes_payable = _parse_number(raw_financials.get("notes_payable"))
    long_term_borrowing = _parse_number(raw_financials.get("long_term_borrowing"))
    bonds_payable = _parse_number(raw_financials.get("bonds_payable"))

    cash_equivalents = _parse_number(raw_financials.get("cash_equivalents"))
    trading_financial_assets = _parse_number(raw_financials.get("trading_financial_assets"))
    notes_receivable = _parse_number(raw_financials.get("notes_receivable"))

    rd_expense = _parse_number(raw_financials.get("rd_expense"))
    average_assets = _parse_number(raw_financials.get("average_total_assets"))

    # ── 盈利能力指标 ──────────────────────────────────────────────
    if revenue is not None and cost is not None:
        computed["gross_profit"] = round(revenue - cost, 2)
        if revenue > 0:
            computed["gross_margin_calc"] = round((revenue - cost) / revenue * 100, 2)

    if net_profit is not None and revenue is not None and revenue > 0:
        computed["net_margin"] = round(net_profit / revenue * 100, 2)

    # 销售利润率 = 利润总额 / 营业收入
    if total_profit is not None and revenue is not None and revenue > 0:
        computed["sales_profit_margin"] = round(total_profit / revenue * 100, 2)

    # ── 偿债能力指标 ──────────────────────────────────────────────
    if current_assets is not None and current_liabilities is not None and current_liabilities > 0:
        computed["current_ratio_calc"] = round(current_assets / current_liabilities, 2)

    if current_assets is not None and current_liabilities is not None and current_liabilities > 0:
        if inventory is not None:
            computed["quick_ratio"] = round((current_assets - inventory) / current_liabilities, 2)

    # ── 杠杆水平指标 ──────────────────────────────────────────────
    if total_liabilities is not None and total_assets is not None and total_assets > 0:
        computed["debt_to_asset_ratio_calc"] = round(total_liabilities / total_assets * 100, 2)

    if total_liabilities is not None and total_equity is not None and total_equity > 0:
        computed["debt_to_equity_ratio"] = round(total_liabilities / total_equity * 100, 2)

    if total_assets is not None and total_equity is not None and total_equity > 0:
        computed["equity_multiplier"] = round(total_assets / total_equity, 2)

    # ── 营运能力指标 ──────────────────────────────────────────────
    if revenue is not None and average_assets is not None and average_assets > 0:
        computed["asset_turnover"] = round(revenue / average_assets, 2)
    elif revenue is not None and total_assets is not None and total_assets > 0:
        computed["asset_turnover"] = round(revenue / total_assets, 2)

    # 应收账款周转天数 = 360 / (营业收入 / 应收账款)
    if revenue is not None and accounts_receivable is not None and accounts_receivable > 0 and revenue > 0:
        computed["receivables_turnover_days"] = round(360 / (revenue / accounts_receivable), 1)

    # 应付账款周转天数 = 360 / (营业成本 / 应付账款)
    if cost is not None and accounts_payable is not None and accounts_payable > 0 and cost > 0:
        computed["payables_turnover_days"] = round(360 / (cost / accounts_payable), 1)

    # 存货周转天数 = 360 / (营业成本 / 存货)
    if cost is not None and inventory is not None and inventory > 0 and cost > 0:
        computed["inventory_turnover_days"] = round(360 / (cost / inventory), 1)

    # ── 杜邦分析 ──────────────────────────────────────────────────
    # ROE = 净利率 × 资产周转率 × 权益乘数
    dupont_parts: dict[str, float | None] = {
        "net_margin_pct": computed.get("net_margin"),
        "asset_turnover": computed.get("asset_turnover"),
        "equity_multiplier": computed.get("equity_multiplier"),
    }
    if all(v is not None for v in dupont_parts.values()):
        roe = (dupont_parts["net_margin_pct"] / 100) * dupont_parts["asset_turnover"] * dupont_parts["equity_multiplier"] * 100
        dupont_parts["roe_pct"] = round(roe, 2)
    else:
        dupont_parts["roe_pct"] = None
    computed["dupont_analysis"] = dupont_parts

    # ── 刚性负债 ──────────────────────────────────────────────────
    rigid_liability_items: list[float] = []
    for item in [short_term_borrowing, notes_payable, long_term_borrowing, bonds_payable]:
        if item is not None:
            rigid_liability_items.append(item)
    if rigid_liability_items:
        computed["rigid_liabilities"] = round(sum(rigid_liability_items), 2)

    # ── 现金类资产 ────────────────────────────────────────────────
    cash_items: list[float] = []
    for item in [cash_equivalents, trading_financial_assets, notes_receivable]:
        if item is not None:
            cash_items.append(item)
    if cash_items:
        computed["cash_assets"] = round(sum(cash_items), 2)

    # ── 刚性负债净敞口 ────────────────────────────────────────────
    rigid = computed.get("rigid_liabilities")
    cash = computed.get("cash_assets")
    if rigid is not None and cash is not None:
        computed["rigid_liability_net"] = round(rigid - cash, 2)

    # ── 成长能力指标 ──────────────────────────────────────────────
    profit_history = raw_financials.get("net_profit_history", [])
    if isinstance(profit_history, list) and len(profit_history) >= 2:
        profits = [_parse_number(p) for p in profit_history if _parse_number(p) is not None]
        if len(profits) >= 2 and profits[-1] > 0:
            n = len(profits) - 1
            cagr = (profits[0] / profits[-1]) ** (1 / n) - 1
            computed["net_profit_cagr"] = round(cagr * 100, 2)

    # ── 研发相关指标 ──────────────────────────────────────────────
    if rd_expense is not None:
        computed["rd_expense_amount"] = round(rd_expense, 2)
    elif revenue is not None and raw_financials.get("rd_expense_ratio") is not None:
        rd_ratio = _parse_number(raw_financials.get("rd_expense_ratio"))
        if rd_ratio is not None and revenue > 0:
            computed["rd_expense_amount"] = round(revenue * rd_ratio / 100, 2)

    _safe_print(f"[phase2_calculator] Computed ratios: {list(computed.keys())}")
    return computed


def merge_extracted_and_computed(
    extracted: dict[str, Any],
    computed: dict[str, Any],
) -> dict[str, Any]:
    """
    合并 phase2 提取值和 phase2_calculator 计算值
    优先使用 phase2 已有指标，computed 作为补充
    """
    merged = dict(extracted)

    # 校验性计算：computed 值与 extracted 值对比
    check_fields = {
        "gross_margin": "gross_margin_calc",
        "current_ratio": "current_ratio_calc",
        "debt_to_asset_ratio": "debt_to_asset_ratio_calc",
    }

    for extracted_key, computed_key in check_fields.items():
        if computed_key in computed and computed[computed_key] is not None:
            if extracted_key in extracted and extracted[extracted_key] is not None:
                diff = abs(extracted[extracted_key] - computed[computed_key])
                if diff > 5:
                    _safe_print(
                        f"[WARN] {extracted_key}: phase2={extracted[extracted_key]}, "
                        f"calculator={computed[computed_key]}, diff={diff:.2f}"
                    )
            else:
                merged[extracted_key] = computed[computed_key]

    # 合并新增的计算指标
    for key, value in computed.items():
        if key not in merged or merged[key] is None:
            if value is not None:
                merged[key] = value

    return merged


def compute_annual_indicators_per_year(
    annual_data: dict[int, dict[str, float]],
) -> dict[int, dict[str, float | None]]:
    """
    为每个年度分别计算 11 项财务指标

    输入：{year: {科目: 数值}}
    输出：{year: {指标: 数值}}

    11 项指标：
      资产负债率、流动比率、速动比率、应收账款周转天数、
      应付账款周转天数、存货周转天数、销售利润率、毛利率、
      刚性负债、现金类资产、刚性负债净敞口
    """
    result: dict[int, dict[str, float | None]] = {}

    for year, data in sorted(annual_data.items()):
        ta = data.get("total_assets")
        tl = data.get("total_liabilities")
        te = data.get("total_equity")
        ca = data.get("current_assets")
        cl = data.get("current_liabilities")
        inv = data.get("inventory")
        ar = data.get("accounts_receivable")
        ap = data.get("accounts_payable")
        rev = data.get("operating_revenue")
        cost = data.get("operating_cost")
        tp = data.get("total_profit")
        stb = data.get("short_term_borrowing")
        np_ = data.get("notes_payable")
        ltb = data.get("long_term_borrowing")
        bp = data.get("bonds_payable")
        cash = data.get("cash_equivalents")
        tfa = data.get("trading_financial_assets")
        nr = data.get("notes_receivable")

        indicators: dict[str, float | None] = {}

        # 资产负债率
        if ta and tl and ta > 0:
            indicators["debt_to_asset_ratio"] = round(tl / ta * 100, 2)
        # 流动比率
        if ca and cl and cl > 0:
            indicators["current_ratio"] = round(ca / cl, 2)
        # 速动比率
        if ca and cl and cl > 0:
            indicators["quick_ratio"] = round((ca - (inv or 0)) / cl, 2)
        # 应收账款周转天数
        if rev and ar and ar > 0 and rev > 0:
            indicators["receivables_turnover_days"] = round(360 / (rev / ar), 1)
        # 应付账款周转天数
        if cost and ap and ap > 0 and cost > 0:
            indicators["payables_turnover_days"] = round(360 / (cost / ap), 1)
        # 存货周转天数
        if cost and inv and inv > 0 and cost > 0:
            indicators["inventory_turnover_days"] = round(360 / (cost / inv), 1)
        # 销售利润率
        if tp and rev and rev > 0:
            indicators["sales_profit_margin"] = round(tp / rev * 100, 2)
        # 毛利率
        if rev and cost and rev > 0:
            indicators["gross_margin"] = round((rev - cost) / rev * 100, 2)
        # 刚性负债
        rigid_items = [v for v in [stb, np_, ltb, bp] if v is not None]
        if rigid_items:
            indicators["rigid_liabilities"] = round(sum(rigid_items), 2)
        # 现金类资产
        cash_items = [v for v in [cash, tfa, nr] if v is not None]
        if cash_items:
            indicators["cash_assets"] = round(sum(cash_items), 2)
        # 刚性负债净敞口
        rigid = indicators.get("rigid_liabilities")
        cash_val = indicators.get("cash_assets")
        if rigid is not None and cash_val is not None:
            indicators["rigid_liability_net"] = round(rigid - cash_val, 2)

        result[year] = indicators

    return result
