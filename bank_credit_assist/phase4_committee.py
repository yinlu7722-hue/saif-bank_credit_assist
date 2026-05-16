"""
phase4_committee.py
Phase 4: 模拟贷审会 — 多智能体辩论系统

5位独立评委 Agent，5轮动态辩论，1位牵头审批官终审汇总。
参考 FinRobot 的多智能体架构，复用 Minimax Anthropic 兼容 API。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import anthropic

from shared.config import MINIMAX_API_KEY, MINIMAX_MODEL, HTTPS_PROXY
from shared.utils import safe_print as _safe_print

MINIMAX_API_BASE: str = "https://api.minimaxi.com/anthropic"

if HTTPS_PROXY:
    os.environ["HTTPS_PROXY"] = HTTPS_PROXY


# ============================================================================
# 5位评委配置
# ============================================================================

AGENT_CONFIGS: dict[str, dict] = {
    "lead_approver": {
        "agent_id": "lead_approver",
        "name": "牵头审批官（李行长）",
        "short_name": "李行长",
        "role": "牵头审批官",
        "role_desc": "某商业银行公司业务部总经理，贷审会主持人，拥有25年对公信贷审批经验，经手上千笔企业贷款，在行内以平衡风险与业务发展著称。",
        "personality": "沉稳大气，善于倾听和引导，关键时刻能一针见血指出核心矛盾。习惯在各方充分表达后做总结陈词。不喜欢急于下结论，但一旦认定风险过高会果断否决。",
        "criteria": """1. 综合风险收益：授信是否在风险可控范围内带来合理收益
2. 意见平衡：是否有充分的信息支撑决策，各方意见是否被充分考虑
3. 制度合规：授信是否符合行内信贷政策和监管要求
4. 还款保障：第一还款来源是否充足，第二还款来源是否可靠""",
    },
    "risk_officer": {
        "agent_id": "risk_officer",
        "name": "风险审批官（王审）",
        "short_name": "王审",
        "role": "风险审批官",
        "role_desc": "风险管理部资深审批官，15年风控经验，曾成功预警多起大额不良。性格保守审慎，信奉'宁可错杀不可放过'。",
        "personality": "质疑一切乐观假设。口头禅：'这个数据有没有交叉验证过？'习惯从最坏情况出发思考问题。对担保措施有近乎苛刻的要求。当其他评委过于乐观时会直接泼冷水。",
        "criteria": """1. 违约概率：企业所处行业周期、经营稳定性、财务健康度
2. 担保充足性：抵质押物价值是否覆盖敞口、变现难度
3. 还款来源可靠性：第一还款来源是否真实稳定
4. 关联风险：实际控制人其他业务风险、对外担保敞口""",
    },
    "industry_officer": {
        "agent_id": "industry_officer",
        "name": "行业审批官（张博士）",
        "short_name": "张博士",
        "role": "行业审批官",
        "role_desc": "行业研究部总监，产业经济学博士，10年行业研究经验。擅长分析行业周期、竞争格局和技术演变趋势。",
        "personality": "战略思维、前瞻视角。喜欢用数据和模型说话。口头禅：'从行业周期来看...'。关注企业是否在正确的赛道。当企业所处行业处于下行周期时，无论其财务多好都会持保留态度。",
        "criteria": """1. 行业生命周期：行业处于上升期/成熟期/衰退期
2. 竞争格局：市场集中度、企业市场份额、进入壁垒
3. 技术替代风险：是否有颠覆性技术威胁企业核心业务
4. 政策环境：产业政策导向、环保合规、进出口依赖度""",
    },
    "finance_officer": {
        "agent_id": "finance_officer",
        "name": "财务审批官（陈会计）",
        "short_name": "陈会计",
        "role": "财务审批官",
        "role_desc": "授信审批部财务分析专家，注册会计师，12年审计+信贷经验。擅长从财务报表中发现隐藏的风险信号。",
        "personality": "数据驱动、细节导向。口头禅：'数字不会说谎，但人会。'对财务造假信号极度敏感，习惯逐项核对报表科目。当企业的财务比率偏离行业均值过大时会立刻警觉。不信任未经审计的报表。",
        "criteria": """1. 盈利能力真实性：收入确认方式、毛利率合理性、关联交易占比
