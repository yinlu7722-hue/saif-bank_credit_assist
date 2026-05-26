"""
test_committee.py - 独立测试模拟贷审会（Phase 4）
不依赖 Phase 1-3，使用 mock 数据直接调用 run_committee()
"""
import asyncio
import json
import sys
import time
from pathlib import Path

from phase4_committee import run_committee


def build_mock_session() -> dict:
    enterprise_name = "深圳华创精密制造有限公司"

    phase2_result = {
        "financial": {
            "enterprise_name": enterprise_name,
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
            "sales_profit_margin": 0.119,
            "revenue_cagr": 0.18,
            "net_profit_cagr": 0.22,
            "roe": 0.181,
        },
        "basic_info": {
            "company_name": enterprise_name,
            "unified_social_credit_code": "91440300MA5DXXXXX",
            "legal_representative": "陈志强",
            "registered_capital": "5000万元",
            "registration_date": "2015年3月18日",
            "business_scope": "精密机械零部件研发、制造与销售；自动化设备研发；货物及技术进出口",
            "shareholder_structure": "陈志强持股42%，深圳华创控股有限公司持股30%，员工持股平台持股18%",
            "actual_controller": "陈志强（通过直接持股及华创控股间接控制，合计控制72%表决权）",
        },
        "tech": {
            "rd_expense_ratio": {"value": 4.8},
            "high_tech_cert": {"value": "GR2023440XXXXX", "valid": True},
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
    }

    inference_text = {
        "business_model": "生产型+研发型商业模式，精密机械零部件为核心产品，从研发设计到生产制造全流程覆盖。",
        "core_technology": "高精度CNC加工技术和自动化检测系统构成核心技术壁垒。23项专利，研发费用占比4.8%。",
        "operation_analysis": "380名员工，研发技术人员占比约22%。深圳生产基地约8000平方米，产能利用率约85%。",
        "industry_position": "国内精密制造行业中上游，汽车零部件精密加工细分领域有竞争优势。",
        "competitive_advantages": "技术壁垒（高精度加工）、客户粘性（长期合作）、认证资质（高新/ISO/TS16949）。",
        "competitive_disadvantages": "规模较小议价有限、客户集中度偏高（前三大客户占55%）、需持续研发投入。",
        "industry_trend": "受益于新能源汽车和智能制造，未来5年预计12-15%年均增速，但行业竞争加剧。",
        "overall_credit_status": "征信记录良好，近三年无不良贷款、无欠息、无垫款记录。",
        "bank_financing": "3家银行有授信，总额度1.2亿元，已使用约7000万元。",
        "risk_evaluation": "企业经营稳健，财务健康。主要风险：客户集中度偏高、扩产现金流压力、技术迭代风险。",
        "risk_level": "中",
        "risk_mitigation_measures": "提供前三大客户采购合同，资产负债率上限65%约束，追加实控人个人连带保证。",
        "credit_usage": "补充流动资金（约60%）和扩产设备采购（约40%）。",
        "recommended_credit_amount": "3000万元",
        "recommended_term": "12个月",
        "recommended_guarantee": "厂房抵押+实际控制人个人连带责任保证",
    }

    return {"phase2_result": phase2_result, "inference_text": inference_text}


async def main():
    session_data = build_mock_session()

    print("=" * 60)
    print("诊断：session_data 结构检查")
    p2r = session_data.get("phase2_result")
    it = session_data.get("inference_text")
    print(f"  phase2_result is None: {p2r is None}")
    print(f"  inference_text type: {type(it).__name__}")
    print(f"  inference_text keys: {len(it) if isinstance(it, dict) else 'N/A'}")
    if isinstance(p2r, dict):
        for k in ["financial", "basic_info", "tech", "income_verification"]:
            v = p2r.get(k)
            print(f"  {k} type: {type(v).__name__}")

    print()
    print("=" * 60)
    print("开始执行模拟贷审会...")
    print()
    t0 = time.time()

    speeches = []

    def on_progress(entry):
        speeches.append(entry)
        speaker = entry.get("speaker_name", "?")
        r = entry.get("round", "?")
        pos = entry.get("position", {}).get("conclusion", "?")
        content = entry.get("content", "")
        print(f"  [R{r}] {speaker} -> {pos} ({len(content)}字)")

    try:
        result = await run_committee(session_data, on_progress)
    except Exception as e:
        print(f"\n!!! 执行失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

    elapsed = time.time() - t0
    print()
    print("=" * 60)
    print(f"贷审会完成！耗时 {elapsed:.0f}s")
    print(f"总发言数: {len(result.debate_log)} 条")
    fc = result.final_conclusion
    print(f"终审结论: {fc.get('final_conclusion', 'N/A')}")

    shifts = sum(1 for s in result.position_shifts.values() if s.get("shift") != "未变化")
    print(f"立场变化: {shifts}/{len(result.position_shifts)} 位评委")

    reasons = fc.get("core_reasons", [])
    if reasons:
        print("\n核心理由:")
        for r in reasons:
            print(f"  - {r}")

    warnings = fc.get("risk_warnings", [])
    if warnings:
        print("\n风险提示:")
        for w in warnings:
            print(f"  [WARN] {w}")

    print("\nPASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
