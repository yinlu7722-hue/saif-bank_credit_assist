"""
phase2_inference.py
Phase 2.6: AI 智能推理填充（使用 Minimax API — 并行批量版）

优化：
  1. 字段分组批量调用（每批一个 API 请求生成多个字段）
  2. asyncio.Semaphore 并发控制（3 批并行）
  3. 删除数据不足常驻字段（non_bank_financing_summary, litigation_status,
     negative_news, other_matters）
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

import anthropic

from shared.config import MINIMAX_API_KEY, MINIMAX_MODEL, HTTPS_PROXY
from shared.utils import safe_print as _safe_print

MINIMAX_API_BASE: str = "https://api.minimaxi.com/anthropic"

if HTTPS_PROXY:
    os.environ["HTTPS_PROXY"] = HTTPS_PROXY


# ============================================================================
# Prompt 模板
# ============================================================================

INFERENCE_SYSTEM_PROMPT: str = """你是一位资深银行对公信贷审批官，拥有20年企业信用评估经验。

【你的职责】
基于银行已收集的企业资料，为调查报告中各个分析字段生成专业、客观的中文分析文本。

【写作风格要求】
1. 语言简洁、专业，符合银行调查报告文风
2. 语气客观中性，不夸大企业优势，不回避问题
3. 每个字段生成200-400字的分析文本
4. 财务数据需注明"根据所提供的财务报表推算"
5. 如现有资料不足以形成有意义的分析，标注"根据现有资料无法确定，建议实地调研补充"

【禁止】
- 不编造任何未经确认的数据
- 不使用"该公司"、"该企业"等模糊表述，应用具体企业名称
- 不添加任何未经资料支持的结论
"""

BATCH_SYSTEM_PROMPT: str = """你是一位资深银行对公信贷审批官，拥有20年企业信用评估经验。
请为以下多个字段同时生成分析文本。输出必须是严格的 JSON 对象，键为字段名，值为分析文本。