2. 资产质量：应收账款集中度/账龄、存货跌价风险、固定资产成新率
3. 负债真实性：隐性负债、表外融资、对外担保
4. 现金流健康度：经营现金流是否覆盖利息支出、投融资现金流的合理性""",
    },
    "compliance_officer": {
        "agent_id": "compliance_officer",
        "name": "合规审批官（赵律师）",
        "short_name": "赵律师",
        "role": "合规审批官",
        "role_desc": "法律合规部高级经理，前律所合伙人，10年金融法律经验。对监管政策、法律法规有深入理解。",
        "personality": "规则至上、严谨细致。口头禅：'监管文件第X条规定...'。对不合规事项零容忍。当发现企业的股权结构复杂或实际控制人不清晰时会高度警惕。对任何'打擦边球'的做法会直接否决。",
        "criteria": """1. 主体合规：营业执照、经营许可是否齐备有效
2. 股权合规：股权结构是否清晰、实际控制人是否可穿透
3. 环保合规：是否属于高污染/高耗能行业、环保处罚记录
4. 法律纠纷：重大诉讼、行政处罚、失信记录""",
    },
}


# ============================================================================
# System Prompt 构建
# ============================================================================

def build_agent_system_prompt(config: dict) -> str:
    """为每位评委构建独立的 system prompt"""
    return f"""【角色定位】
你是{config['role_desc']}

【性格特征】
{config['personality']}

【审查准则】
{config['criteria']}

【发言规则】
1. 基于《贷审会简报》中的事实和数据发表意见，不编造信息
2. 明确表达立场：同意 / 有条件同意 / 需要补充 / 否决
3. 给出具体、可操作的论据，不要泛泛而谈
4. 可以点名其他评委回应你的关切
5. 如果被其他评委说服，可以修正自己的立场
6. 坚持自己的判断，不随意妥协——除非对方提供了你没有考虑到的信息

【当前贷审会阶段】
你正在参加某银行对公授信贷审会，审议一笔企业授信申请。
你会看到《贷审会简报》和其他评委的发言记录。
请基于你的专业角色发表意见。"""


SPEAKER_SELECTOR_SYSTEM_PROMPT = """你是贷审会流程管理者。根据当前的辩论进展，选择下一位发言人。

【选择原则】
1. 优先选择被上一轮发言人点名的评委
2. 确保每位评委在本轮至少发言一次
3. 不要连续选择同一位评委
4. 当所有评委都已发言且没有新的争论点时，输出 END_ROUND
5. 牵头审批官每轮最多发言两次（开场引导 + 阶段性总结）

