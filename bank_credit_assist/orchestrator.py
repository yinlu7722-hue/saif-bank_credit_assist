"""
orchestrator.py
对公信贷智能化辅助系统 — 后台编排引擎（v3.2）

完整工作流（v3.2）：
Phase1 解析 → Phase2 分析（财务+科技特征+合规）→ 人工核对结构化数据 → Phase3 报告生成

注：app.py 直接调用各 Phase 函数，orchestrator.py 提供便捷封装供外部使用。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from phase1_parser import phase1_parse_documents
from phase2_analysis import run_financial_analysis, extract_tech_innovation_metrics
from phase2_compliance import ComplianceScreener
from phase3_gemini import generate_report, FinalReport


class WorkflowOrchestrator:
    """
    工作流编排器
    管理 Phase1 → Phase2 → Phase3 完整流程（v3.2 Human-in-the-Loop）
    """

    def __init__(
        self,
        template_path: Path | str,
        output_dir: Path | str | None = None,
    ) -> None:
        self.template_path: Path = Path(template_path)
        self.output_dir: Path = Path(output_dir or "output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def run_phase1(self, input_dir: Path | str) -> dict[str, Any]:
        """
        执行 Phase1: 多模态资料解析
        Excel 文件强制走 pandas 本地解析，不发 MinerU
        """
        result = await phase1_parse_documents(input_dir)
        combined: list[str] = []
        for fname, content in result["contents"].items():
            combined.append(f"\n\n## 📄 {fname}\n\n{content}")
        combined_markdown: str = "\n".join(combined)
        return {
            "contents": result["contents"],
            "failed_files": result["failed_files"],
            "combined_markdown": combined_markdown,
        }

    async def run_phase2(self, markdown: str) -> dict[str, Any]:
        """
        执行 Phase2: 财务分析 + 科技特征提取 + 合规筛查
        不等待人工核对，直接返回结构化结果供 HITL 环节展示
        """
        financial_metrics: dict = await run_financial_analysis(markdown)
        tech_metrics: dict = await extract_tech_innovation_metrics(markdown)
        screener: ComplianceScreener = ComplianceScreener()
        enterprise_data: dict = {
            "enterprise_name": financial_metrics.get("enterprise_name", "待提取"),
            "verified_markdown": markdown,
        }
        compliance_results: dict = await screener.run_checks(enterprise_data)
        return {
            "financial_metrics": financial_metrics,
            "tech_metrics": tech_metrics,
            "compliance_results": compliance_results,
        }

    async def run_phase3(
        self,
        markdown: str,
        verified_financial_metrics: dict,
        tech_metrics: dict,
        compliance_results: dict,
    ) -> str:
        """
        执行 Phase3: Gemini 报告生成

        参数:
            verified_financial_metrics: 人工核对并修正后的财务指标（来自 st.data_editor）
        """
        enterprise_data: dict = {
            "enterprise_name": verified_financial_metrics.get("enterprise_name", "待提取"),
            "markdown": markdown,
        }
        timestamp: int = int(time.time())
        output_path: Path = self.output_dir / f"授信审查报告_{timestamp}.docx"
        await generate_report(
            enterprise_data=enterprise_data,
            financial_metrics=verified_financial_metrics,
            compliance_results=compliance_results,
            template_path=self.template_path,
            output_path=output_path,
        )
        return str(output_path)

    async def run_full_workflow(self, input_dir: Path | str) -> dict[str, Any]:
        """
        执行完整工作流（Phase1 → Phase2 → Phase3）
        人工核对由 app.py 的 st.data_editor 环节负责，不在此处处理
        """
        phase1_result = await self.run_phase1(input_dir)
        phase2_result = await self.run_phase2(phase1_result["combined_markdown"])
        report_path = await self.run_phase3(
            markdown=phase1_result["combined_markdown"],
            verified_financial_metrics=phase2_result["financial_metrics"],
            tech_metrics=phase2_result["tech_metrics"],
            compliance_results=phase2_result["compliance_results"],
        )
        return {
            "phase1": phase1_result,
            "phase2": phase2_result,
            "report_path": report_path,
        }


# ============================================================================
# 便捷封装
# ============================================================================

async def run_workflow(
    input_dir: Path | str,
    template_path: Path | str,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    """
    端到端工作流执行（供外部脚本调用）
    """
    orchestrator = WorkflowOrchestrator(template_path=template_path, output_dir=output_dir)
    return await orchestrator.run_full_workflow(input_dir)