【写作风格要求】
1. 每个字段 200-400 字，专业银行调查报告风格
2. 财务数据需注明"根据所提供的财务报表推算"
3. 数据不足时标注"根据现有资料无法确定，建议实地调研补充"
4. 不编造任何未经确认的数据
5. 不使用"该公司"、"该企业"等模糊表述
"""


# ============================================================================
# 字段定义（元数据）
# ============================================================================

INFERENCE_FIELDS: dict[str, dict[str, str]] = {
    # ── 一、申请人基本信息 ────────────────────────────────────
    "main_products": {
        "description": "企业主营业务产品，基于经营范围推断主要产品线",
        "chapter": "一、申请人基本信息",
    },
    "actual_controller": {
        "description": "企业实际控制人，基于股东结构和股权穿透分析",
        "chapter": "一、申请人基本信息",
    },
    "management_team_summary": {
        "description": "管理层资质、行业经验、内部控制能力综述",
        "chapter": "一、申请人基本信息",
    },
    "group_introduction": {
        "description": "集团基本情况、经营及财务状况、板块收入盈利综述",
        "chapter": "一、申请人基本信息",
    },
    # ── 二、申请人经营情况 ────────────────────────────────────
    "business_model": {
        "description": "企业商业模式（生产型/贸易型/服务型/轻资产/重资产）",
        "chapter": "二、申请人经营情况",
    },
    "core_technology": {
        "description": "企业核心技术描述，基于高新技术企业证书和研发费用推断",
        "chapter": "二、申请人经营情况",
    },
    "operation_analysis": {
        "description": "经营模式、生产工艺流程、盈利模式分析",
        "chapter": "二、申请人经营情况",
    },
    "capacity_output_summary": {
        "description": "产能产量及产能利用率概述，基于企业规模和行业特征推断",
        "chapter": "二、申请人经营情况",
    },
    "gross_margin_analysis": {
        "description": "毛利率变动趋势分析，基于近三年毛利率数据",
        "chapter": "二、申请人经营情况",
    },
    "current_orders_summary": {
        "description": "在手订单情况概述，如无具体订单数据标注'待企业提供订单明细'",
        "chapter": "二、申请人经营情况",
    },
    "major_investments": {
        "description": "近两年重大对外投资及在建项目情况",
        "chapter": "二、申请人经营情况",
    },
    # ── 三、申请人财务状况 ────────────────────────────────────
    "financial_metrics_summary": {
        "description": "财务指标综合分析，基于盈利能力/偿债能力/成长性指标给出评价",
        "chapter": "三、申请人财务状况",
    },
    "financial_analysis_conclusion": {
        "description": "财务分析总体结论，综合资产负债/损益/现金流给出最终判断",
        "chapter": "三、申请人财务状况",
    },
    # ── 四、申请人信用状况 ────────────────────────────────────
    "overall_credit_status": {
        "description": "企业总体信用情况评价，如无征信报告则注明",
        "chapter": "四、申请人信用状况",
    },
    "bank_financing": {
        "description": "银行融资情况，基于财务报表短期借款和长期借款科目汇总",
        "chapter": "四、申请人信用状况",
    },
    # ── 五、行业地位比较分析 ──────────────────────────────────
    "industry_position": {
        "description": "企业在行业中的地位，基于企业规模和财务指标与行业均值比较",
        "chapter": "五、行业地位比较分析",
    },
    "competitive_advantages": {
        "description": "企业竞争优势分析",
        "chapter": "五、行业地位比较分析",
    },
    "competitive_disadvantages": {
        "description": "企业竞争劣势分析",
        "chapter": "五、行业地位比较分析",
    },
    "industry_trend": {
        "description": "行业发展趋势分析，行业生命周期/市场结构/前景预判",
        "chapter": "五、行业地位比较分析",
    },
    "price_trend": {
        "description": "近三年主要原材料及产成品价格走势分析",
        "chapter": "五、行业地位比较分析",
    },
    # ── 七、授信用途及还款来源 ────────────────────────────────
    "credit_usage": {
        "description": "授信资金用途分析，基于企业经营情况推断典型用途",
        "chapter": "七、授信用途及还款来源",
    },
    "credit_usage_analysis": {
        "description": "授信用途合理性及真实性分析，结合结算方式/物流/交易对手说明",
        "chapter": "七、授信用途及还款来源",
    },
    "repayment_source": {
        "description": "还款来源分析，基于企业财务指标推断主要还款来源",
        "chapter": "七、授信用途及还款来源",
    },
    "repayment_method": {
        "description": "还款方式分析，如无具体信息标注'待与客户协商确定'",
        "chapter": "七、授信用途及还款来源",
    },
    # ── 八、担保情况 ──────────────────────────────────────────
    "collateral_pledge": {
        "description": "抵押质押担保情况，基于财务报表资产科目推断可能的抵押物",
        "chapter": "八、担保情况",
    },
    "guarantee_evaluation": {
        "description": "担保综合评价，对担保充足性和可行性的主观评估",
        "chapter": "八、担保情况",
    },
    # ── 九、授信收益与风险分析 ────────────────────────────────
    "return_analysis": {
        "description": "授信收益分析，基于财务指标和模拟利率计算收益",
        "chapter": "九、授信收益与风险分析",
    },
    "risk_evaluation": {
        "description": "综合风险评价，基于所有分析章节做全面风险评估",
        "chapter": "九、授信收益与风险分析",
    },
    "risk_level": {
        "description": "风险等级判定（低/中/高），基于风险评价结果",
        "chapter": "九、授信收益与风险分析",
    },
    "risk_mitigation_measures": {
        "description": "风险缓释措施建议，基于担保情况推荐缓释手段",
        "chapter": "九、授信收益与风险分析",
    },
    # ── 十、授信调查结论和授信方案 ─────────────────────────────
    "investigation_conclusion": {
        "description": "调查结论，综合10章分析给出总结性结论",
        "chapter": "十、授信调查结论和授信方案",
    },
    "reported_opinion": {
        "description": "上报意见，提交审批的建议性意见",
        "chapter": "十、授信调查结论和授信方案",
    },
    "recommended_credit_type": {
        "description": "建议授信品种（流动资金贷款/固定资产贷款等）",
        "chapter": "十、授信调查结论和授信方案",
    },
    "recommended_credit_amount": {
        "description": "建议授信金额，基于财务指标测算",
        "chapter": "十、授信调查结论和授信方案",
    },
    "recommended_term": {
        "description": "建议授信期限（个月）",
        "chapter": "十、授信调查结论和授信方案",
    },
    "recommended_guarantee": {
        "description": "建议担保方式",
        "chapter": "十、授信调查结论和授信方案",
    },
}

# ── 批量分组（按章节 + 关联性，每批 2-7 个字段）─────────────
FIELD_BATCHES: list[list[str]] = [
    # Batch 1: 申请人基本信息（4 字段）
    ["main_products", "actual_controller", "management_team_summary", "group_introduction"],
    # Batch 2: 经营情况 — 核心（4 字段）
    ["business_model", "core_technology", "operation_analysis", "gross_margin_analysis"],
    # Batch 3: 经营情况 — 补充（3 字段）
    ["capacity_output_summary", "current_orders_summary", "major_investments"],
    # Batch 4: 财务状况（2 字段）
    ["financial_metrics_summary", "financial_analysis_conclusion"],
    # Batch 5: 信用状况 + 行业（5 字段，关联度低但单字段信息量小）
    ["overall_credit_status", "bank_financing", "industry_position", "competitive_advantages", "competitive_disadvantages"],
    # Batch 6: 行业趋势 + 价格（2 字段）
    ["industry_trend", "price_trend"],
    # Batch 7: 授信用途及还款（4 字段）
    ["credit_usage", "credit_usage_analysis", "repayment_source", "repayment_method"],
    # Batch 8: 担保 + 风险（6 字段，高度关联）
    ["collateral_pledge", "guarantee_evaluation", "return_analysis",
     "risk_evaluation", "risk_level", "risk_mitigation_measures"],
    # Batch 9: 结论及授信方案（6 字段）
    ["investigation_conclusion", "reported_opinion", "recommended_credit_type",
     "recommended_credit_amount", "recommended_term", "recommended_guarantee"],
]

# ── 结构化字段 ─────────────────────────────────────────────
STRUCTURED_FIELDS: dict[str, dict[str, str]] = {
    "upstream_suppliers": {
        "description": "前五大供应商列表，每项包含 name/amount/ratio/product/years/payment/relation/remark",
        "chapter": "二、申请人经营情况",
        "output_format": "JSON array of objects",
    },
    "downstream_customers": {
        "description": "前五大销售商列表，每项包含 name/amount/ratio/product/years/payment/relation/remark",
        "chapter": "二、申请人经营情况",
        "output_format": "JSON array of objects",
    },
    "litigation_events": {
        "description": "重大诉讼及负面事件列表，每项包含 category/description/amount/date/impact/status",
        "chapter": "六、其他重要事项",
        "output_format": "JSON array of objects",
    },
}

# 并发控制
MAX_CONCURRENT = 3


# ============================================================================
# Minimax 客户端封装
# ============================================================================

class MinimaxInferenceEngine:
    """Phase 2.6 AI 推理引擎 — 并行批量版"""

    def __init__(self, api_key: str | None = None) -> None:
        key: str = api_key or MINIMAX_API_KEY
        self.client = anthropic.Anthropic(
            api_key=key,
            base_url=MINIMAX_API_BASE,
            timeout=120.0,
            max_retries=2,
        )
        self.model = MINIMAX_MODEL
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    # ── 批量生成 ──────────────────────────────────────────────

    async def _generate_batch(
        self,
        batch_index: int,
        field_names: list[str],
        enterprise_data: dict,
        financial_data: dict,
    ) -> dict[str, str]:
        """一次 API 调用生成一组字段，返回 {field_name: text}"""
        total_batches = len(FIELD_BATCHES)

        # 构建字段说明
        field_descriptions: list[str] = []
        for name in field_names:
            meta = INFERENCE_FIELDS.get(name, {})
            ch = meta.get("chapter", "")
            desc = meta.get("description", "")
            field_descriptions.append(f"  - {name}（{ch}）：{desc}")

        user_prompt = f"""请为以下 {len(field_names)} 个字段生成分析文本：