【输出格式】
输出纯 JSON：{"next_speaker": "<agent_id>", "reason": "选择理由"}
或结束本轮：{"next_speaker": "END_ROUND", "reason": "所有评委已充分表达"}
"""


# ============================================================================
# CommitteeAgent 类
# ============================================================================

class CommitteeAgent:
    """独立评委智能体"""

    def __init__(self, config: dict, client: anthropic.Anthropic, model: str) -> None:
        self.agent_id: str = config["agent_id"]
        self.name: str = config["name"]
        self.short_name: str = config["short_name"]
        self.role: str = config["role"]
        self.system_prompt: str = build_agent_system_prompt(config)
        self.client = client
        self.model = model
        self.initial_position: dict | None = None
        self.final_position: dict | None = None

    async def respond(self, instruction: str) -> str:
        """调用 AI 生成发言，返回文本内容"""
        try:
            response = await asyncio.to_thread(
                self.client.messages.create,
                model=self.model,
                max_tokens=2048,
                system=self.system_prompt,
                messages=[{"role": "user", "content": instruction}],
            )
            raw_text: str = ""
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    raw_text = block.text
                    break
            return raw_text.strip()
        except Exception as e:
            _safe_print(f"  [ERROR] {self.name} respond failed: {e}")
            return f"【发言失败】{str(e)[:200]}"

    def parse_position(self, text: str) -> dict:
        """从发言文本中提取结构化立场"""
        result = {
            "conclusion": "未明确",
            "reasons": [],
            "risks": [],
            "confidence": "中等",
        }

        text_lower = text.lower()
        # 提取结论
        for keyword in ["有条件同意", "同意", "需要补充", "否决", "有条件通过"]:
            if keyword in text:
                result["conclusion"] = keyword
                break

        # 提取信心水平
        if any(w in text_lower for w in ["高度确信", "把握较大", "确定性高", "风险可控"]):
            result["confidence"] = "较高"
        elif any(w in text_lower for w in ["不确定", "存疑", "有待核实", "风险较高"]):
            result["confidence"] = "较低"

        return result


# ============================================================================
# CommitteeOrchestrator 编排器
# ============================================================================

@dataclass
class CommitteeResult:
    """贷审会完整结果"""
    briefing: str = ""
    initial_positions: dict[str, dict] = field(default_factory=dict)
    debate_log: list[dict] = field(default_factory=list)
    final_positions: dict[str, dict] = field(default_factory=dict)
    final_conclusion: dict = field(default_factory=dict)
    position_shifts: dict[str, dict] = field(default_factory=dict)


class CommitteeOrchestrator:
    """贷审会编排器 — 管理5位Agent + 5轮辩论"""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        key = api_key or MINIMAX_API_KEY
        self.client = anthropic.Anthropic(
            api_key=key,
            base_url=MINIMAX_API_BASE,
            timeout=120.0,
            max_retries=2,
        )
        self.model = model or MINIMAX_MODEL
        self.agents: dict[str, CommitteeAgent] = {}
        self.debate_log: list[dict] = []
        self._init_agents()

    def _init_agents(self) -> None:
        for agent_id, config in AGENT_CONFIGS.items():
            self.agents[agent_id] = CommitteeAgent(config, self.client, self.model)

    # ── Briefing 构建 ──────────────────────────────────────────────

    def _build_briefing(self, session_data: dict) -> str:
        """从 Phase2/Phase3 结果构建贷审会简报"""
        phase2 = session_data.get("phase2_result", {})
        inference = session_data.get("inference_text", {})
        financial = phase2.get("financial", {})
        basic_info = phase2.get("basic_info", {})
        tech = phase2.get("tech", {})
        income_v = phase2.get("income_verification", {})

        def _v(data: dict, *keys, default="待提取"):
            for k in keys:
                val = data.get(k)
                if val not in (None, "", 0):
                    return val
            return default

        company_name = _v(basic_info, "company_name") or _v(financial, "enterprise_name")

        # 财务指标表
        def _num(v, fmt=".2f"):
            if v is None:
                return "—"
            try:
                n = float(v)
                if fmt == ".0f":
                    return f"{n:,.0f}"
                elif fmt == ".2f":
                    return f"{n:,.2f}"
                elif fmt == ".1%":
                    return f"{n*100:.1f}%" if abs(n) < 10 else f"{n:.1f}%"
                return str(n)
            except (ValueError, TypeError):
                return str(v)

        briefing_parts = [
            f"# 贷审会简报\n\n**审议企业**：{company_name}\n**会议时间**：{datetime.now().strftime('%Y年%m月%d日')}",
            f"\n## 一、企业基本信息",
            f"- 统一社会信用代码：{_v(basic_info, 'unified_social_credit_code')}",
            f"- 法定代表人：{_v(basic_info, 'legal_representative')}",
            f"- 注册资本：{_v(basic_info, 'registered_capital')}",
            f"- 成立日期：{_v(basic_info, 'registration_date')}",
            f"- 经营范围：{_v(basic_info, 'business_scope')}",
            f"- 实际控制人：{_v(basic_info, 'actual_controller')}",
            f"- 股东结构：{_v(basic_info, 'shareholder_structure')}",
            f"\n## 二、经营情况",
            f"- 商业模式：{_v(inference, 'business_model')}",
            f"- 核心技术：{_v(inference, 'core_technology')}",
            f"- 经营分析：{_v(inference, 'operation_analysis')}",
            f"- 主营产品：{_v(inference, 'main_products')}",
            f"\n## 三、财务状况",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 营业收入 | {_num(financial.get('operating_revenue'), '.0f')} 元 |",
            f"| 净利润 | {_num(financial.get('net_profit'), '.0f')} 元 |",
            f"| 毛利率 | {_num(financial.get('gross_margin'), '.1%')} |",
            f"| 资产负债率 | {_num(financial.get('debt_to_asset_ratio'), '.1%')} |",
            f"| 流动比率 | {_num(financial.get('current_ratio'), '.2f')} |",
            f"| 速动比率 | {_num(financial.get('quick_ratio'), '.2f')} |",
            f"| ROE | {_num(financial.get('roe'), '.1%')} |",
            f"| 总资产 | {_num(financial.get('total_assets'), '.0f')} 元 |",
            f"| 总负债 | {_num(financial.get('total_liabilities'), '.0f')} 元 |",
            f"| 刚性负债 | {_num(financial.get('rigid_liabilities'), '.0f')} 元 |",
            f"| 营收复合增长率 | {_num(financial.get('revenue_cagr'), '.1%')} |",
            f"| 净利润复合增长率 | {_num(financial.get('net_profit_cagr'), '.1%')} |",
            f"\n### 收入交叉核验",
            f"- 报表营收：{_num(income_v.get('report_revenue'), '.0f')} 元",
            f"- 银行流水：{_num(income_v.get('bank_inflow'), '.0f')} 元",
            f"- 纳税申报：{_num(income_v.get('tax_revenue'), '.0f')} 元",
            f"- 银行偏差：{_v(income_v, 'bank_deviation_pct', default='—')}",
            f"- 税务偏差：{_v(income_v, 'tax_deviation_pct', default='—')}",
            f"- 核验结论：{_v(income_v, 'conclusion')}",
            f"\n## 四、信用状况",
            f"- 整体信用：{_v(inference, 'overall_credit_status')}",
            f"- 银行融资：{_v(inference, 'bank_financing')}",
            f"\n## 五、行业与竞争力",
            f"- 行业地位：{_v(inference, 'industry_position')}",
            f"- 竞争优势：{_v(inference, 'competitive_advantages')}",
            f"- 竞争劣势：{_v(inference, 'competitive_disadvantages')}",
            f"- 行业趋势：{_v(inference, 'industry_trend')}",
            f"\n## 六、风险分析",
            f"- 风险等级：{_v(inference, 'risk_level')}",
            f"- 风险评价：{_v(inference, 'risk_evaluation')}",
            f"- 缓释措施：{_v(inference, 'risk_mitigation_measures')}",
            f"\n## 七、建议授信方案（系统建议，仅供参考）",
            f"- 授信用途：{_v(inference, 'credit_usage')}",
            f"- 建议金额：{_v(inference, 'recommended_credit_amount')}",
            f"- 建议期限：{_v(inference, 'recommended_term')}",
            f"- 建议担保：{_v(inference, 'recommended_guarantee')}",
        ]

        # 附加科技属性（如有）
        rd_info = tech.get("rd_expense_ratio", {})
        if rd_info and rd_info.get("value"):
            briefing_parts.insert(5, f"\n### 科技属性\n- 研发费用占比：{rd_info.get('value')}{rd_info.get('unit', '%')}\n- 专利数量：{tech.get('patent_count', '—')}\n- 高新认证：{tech.get('high_tech_cert', {}).get('value', '—')}")

        return "\n".join(briefing_parts)

    # ── Speaker Selector ───────────────────────────────────────────

    async def _select_next_speaker(
        self, round_num: int, spoken_agents: set[str], last_speaker: str,
        debate_so_far: str, lead_has_spoken: int = 0,
    ) -> str:
        """LLM 驱动的动态发言人选择"""
        available = []
        for agent_id, agent in self.agents.items():
            spoke_count = sum(1 for log in self.debate_log if log.get("round") == round_num and log.get("speaker") == agent_id)
            if agent_id == "lead_approver":
                if lead_has_spoken >= 2:
                    continue
            available.append(f"  - {agent_id} ({agent.name}) — {'已发言' if agent_id in spoken_agents else '未发言'}（本轮已{spoke_count}次）")

        selector_prompt = f"""当前是第{round_num}轮辩论。

