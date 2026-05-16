"""
test_committee.py
贷审会全流程测试 — 使用模拟数据运行完整5轮辩论
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from phase4_committee import CommitteeOrchestrator
from shared.utils import safe_print as _safe_print


# 模拟 Phase2/Phase3 数据（模拟一家制造业中小企业）
MOCK_SESSION_DATA = {
    "phase2_result": {
        "financial": {
            "enterprise_name": "深圳华创精密制造有限公司",
            "total_assets": 285000000,
            "total_liabilities": 128000000,
            "total_equity": 157000000,
            "current_assets": 165000000,
            "current_liabilities": 95000000,
            "operating_revenue": 320000000,
            "operating_cost": 240000000,
            "net_profit": 28500000,
            "total_profit": 38000000,
            "gross_margin": 0.25,
            "current_ratio": 1.74,
            "quick_ratio": 1.15,
            "debt_to_asset_ratio": 0.449,
            "receivables_turnover_days": 85,
            "inventory_turnover_days": 62,
            "rigid_liabilities": 85000000,
            "cash_assets": 42000000,
            "rigid_liability_net": 43000000,
            "asset_turnover": 1.12,
            "equity_multiplier": 1.82,
            "net_margin": 0.089,
            "sales_profit_margin": 0.119,
            "revenue_cagr": 0.18,
            "net_profit_cagr": 0.22,
            "roe": 0.181,
            "dupont_analysis": {
                "roe_pct": 18.1,
                "net_margin_pct": 8.9,
                "asset_turnover": 1.12,
                "equity_multiplier": 1.82
            },
            "rd_expense_ratio": 0.048,
            "operating_cash_flow": 32000000,
            "investing_cash_flow": -45000000,
            "operating_revenue_2023": 271000000,
            "operating_revenue_2022": 230000000,
            "net_profit_2023": 23400000,
            "net_profit_2022": 19200000,
        },
        "basic_info": {
            "company_name": "深圳华创精密制造有限公司",
            "unified_social_credit_code": "91440300MA5DXXXXX",
            "legal_representative": "陈志强",
            "registered_capital": "5000万元",
            "registration_date": "2015年3月18日",
            "business_scope": "精密机械零部件研发、制造与销售；自动化设备研发；货物及技术进出口",
            "shareholder_structure": "陈志强持股42%，深圳华创控股有限公司持股30%，员工持股平台持股18%，外部投资机构持股10%",
            "actual_controller": "陈志强（通过直接持股及华创控股间接控制，合计控制72%表决权）",
        },
        "tech": {
            "rd_expense_ratio": {"metric": "研发费用占营收比", "value": 4.8, "unit": "%", "source_file": "06B1财务报表.pdf", "confidence_score": 0.85},
            "high_tech_cert": {"metric": "高新技术企业认证", "value": "已取得（GR2023440XXXXX，有效期至2026年）", "source_file": "01 营业执照.pdf"},
            "patent_count": 23,
            "team_size": 380,
        },
        "income_verification": {
            "report_revenue": 320000000,
            "bank_inflow": 305000000,
            "tax_revenue": 315000000,
            "bank_deviation_pct": "4.7%",
            "tax_deviation_pct": "1.6%",
            "bank_result": "基本吻合",
            "tax_result": "吻合",
            "conclusion": "收入核验整体一致，银行流水偏差在可接受范围内",
        },
        "annual_data": {
            2024: {"total_assets": 285000000, "operating_revenue": 320000000, "net_profit": 28500000, "total_liabilities": 128000000},
            2023: {"total_assets": 248000000, "operating_revenue": 271000000, "net_profit": 23400000, "total_liabilities": 115000000},
            2022: {"total_assets": 210000000, "operating_revenue": 230000000, "net_profit": 19200000, "total_liabilities": 102000000},
        },
        "annual_indicators": {
            2024: {"debt_to_asset_ratio": 0.449, "current_ratio": 1.74, "roe": 0.181},
            2023: {"debt_to_asset_ratio": 0.464, "current_ratio": 1.62, "roe": 0.168},
            2022: {"debt_to_asset_ratio": 0.486, "current_ratio": 1.55, "roe": 0.152},
        },
    },
    "inference_text": {
        "business_model": "企业采用生产型+研发型商业模式，以精密机械零部件为核心产品，覆盖从研发设计到生产制造的全流程。产品主要面向汽车零部件和3C电子行业客户，具有较高的客户粘性和技术壁垒。",
        "core_technology": "企业自主研发的高精度CNC加工技术和自动化检测系统构成核心技术壁垒。拥有23项专利（其中发明专利5项），研发费用占比4.8%，高于行业平均水平。已取得高新技术企业认证。",
        "operation_analysis": "企业拥有380名员工，其中研发技术人员占比约22%。生产基地位于深圳，占地约8000平方米。产能利用率维持在85%左右，近两年因订单增长进行了一轮扩产。",
        "industry_position": "企业处于国内精密制造行业中上游水平，在汽车零部件精密加工细分领域具有一定竞争优势。但与行业内头部企业相比，在规模和品牌影响力上仍有差距。",
        "competitive_advantages": "1）技术壁垒：高精度加工和自动化检测能力；2）客户粘性：与多家知名汽车零部件厂商保持长期合作；3）认证资质：高新技术企业、ISO9001/TS16949认证。",
        "competitive_disadvantages": "1）规模较小，议价能力有限；2）客户集中度偏高，前三大客户占营收约55%；3）技术迭代快，需持续研发投入。",
        "industry_trend": "精密制造行业受益于新能源汽车和智能制造趋势，未来5年预计保持12-15%的年均增速。但行业竞争加剧，低端产能过剩，高端产能仍依赖进口替代。",
        "overall_credit_status": "企业征信记录良好，近三年无不良贷款、无欠息、无垫款记录。在合作银行中保持良好声誉。",
        "bank_financing": "目前在3家银行有授信，总授信额度1.2亿元，已使用约7000万元。短期借款5500万元，长期借款3000万元。",
        "risk_evaluation": "企业整体经营稳健，财务指标健康。主要风险点：1）客户集中度偏高带来的收入波动风险；2）扩产投资带来的现金流压力；3）行业技术迭代可能导致现有设备贬值。风险等级：中。",
        "risk_level": "中",
        "risk_mitigation_measures": "1）要求企业提供前三大客户的年度采购合同作为增信；2）设定资产负债率上限65%的财务约束条款；3）追加实际控制人个人连带责任保证。",
        "credit_usage": "本次授信主要用于补充流动资金（约60%）和扩产设备采购（约40%），与企业发展阶段相匹配。",
        "recommended_credit_amount": "3000万元",
        "recommended_term": "12个月",
        "recommended_guarantee": "厂房抵押+实际控制人个人连带责任保证",
        "investigation_conclusion": "企业基本面良好，财务指标稳健，行业前景正面。建议在落实担保措施的前提下予以授信支持。",
        "return_analysis": "按LPR+100BP测算，本笔授信年化收益约4.85%，综合存款和国际结算等派生业务，综合回报率约6.2%。",
    },
}


async def main():
    _safe_print("=" * 70)
    _safe_print("  贷审会全流程测试")
    _safe_print("=" * 70)
    _safe_print(f"\n审议企业：{MOCK_SESSION_DATA['phase2_result']['basic_info']['company_name']}")
    _safe_print(f"五位评委即将开始5轮辩论...\n")

    # 进度回调
    def on_progress(log_entry: dict):
        entry = log_entry
        speaker = entry.get("speaker_name", "未知")
        round_num = entry.get("round", "?")
        pos = entry.get("position", {}).get("conclusion", "—")
        content_preview = entry.get("content", "")[:80].replace("\n", " ")
        _safe_print(f"  [R{round_num}] {speaker} → {pos} | {content_preview}...")

    # 运行贷审会
    orchestrator = CommitteeOrchestrator()
    result = await orchestrator.run(MOCK_SESSION_DATA, on_progress)

    # 输出结果
    _safe_print("\n" + "=" * 70)
    _safe_print("  终审结论")
    _safe_print("=" * 70)

    fc = result.final_conclusion
    _safe_print(f"\n结论：{fc.get('final_conclusion', '未明确')}")

    reasons = fc.get("core_reasons", [])
    if reasons:
        _safe_print("\n核心理由：")
        for i, r in enumerate(reasons, 1):
            _safe_print(f"  {i}. {r}")

    warnings = fc.get("risk_warnings", [])
    if warnings:
        _safe_print("\n风险提示：")
        for w in warnings:
            _safe_print(f"  ⚠ {w}")

    rc = fc.get("recommended_credit", {})
    if rc:
        _safe_print(f"\n建议授信方案：")
        _safe_print(f"  金额：{rc.get('amount', '—')}")
        _safe_print(f"  期限：{rc.get('term', '—')}")
        _safe_print(f"  利率：{rc.get('interest_rate', '—')}")
        _safe_print(f"  担保：{rc.get('guarantee', '—')}")

    _safe_print("\n" + "-" * 70)
    _safe_print("  评委立场变化")
    _safe_print("-" * 70)
    for agent_id, shift in result.position_shifts.items():
        changed = " ← 变化" if shift["shift"] != "未变化" else ""
        _safe_print(f"  {shift['agent_name']}: {shift['initial']} → {shift['final']}{changed}")

    _safe_print(f"\n辩论记录共 {len(result.debate_log)} 条发言")
    _safe_print(f"立场变化: {sum(1 for s in result.position_shifts.values() if s['shift'] != '未变化')}/{len(result.position_shifts)} 位")

    # 保存完整结果
    output_path = Path(__file__).parent / "output" / "committee_test_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    save_data = {
        "briefing": result.briefing,
        "initial_positions": {k: v for k, v in result.initial_positions.items()},
        "debate_log": result.debate_log,
        "final_positions": {k: v for k, v in result.final_positions.items()},
        "final_conclusion": fc,
        "position_shifts": {k: v for k, v in result.position_shifts.items()},
    }
    output_path.write_text(json.dumps(save_data, ensure_ascii=False, indent=2), encoding="utf-8")
    _safe_print(f"\n完整结果已保存至: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
