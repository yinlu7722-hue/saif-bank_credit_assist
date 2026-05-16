"""
test_e2e.py
端到端测试脚本 —— 仅使用 5 个必填文件测试完整流程
Phase1 → Phase2 → Phase3
"""
import asyncio
import json
import shutil
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from phase1_parser import phase1_parse_documents
from phase2_analysis import run_financial_analysis, extract_tech_innovation_metrics
from phase2_analysis import extract_enterprise_basic_info
from phase2_calculator import compute_financial_ratios, merge_extracted_and_computed
from phase2_compliance import ComplianceScreener
from phase2_inference import run_inference
from shared.utils import safe_print as _safe_print

# 测试文件目录
TEST_DIR = Path(r"C:\Users\Lawrence\Desktop\MBA\AI课\对公信贷流程智能化任务\testfile-gemini")
# 临时拷贝目录（只取必填文件）
TEMP_PARSE_DIR = Path(__file__).parent / "temp" / "e2e_test"


async def main():
    _safe_print("\n" + "=" * 70)
    _safe_print("  端到端测试: Phase1 → Phase2 → Phase3")
    _safe_print("=" * 70)

    # 准备测试文件（只取必填项 A1, A2, B1, B2, B3）
    TEMP_PARSE_DIR.mkdir(parents=True, exist_ok=True)
    required_map = {
        "01 营业执照.pdf": "A1",
        "02A2法人身份证.pdf": "A2",
        "06B1财务报表.pdf": "B1",
        "08B3银行流水.pdf": "B2",
        "09B4纳税申报表.pdf": "B3",
    }

    files_copied = 0
    for fname, code in required_map.items():
        src = TEST_DIR / fname
        if src.exists():
            dst = TEMP_PARSE_DIR / fname
            if not dst.exists():
                shutil.copy2(src, dst)
            files_copied += 1
            _safe_print(f"  [{code}] {fname} ({src.stat().st_size / 1024:.0f} KB)")
        else:
            _safe_print(f"  [MISSING] {fname}")

    if files_copied < 3:
        _safe_print(f"\nERROR: Only {files_copied}/5 required files available. Aborting.")
        return

    # ================================================================
    # PHASE 1: 文档解析
    # ================================================================
    _safe_print("\n" + "-" * 50)
    _safe_print("  PHASE 1: 文档解析")
    _safe_print("-" * 50)

    try:
        result = await phase1_parse_documents(TEMP_PARSE_DIR)
    except Exception as e:
        _safe_print(f"\n[PHASE 1 FAILED] {e}")
        return

    n_success = len(result["contents"])
    n_failed = len(result["failed_files"])
    _safe_print(f"\n  Parsed: {n_success} success, {n_failed} failed")

    if n_success == 0:
        _safe_print("[ABORT] No files parsed successfully")
        return

    # 合并 Markdown
    combined = []
    for fname, content in result["contents"].items():
        combined.append(f"\n\n## {fname}\n\n{content}")
    combined_md = "\n".join(combined)
    _safe_print(f"  Combined markdown: {len(combined_md):,} chars")

    # 保存 Phase1 输出供检查
    phase1_out = TEMP_PARSE_DIR / "phase1_output.md"
    phase1_out.write_text(combined_md[:50000], encoding="utf-8")
    _safe_print(f"  Saved preview to: {phase1_out}")

    # ================================================================
    # PHASE 2: 分析
    # ================================================================
    _safe_print("\n" + "-" * 50)
    _safe_print("  PHASE 2: 分析")
    _safe_print("-" * 50)

    # 2.1 财务提取
    _safe_print("\n  [2.1] Financial analysis...")
    financial = await run_financial_analysis(combined_md)
    _safe_print(f"        net_profit={financial.get('net_profit')}, op_rev={financial.get('operating_revenue')}")

    # 2.2 科技提取
    _safe_print("\n  [2.2] Tech innovation...")
    tech = await extract_tech_innovation_metrics(combined_md)
    rd_info = tech.get("rd_expense_ratio", {})
    _safe_print(f"        rd_ratio={rd_info}, patents={tech.get('patent_count')}, team={tech.get('team_size')}")

    # 2.3 基本信息提取
    _safe_print("\n  [2.3] Basic info extraction...")
    basic_info = await extract_enterprise_basic_info(combined_md)
    _safe_print(f"        company_name={basic_info.get('company_name', 'N/A')}")
    _safe_print(f"        unified_social_credit_code={basic_info.get('unified_social_credit_code', 'N/A')}")
    _safe_print(f"        legal_representative={basic_info.get('legal_representative', 'N/A')}")

    # 2.4 财务计算
    _safe_print("\n  [2.4] Financial ratio calculation...")
    computed_ratios = compute_financial_ratios(financial)
    financial_merged = merge_extracted_and_computed(financial, computed_ratios)
    _safe_print(f"        Computed: {list(computed_ratios.keys())[:5]}...")

    # 2.5 合规 + AI推理
    _safe_print("\n  [2.5] Compliance + AI inference...")
    screener = ComplianceScreener()
    compliance = await screener.run_checks({
        "enterprise_name": basic_info.get("company_name", "待提取"),
        "verified_markdown": combined_md,
    })
    _safe_print(f"        Compliance overall: {compliance.get('overall', 'N/A')}")

    # AI 推理（29字段）
    inference = await run_inference(
        enterprise_data={
            "enterprise_name": basic_info.get("company_name", "待提取"),
            "business_scope": basic_info.get("business_scope", ""),
            "shareholder_structure": basic_info.get("shareholder_structure", "待提取"),
        },
        financial_data=financial_merged,
        compliance_data=compliance,
    )
    _safe_print(f"        Inference generated: {len(inference)} fields")
    inference_ok = sum(1 for v in inference.values() if not v.startswith("【生成失败】"))
    _safe_print(f"        Successful: {inference_ok}/{len(inference)}")

    # ================================================================
    # PHASE 2 RESULTS SUMMARY
    # ================================================================
    _safe_print("\n" + "-" * 50)
    _safe_print("  PHASE 2 RESULTS SUMMARY")
    _safe_print("-" * 50)

    summary = {
        "phase1": {
            "parsed_files": n_success,
            "failed_files": n_failed,
            "markdown_chars": len(combined_md),
        },
        "phase2": {
            "financial_metrics": {
                k: financial_merged.get(k) for k in
                ["net_profit", "operating_revenue", "gross_margin",
                 "current_ratio", "debt_to_asset_ratio", "revenue_cagr", "rd_expense_ratio"]
            },
            "tech_metrics": {
                "rd_expense_ratio": tech.get("rd_expense_ratio"),
                "patent_count": tech.get("patent_count"),
                "team_size": tech.get("team_size"),
            },
            "basic_info": {
                k: basic_info.get(k) for k in
                ["company_name", "legal_representative", "registered_capital", "registration_date"]
                if basic_info.get(k)
            },
            "compliance": compliance.get("overall"),
            "inference_fields": len(inference),
            "inference_ok": inference_ok,
        },
    }

    _safe_print(json.dumps(summary, ensure_ascii=False, indent=2))

    # Save full results
    results_out = TEMP_PARSE_DIR / "phase2_results.json"
    results_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _safe_print(f"\n  Full results saved to: {results_out}")

    # Cleanup
    shutil.rmtree(TEMP_PARSE_DIR, ignore_errors=True)

    _safe_print("\n" + "=" * 70)
    _safe_print("  TEST COMPLETE")
    _safe_print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