本轮已发言的评委：{spoken_agents or '无'}
上一发言人：{last_speaker or '无'}
牵头审批官本轮已发言{lead_has_spoken}次。

可选评委：
{chr(10).join(available)}

最近讨论摘要：
{debate_so_far[-1500:] if len(debate_so_far) > 1500 else debate_so_far}

请选择下一位发言人（或 END_ROUND）。"""

        try:
            response = await asyncio.to_thread(
                self.client.messages.create,
                model=self.model,
                max_tokens=256,
                system=SPEAKER_SELECTOR_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": selector_prompt}],
            )
            raw_text: str = ""
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    raw_text = block.text
                    break

            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
            raw_text = re.sub(r"\s*```$", "", raw_text)
            result = json.loads(raw_text)
            return result.get("next_speaker", "END_ROUND")

        except Exception as e:
            _safe_print(f"  [SpeakerSelector Error] {e}")
            # 回退：选择第一个未发言的评委
            for agent_id in self.agents:
                if agent_id not in spoken_agents and agent_id != "lead_approver":
                    return agent_id
            return "END_ROUND"

    # ── Round 实现 ────────────────────────────────────────────────

    async def _run_round_1(self, briefing: str, on_progress: Callable | None) -> dict[str, dict]:
        """Round 1: 独立初审 — 5位评委并行审阅"""
        _safe_print("\n" + "=" * 60)
        _safe_print("  ROUND 1: 独立初审")
        _safe_print("=" * 60)

        positions: dict[str, dict] = {}

        async def agent_initial_review(agent: CommitteeAgent) -> tuple[str, str, dict]:
            instruction = f"""{briefing}