{chr(10).join(field_descriptions)}

【企业基本信息】：
{json.dumps(enterprise_data, ensure_ascii=False, indent=2)}

【财务指标数据】：
{json.dumps(financial_data, ensure_ascii=False, indent=2)}

【输出要求】
1. 输出纯 JSON 对象，键为字段名，值为分析文本
2. 不要代码块标记，不要任何解释文字
3. 每个字段 200-400 字
4. 数据不足的字段标注"根据现有资料无法确定，建议实地调研补充"
"""

        async with self._semaphore:
            _safe_print(f"  [Batch {batch_index+1}/{total_batches}] Generating {len(field_names)} fields: {', '.join(field_names)}...")
            try:
                response = await asyncio.to_thread(
                    self.client.messages.create,
                    model=self.model,
                    max_tokens=4096,
                    system=BATCH_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )

                raw_text: str = ""
                for block in response.content:
                    if hasattr(block, "text") and block.text:
                        raw_text = block.text
                        break

                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
                raw_text = re.sub(r"\s*```$", "", raw_text)

                parsed = json.loads(raw_text)
                if isinstance(parsed, dict):
                    ok_count = sum(1 for v in parsed.values() if "【生成失败】" not in str(v))
                    _safe_print(f"    [OK] Batch {batch_index+1}: {ok_count}/{len(field_names)} fields")
                    return parsed
                else:
                    raise ValueError(f"Expected dict, got {type(parsed)}")

            except Exception as e:
                _safe_print(f"    [FAIL] Batch {batch_index+1}: {str(e)[:80]}")
                return {name: f"【生成失败】{str(e)[:100]}" for name in field_names}

    async def _generate_structured(
        self,
        field_name: str,
        field_meta: dict,
        enterprise_data: dict,
        financial_data: dict,
    ) -> tuple[str, str]:
        """生成单个结构化字段（与批量并行执行）"""
        description = field_meta.get("description", "")
        chapter = field_meta.get("chapter", "")

        user_prompt = f"""基于以下企业资料，生成【{chapter} - {field_name}】的结构化数据。