【本轮任务 — 独立初审】
请仔细审阅以上《贷审会简报》，给出你的独立初审意见。

【注意】你现在看不到其他评委的意见。请完全基于你自己的专业判断。

【输出要求】
1. 明确你的初审结论（同意/有条件同意/需要补充/否决）
2. 列出3-5条核心理由
3. 指出你关注的主要风险点（至少2条）
4. 提出你希望在后续讨论中探讨的问题（至少1条）"""

            _safe_print(f"  [{agent.short_name}] 开始独立审阅...")
            response = await agent.respond(instruction)
            position = agent.parse_position(response)
            agent.initial_position = position
            _safe_print(f"  [{agent.short_name}] 初审结论: {position.get('conclusion', '未明确')}")
            return agent.agent_id, response, position

        tasks = [agent_initial_review(agent) for agent in self.agents.values()]
        results = await asyncio.gather(*tasks)

        for agent_id, response, position in results:
            positions[agent_id] = position
            log_entry = {
                "round": 1,
                "speaker": agent_id,
                "speaker_name": self.agents[agent_id].name,
                "content": response,
                "position": position,
            }
            self.debate_log.append(log_entry)
            if on_progress:
                on_progress(log_entry)

        return positions

    async def _run_round_2(self, briefing: str, on_progress: Callable | None) -> None:
        """Round 2: 风险与合规交锋"""
        _safe_print("\n" + "=" * 60)
        _safe_print("  ROUND 2: 风险与合规交锋")
        _safe_print("=" * 60)

        lead = self.agents["lead_approver"]
        spoken: set[str] = set()
        lead_speak_count = 0

        # 牵头官开场引导
        initial_summary = self._summarize_positions()
        round_so_far = ""

        lead_instruction = f"""{briefing}

【本轮任务 — 风险与合规交锋（开场引导）】

各位评委的初审结论汇总：
{initial_summary}

请做开场引导：简要总结各方初始立场，指出核心分歧点，然后请风险审批官首先就风险关切发言。发言控制在200字以内。"""

        _safe_print(f"  [{lead.short_name}] 开场引导...")
        lead_response = await lead.respond(lead_instruction)
        self._log_speech(2, "lead_approver", lead.name, lead_response, lead.parse_position(lead_response))
        if on_progress:
            on_progress(self.debate_log[-1])
        spoken.add("lead_approver")
        lead_speak_count += 1
        round_so_far += f"\n\n{lead.name}: {lead_response[:300]}"

        # 动态发言循环（最多6轮）
        last_speaker = "lead_approver"
        for _ in range(6):
            next_id = await self._select_next_speaker(2, spoken, last_speaker, round_so_far, lead_speak_count)
            if next_id == "END_ROUND":
                break

            agent = self.agents[next_id]
            instruction = self._build_round_2_3_instruction(
                briefing, 2, next_id, spoken, round_so_far
            )
            _safe_print(f"  [{agent.short_name}] 发言...")
            response = await agent.respond(instruction)
            self._log_speech(2, next_id, agent.name, response, agent.parse_position(response))
            if on_progress:
                on_progress(self.debate_log[-1])
            spoken.add(next_id)
            if next_id == "lead_approver":
                lead_speak_count += 1
            last_speaker = next_id
            round_so_far += f"\n\n{agent.name}: {response[:400]}"

    async def _run_round_3(self, briefing: str, on_progress: Callable | None) -> None:
        """Round 3: 行业与财务交锋"""
        _safe_print("\n" + "=" * 60)
        _safe_print("  ROUND 3: 行业与财务交锋")
        _safe_print("=" * 60)

        lead = self.agents["lead_approver"]
        spoken: set[str] = set()
        lead_speak_count = 0

        # 牵头官转移焦点到行业与财务
        lead_instruction = f"""{briefing}

【本轮任务 — 行业与财务交锋（开场引导）】

上一轮我们重点讨论了风险与合规方面的问题。现在请各位将焦点转向行业地位和财务分析。

请行业审批官（张博士）首先发言，分析该企业所处行业的周期位置、竞争壁垒和技术风险。然后请财务审批官（陈会计）从财务数据角度进行补充或质疑。

请做简短引导，控制在150字以内。"""

        _safe_print(f"  [{lead.short_name}] 引导行业/财务讨论...")
        lead_response = await lead.respond(lead_instruction)
        self._log_speech(3, "lead_approver", lead.name, lead_response, lead.parse_position(lead_response))
        if on_progress:
            on_progress(self.debate_log[-1])
        spoken.add("lead_approver")
        lead_speak_count += 1
        round_so_far = f"{lead.name}: {lead_response[:300]}"

        last_speaker = "lead_approver"
        for _ in range(6):
            next_id = await self._select_next_speaker(3, spoken, last_speaker, round_so_far, lead_speak_count)
            if next_id == "END_ROUND":
                break

            agent = self.agents[next_id]
            instruction = self._build_round_2_3_instruction(
                briefing, 3, next_id, spoken, round_so_far
            )
            _safe_print(f"  [{agent.short_name}] 发言...")
            response = await agent.respond(instruction)
            self._log_speech(3, next_id, agent.name, response, agent.parse_position(response))
            if on_progress:
                on_progress(self.debate_log[-1])
            spoken.add(next_id)
            if next_id == "lead_approver":
                lead_speak_count += 1
            last_speaker = next_id
            round_so_far += f"\n\n{agent.name}: {response[:400]}"

    async def _run_round_4(self, briefing: str, on_progress: Callable | None) -> None:
        """Round 4: 自由辩论"""
        _safe_print("\n" + "=" * 60)
        _safe_print("  ROUND 4: 自由辩论")
        _safe_print("=" * 60)

        lead = self.agents["lead_approver"]
        spoken: set[str] = set()
        lead_speak_count = 0

        debate_summary = self._summarize_rounds(2, 3)

        lead_instruction = f"""{briefing}

【本轮任务 — 自由辩论（开场引导）】

在风险、合规、行业和财务各方面都已有了比较充分的讨论。现在是自由辩论环节。

前两轮讨论摘要：
{debate_summary}

请各位评委自由发言：可以质疑其他评委的观点，可以补充之前遗漏的要点，也可以修正自己之前的判断。如果你被其他评委说服了，请明确说明。

做简短引导，然后请任意一位评委开始。控制在150字以内。"""

        _safe_print(f"  [{lead.short_name}] 开启自由辩论...")
        lead_response = await lead.respond(lead_instruction)
        self._log_speech(4, "lead_approver", lead.name, lead_response, lead.parse_position(lead_response))
        if on_progress:
            on_progress(self.debate_log[-1])
        spoken.add("lead_approver")
        lead_speak_count += 1
        round_so_far = f"{lead.name}: {lead_response[:300]}"

        last_speaker = "lead_approver"
        for _ in range(7):
            next_id = await self._select_next_speaker(4, spoken, last_speaker, round_so_far, lead_speak_count)
            if next_id == "END_ROUND":
                break

            agent = self.agents[next_id]
            instruction = self._build_round_4_instruction(
                briefing, next_id, spoken, round_so_far
            )
            _safe_print(f"  [{agent.short_name}] 自由发言...")
            response = await agent.respond(instruction)
            self._log_speech(4, next_id, agent.name, response, agent.parse_position(response))
            if on_progress:
                on_progress(self.debate_log[-1])
            spoken.add(next_id)
            if next_id == "lead_approver":
                lead_speak_count += 1
            last_speaker = next_id
            round_so_far += f"\n\n{agent.name}: {response[:400]}"

    async def _run_round_5(self, briefing: str, on_progress: Callable | None) -> dict:
        """Round 5: 牵头审批官终审汇总"""
        _safe_print("\n" + "=" * 60)
        _safe_print("  ROUND 5: 牵头审批官终审汇总")
        _safe_print("=" * 60)

        lead = self.agents["lead_approver"]

        # 收集所有评委的当前立场
        all_positions = self._collect_current_positions()
        full_debate = self._get_full_debate_transcript()

        lead_instruction = f"""{briefing}

【本轮任务 — 终审汇总】

你是本次贷审会的牵头审批官。经过四轮激烈辩论，现在请你做最终汇总。

【各位评委的最终立场】
{all_positions}

【全程辩论记录摘要】
{full_debate[-3000:]}

【输出要求】
请严格按以下 JSON 格式输出（不要代码块标记）：