【字段说明】：{description}

【企业基本信息】：
{json.dumps(enterprise_data, ensure_ascii=False, indent=2)}

【财务指标数据】：
{json.dumps(financial_data, ensure_ascii=False, indent=2)}

【要求】
1. 输出纯 JSON 数组
2. 不要代码块标记，不要任何解释文字
3. 如数据不足，输出空数组 []
4. 数字字段使用数值类型，文本字段使用字符串类型
"""

        async with self._semaphore:
            _safe_print(f"  [STRUCT] Generating: {field_name}...")
            try:
                response = await asyncio.to_thread(
                    self.client.messages.create,
                    model=self.model,
                    max_tokens=2048,
                    system=INFERENCE_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )

                raw_text: str = ""
                for block in response.content:
                    if hasattr(block, "text") and block.text:
                        raw_text = block.text
                        break

                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
                raw_text = re.sub(r"\s*```$", "", raw_text)

                parsed = json.loads(raw_text)
                if isinstance(parsed, list):
                    _safe_print(f"    [OK] {field_name}: {len(parsed)} items")
                    return field_name, json.dumps(parsed, ensure_ascii=False)
                else:
                    return field_name, "[]"

            except Exception as e:
                _safe_print(f"    [FAIL] {field_name}: {str(e)[:60]}")
                return field_name, f"【生成失败】{str(e)[:100]}"

    # ── 主入口 ─────────────────────────────────────────────────

    async def generate_all_fields(
        self,
        enterprise_data: dict,
        financial_data: dict,
    ) -> dict[str, str]:
        """并行批量生成所有字段"""
        total_batches = len(FIELD_BATCHES)
        total_structured = len(STRUCTURED_FIELDS)
        _safe_print(f"\n[Phase 2.6] Starting AI inference: {total_batches} batches + {total_structured} structured (max {MAX_CONCURRENT} concurrent)")
        _safe_print("=" * 60)

        # ── 并行执行所有批量调用 ────────────────────────────────
        batch_tasks = [
            self._generate_batch(i, names, enterprise_data, financial_data)
            for i, names in enumerate(FIELD_BATCHES)
        ]
        structured_tasks = [
            self._generate_structured(name, meta, enterprise_data, financial_data)
            for name, meta in STRUCTURED_FIELDS.items()
        ]

        all_tasks = batch_tasks + structured_tasks
        batch_results = await asyncio.gather(*all_tasks)

        # ── 合并结果 ────────────────────────────────────────────
        results: dict[str, str] = {}
        for item in batch_results:
            if isinstance(item, dict):
                results.update(item)
            elif isinstance(item, tuple) and len(item) == 2:
                results[item[0]] = item[1]

        # ── 确保所有声明的字段都有值 ────────────────────────────
        total_fields = len(INFERENCE_FIELDS) + len(STRUCTURED_FIELDS)
        ok_count = sum(1 for v in results.values() if "【生成失败】" not in str(v))
        for name in INFERENCE_FIELDS:
            if name not in results:
                results[name] = "【跳过】未生成"
        for name in STRUCTURED_FIELDS:
            if name not in results:
                results[name] = "[]"

        _safe_print("\n" + "=" * 60)
        _safe_print(f"[Phase 2.6] Done! {ok_count}/{total_fields} fields OK, {total_fields - ok_count} failed/skipped")
        _safe_print("=" * 60 + "\n")

        return results


# ============================================================================
# 便捷封装
# ============================================================================

async def run_inference(
    enterprise_data: dict,
    financial_data: dict,
) -> dict[str, str]:
    """执行 Phase 2.6 AI 推理（并行批量版）"""
    engine = MinimaxInferenceEngine()
    return await engine.generate_all_fields(enterprise_data, financial_data)