{{
    "final_conclusion": "同意/有条件同意/需要补充/否决",
    "core_reasons": [
        "核心理由1（每条20-50字）",
        "核心理由2",
        "核心理由3"
    ],
    "risk_warnings": [
        "风险提示1（每条20-50字）",
        "风险提示2"
    ],
    "recommended_credit": {{
        "amount": "建议金额（如：3000万元）",
        "term": "建议期限（如：12个月）",
        "interest_rate": "建议利率（如：LPR+100BP）",
        "guarantee": "建议担保方式",
        "conditions": ["放款前提条件1", "放款前提条件2"]
    }},
    "judge_summary": {{
        "risk_officer_final": "风险官最终立场（总结）",
        "industry_officer_final": "行业官最终立场（总结）",
        "finance_officer_final": "财务官最终立场（总结）",
        "compliance_officer_final": "合规官最终立场（总结）",
        "lead_approver_final": "你的最终立场（总结）"
    }},
    "overall_assessment": "综合评价（150字以内）"
}}"""

        _safe_print(f"  [{lead.short_name}] 正在汇总终审...")
        response = await lead.respond(lead_instruction)

        # 解析 JSON 结论
        conclusion = self._parse_final_conclusion(response)
        self._log_speech(5, "lead_approver", lead.name, response, {"conclusion": conclusion.get("final_conclusion", "未明确")})
        if on_progress:
            on_progress(self.debate_log[-1])

        return conclusion

    # ── 辅助方法 ──────────────────────────────────────────────────

    def _log_speech(self, round_num: int, speaker_id: str, speaker_name: str, content: str, position: dict) -> None:
        self.debate_log.append({
            "round": round_num,
            "speaker": speaker_id,
            "speaker_name": speaker_name,
            "content": content,
            "position": position,
        })

    def _summarize_positions(self) -> str:
        """汇总初审立场"""
        lines = []
        for agent_id, agent in self.agents.items():
            pos = agent.initial_position or {}
            lines.append(f"- {agent.name}：{pos.get('conclusion', '未表态')}")
        return "\n".join(lines)

    def _summarize_rounds(self, *round_nums: int) -> str:
        """压缩指定轮次的发言"""
        lines = []
        for log in self.debate_log:
            if log["round"] in round_nums:
                lines.append(f"[{log['speaker_name']}] {log['content'][:200]}...")
        return "\n\n".join(lines)

    def _get_full_debate_transcript(self) -> str:
        lines = []
        for log in self.debate_log:
            lines.append(f"## 第{log['round']}轮 — {log['speaker_name']}\n{log['content']}\n")
        return "\n".join(lines)

    def _collect_current_positions(self) -> str:
        """收集所有评委当前立场"""
        parts = []
        for agent_id, agent in self.agents.items():
            pos = agent.initial_position or {}
            # 查找最后的发言
            last_spoke = None
            for log in reversed(self.debate_log):
                if log["speaker"] == agent_id:
                    last_spoke = log
                    break
            last_pos = last_spoke.get("position", {}) if last_spoke else pos
            conclusion = last_pos.get("conclusion", pos.get("conclusion", "未明确"))
            parts.append(f"- {agent.name}：{conclusion}")
        return "\n".join(parts)

    def _build_round_2_3_instruction(self, briefing: str, round_num: int, agent_id: str, spoken: set, round_so_far: str) -> str:
        """为 Round 2/3 的发言者构建指令"""
        agent = self.agents[agent_id]

        # 找出该评委在前一轮的立场
        prev_round_logs = [log for log in self.debate_log if log["round"] == round_num]
        prev_text = "\n".join([f"[{log['speaker_name']}] {log['content'][:300]}" for log in prev_round_logs[-4:]])

        return f"""{briefing}

【第{round_num}轮 — 当前讨论记录】
{prev_text}

【你的任务】
你是{agent.name}。请基于你的专业角色，对前面的发言做出回应：
1. 对认同的观点表示支持，并补充你的视角
2. 对不同意的观点进行反驳，给出理由
3. 如需要某位评委回应具体问题，可以点名提问
4. 如果你的观点在本轮讨论中被修正了，请说明原因

请保持你的角色风格（{agent.role}），控制在200-400字。"""

    def _build_round_4_instruction(self, briefing: str, agent_id: str, spoken: set, round_so_far: str) -> str:
        """为 Round 4 自由辩论的发言者构建指令"""
        agent = self.agents[agent_id]

        return f"""{briefing}

【第4轮 — 自由辩论】
本轮已发言的评委：{spoken}

讨论记录：
{round_so_far[-2000:]}

【你的任务】
你是{agent.name}。这是自由辩论环节，你可以：
1. 回应之前评委对你的质疑
2. 补充你在前几轮遗漏的重要观点
3. 修正你的立场（如果你被说服了，请明确说"我修正之前的判断"）
4. 对即将到来的终审提出你的最后建议

请保持角色风格，控制在200-400字。"""

    def _parse_final_conclusion(self, text: str) -> dict:
        """解析牵头审批官的终审 JSON"""
        try:
            cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
            cleaned = re.sub(r"\s*```$", "", cleaned)
            return json.loads(cleaned)
        except json.JSONDecodeError:
            _safe_print("  [WARN] Final conclusion JSON parse failed, using fallback")
            return {
                "final_conclusion": "需要补充",
                "core_reasons": ["终审结论解析失败，请查看完整发言"],
                "risk_warnings": [],
                "recommended_credit": {},
                "judge_summary": {},
                "overall_assessment": text[:300],
                "raw_response": text,
            }

    def _compute_position_shifts(self) -> dict[str, dict]:
        """计算评委立场变化"""
        shifts = {}
        for agent_id, agent in self.agents.items():
            initial = agent.initial_position or {}
            # 找最后的发言立场
            final = initial.copy()
            for log in reversed(self.debate_log):
                if log["speaker"] == agent_id:
                    final = log.get("position", initial)
                    break

            initial_conclusion = initial.get("conclusion", "未明确")
            final_conclusion = final.get("conclusion", initial_conclusion)

            if initial_conclusion != final_conclusion:
                shifts[agent_id] = {
                    "agent_name": agent.name,
                    "initial": initial_conclusion,
                    "final": final_conclusion,
                    "shift": f"{initial_conclusion} → {final_conclusion}",
                }
            else:
                shifts[agent_id] = {
                    "agent_name": agent.name,
                    "initial": initial_conclusion,
                    "final": final_conclusion,
                    "shift": "未变化",
                }
        return shifts

    # ── 主入口 ────────────────────────────────────────────────────

    async def run(
        self, session_data: dict, on_progress: Callable[[dict], None] | None = None
    ) -> CommitteeResult:
        """执行完整的5轮贷审会辩论"""
        _safe_print("\n" + "█" * 60)
        _safe_print("  Phase 4: 模拟贷审会 — 多智能体辩论")
        _safe_print("█" * 60)
        _safe_print(f"  评委: {', '.join(a.short_name for a in self.agents.values())}")

        # 1. 构建简报
        briefing = self._build_briefing(session_data)
        _safe_print(f"  简报: {len(briefing)} chars")

        # 2. Round 1: 独立初审
        initial_positions = await self._run_round_1(briefing, on_progress)

        # 3. Round 2: 风险与合规
        await self._run_round_2(briefing, on_progress)

        # 4. Round 3: 行业与财务
        await self._run_round_3(briefing, on_progress)

        # 5. Round 4: 自由辩论
        await self._run_round_4(briefing, on_progress)

        # 6. Round 5: 终审
        final_conclusion = await self._run_round_5(briefing, on_progress)

        # 7. 收集最终立场
        final_positions: dict[str, dict] = {}
        for agent_id, agent in self.agents.items():
            final_positions[agent_id] = agent.initial_position.copy() if agent.initial_position else {}
            for log in reversed(self.debate_log):
                if log["speaker"] == agent_id:
                    final_positions[agent_id] = log.get("position", final_positions[agent_id])
                    break

        # 8. 计算立场变化
        position_shifts = self._compute_position_shifts()

        # 9. 构建结果
        result = CommitteeResult(
            briefing=briefing,
            initial_positions=initial_positions,
            debate_log=self.debate_log,
            final_positions=final_positions,
            final_conclusion=final_conclusion,
            position_shifts=position_shifts,
        )

        _safe_print("\n" + "█" * 60)
        _safe_print(f"  贷审会结束！终审结论: {final_conclusion.get('final_conclusion', '未明确')}")
        _safe_print(f"  立场变化: {sum(1 for s in position_shifts.values() if s['shift'] != '未变化')}/{len(position_shifts)} 位评委立场有调整")
        _safe_print("█" * 60 + "\n")

        return result


# ============================================================================
# 便捷函数
# ============================================================================

async def run_committee(
    session_data: dict,
    on_progress: Callable[[dict], None] | None = None,
    api_key: str | None = None,
) -> CommitteeResult:
    """执行 Phase 4 模拟贷审会"""
    orchestrator = CommitteeOrchestrator(api_key=api_key)
    return await orchestrator.run(session_data, on_progress)
