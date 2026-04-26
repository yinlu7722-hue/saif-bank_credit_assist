"""
phase2_compliance.py
Phase 2 — 合规筛查模块
由于内网隔离限制，标注需人工核验项，实际筛查逻辑预留接口
【核心更新 v3.0】
- 双维度筛查：企业 + 实际控制人/核心高管
- 数据溯源字段：source_file, confidence_score
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from enum import Enum


# ============================================================================
# 数据结构
# ============================================================================

class CheckDimension(str, Enum):
    """筛查维度"""
    ENTERPRISE = "enterprise"          # 企业维度
    ACTUAL_CONTROLLER = "actual_controller"  # 实际控制人维度
    CORE_EXECUTIVE = "core_executive"        # 核心高管维度


class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ComplianceCheckResult:
    """
    单条筛查结果（含数据溯源）
    所有字段必须包含 source_file 和 confidence_score，
    以确保可追溯性。
    """
    name: str                                   # 筛查项名称
    dimension: CheckDimension                    # 筛查维度
    result: str  # PASS / WARNING / FAIL / REQUIRES_MANUAL
    details: str                                # 详细说明
    requires_manual_verify: bool                 # 是否需人工内网核验
    source_file: str | None = None             # 数据来源文件
    source_location: str | None = None         # 文件内位置
    confidence_score: float = 1.0               # 置信度 0.0-1.0
    risk_level: RiskLevel = RiskLevel.LOW       # 风险等级

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dimension"] = self.dimension.value
        d["risk_level"] = self.risk_level.value
        return d


@dataclass
class SubjectInfo:
    """筛查主体信息（企业/实际控制人/核心高管）"""
    name: str
    id_type: str | None = None   # 证件类型（身份证/统一社会信用代码）
    id_number: str | None = None # 证件号码
    role: str | None = None       # 角色（法人/实控人/总经理/技术总监等）


# ============================================================================
# 合规筛查引擎
# ============================================================================

class ComplianceScreener:
    """
    合规筛查引擎 v3.0
    【核心特性】
    1. 双维度筛查：企业 + 实际控制人/核心高管
    2. 数据溯源：每条结果附带 source_file, confidence_score
    3. 内网隔离：敏感项标注 REQUIRES_MANUAL，引导人工核验
    """

    def __init__(self) -> None:
        self.name = "合规筛查模块 v3.0"

    async def run_checks(self, enterprise_data: dict) -> dict:
        """
        执行全量合规筛查（企业 + 双维度）
        """
        # 提取筛查主体
        enterprise_name: str = enterprise_data.get("enterprise_name", "未知")
        actual_controller: str | None = enterprise_data.get("actual_controller")
        core_executives: list[str] = enterprise_data.get("core_executives", [])

        # ── 企业维度筛查 ──
        enterprise_checks: list[ComplianceCheckResult] = [
            await self._check_aml_list_enterprise(enterprise_name),
            await self._check_sanctions_list_enterprise(enterprise_name),
            await self._check_litigation_enterprise(enterprise_name),
            await self._check_business_license(enterprise_name),
            await self._check_environmental_compliance(enterprise_name),
        ]

        # ── 个人维度筛查（实际控制人 + 核心高管）──
        person_checks: list[ComplianceCheckResult] = []

        if actual_controller:
            person_checks.extend([
                await self._check_aml_list_person(actual_controller, "实际控制人"),
                await self._check_sanctions_list_person(actual_controller, "实际控制人"),
                await self._check_litigation_person(actual_controller, "实际控制人"),
                await self._check_negative_news_person(actual_controller, "实际控制人"),
            ])

        for exec_name in core_executives:
            person_checks.extend([
                await self._check_litigation_person(exec_name, "核心高管"),
                await self._check_negative_news_person(exec_name, "核心高管"),
            ])

        # ── 综合判断 ──
        all_checks: list[ComplianceCheckResult] = enterprise_checks + person_checks
        has_fail = any(c.result == "FAIL" for c in all_checks)
        has_high_risk = any(c.risk_level == RiskLevel.HIGH for c in all_checks)
        has_critical = any(c.risk_level == RiskLevel.CRITICAL for c in all_checks)
        has_warning = any(c.result == "WARNING" for c in all_checks)
        has_manual = any(c.requires_manual_verify for c in all_checks)

        if has_critical or has_fail:
            overall = "FAIL"
        elif has_high_risk:
            overall = "WARNING"
        elif has_warning:
            overall = "WARNING"
        elif has_manual:
            overall = "REQUIRES_MANUAL"
        else:
            overall = "PASS"

        # ── 风险汇总 ──
        risk_summary: dict[str, Any] = {
            "enterprise_risk_count": {
                "fail": sum(1 for c in enterprise_checks if c.result == "FAIL"),
                "warning": sum(1 for c in enterprise_checks if c.result == "WARNING"),
                "requires_manual": sum(1 for c in enterprise_checks if c.requires_manual_verify),
            },
            "person_risk_count": {
                "fail": sum(1 for c in person_checks if c.result == "FAIL"),
                "warning": sum(1 for c in person_checks if c.result == "WARNING"),
                "requires_manual": sum(1 for c in person_checks if c.requires_manual_verify),
            },
            "high_risk_items": [
                {"name": c.name, "dimension": c.dimension.value, "details": c.details}
                for c in all_checks if c.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
            ],
        }

        return {
            "overall": overall,
            "manual_verify_required": has_manual,
            "enterprise_checks": [c.to_dict() for c in enterprise_checks],
            "person_checks": [c.to_dict() for c in person_checks],
            "risk_summary": risk_summary,
        }

    # =========================================================================
    # 企业维度筛查
    # =========================================================================

    async def _check_aml_list_enterprise(self, name: str) -> ComplianceCheckResult:
        """企业反洗钱名单筛查"""
        return ComplianceCheckResult(
            name="企业反洗钱名单筛查",
            dimension=CheckDimension.ENTERPRISE,
            result="REQUIRES_MANUAL",
            details=f"企业名称：{name}，需在人民银行反洗钱系统查询",
            requires_manual_verify=True,
            source_file=None,
            confidence_score=0.0,
            risk_level=RiskLevel.HIGH,
        )

    async def _check_sanctions_list_enterprise(self, name: str) -> ComplianceCheckResult:
        """企业国际制裁名单筛查"""
        return ComplianceCheckResult(
            name="企业国际制裁名单筛查（OFAC/FATF）",
            dimension=CheckDimension.ENTERPRISE,
            result="REQUIRES_MANUAL",
            details=f"企业名称：{name}，需在OFAC/FATF名单系统查询",
            requires_manual_verify=True,
            source_file=None,
            confidence_score=0.0,
            risk_level=RiskLevel.CRITICAL,
        )

    async def _check_litigation_enterprise(self, name: str) -> ComplianceCheckResult:
        """企业诉讼及被执行人筛查（返回模拟数据）"""
        return ComplianceCheckResult(
            name="企业诉讼及被执行人筛查",
            dimension=CheckDimension.ENTERPRISE,
            result="WARNING",
            details="根据公开信息检索，发现存在1起合同纠纷诉讼（标的200万元），需人工核实",
            requires_manual_verify=True,
            source_file="企查查公开数据（模拟）",
            source_location="企业诉讼记录",
            confidence_score=0.60,
            risk_level=RiskLevel.MEDIUM,
        )

    async def _check_business_license(self, name: str) -> ComplianceCheckResult:
        """营业执照有效性检查（返回模拟数据）"""
        return ComplianceCheckResult(
            name="营业执照有效性检查",
            dimension=CheckDimension.ENTERPRISE,
            result="PASS",
            details="营业执照有效期至2029年，当前状态正常",
            requires_manual_verify=False,
            source_file="工商登记信息（模拟）",
            source_location="企业基本信息",
            confidence_score=0.85,
            risk_level=RiskLevel.LOW,
        )

    async def _check_environmental_compliance(self, name: str) -> ComplianceCheckResult:
        """环保合规筛查（科技型企业需关注）"""
        return ComplianceCheckResult(
            name="环保合规筛查",
            dimension=CheckDimension.ENTERPRISE,
            result="PASS",
            details="未发现环保处罚记录",
            requires_manual_verify=False,
            source_file="环保处罚公示数据（模拟）",
            source_location="行政处罚记录",
            confidence_score=0.80,
            risk_level=RiskLevel.LOW,
        )

    # =========================================================================
    # 个人维度筛查（实际控制人 + 核心高管）
    # =========================================================================

    async def _check_aml_list_person(
        self, person_name: str, role: str
    ) -> ComplianceCheckResult:
        """个人反洗钱名单筛查"""
        return ComplianceCheckResult(
            name=f"{role}反洗钱名单筛查",
            dimension=CheckDimension.ACTUAL_CONTROLLER if role == "实际控制人" else CheckDimension.CORE_EXECUTIVE,
            result="REQUIRES_MANUAL",
            details=f"{role}：{person_name}，需在人民银行系统查询",
            requires_manual_verify=True,
            source_file=None,
            confidence_score=0.0,
            risk_level=RiskLevel.HIGH,
        )

    async def _check_sanctions_list_person(
        self, person_name: str, role: str
    ) -> ComplianceCheckResult:
        """个人国际制裁名单筛查"""
        return ComplianceCheckResult(
            name=f"{role}国际制裁名单筛查",
            dimension=CheckDimension.ACTUAL_CONTROLLER if role == "实际控制人" else CheckDimension.CORE_EXECUTIVE,
            result="REQUIRES_MANUAL",
            details=f"{role}：{person_name}，需在OFAC/FATF名单系统查询",
            requires_manual_verify=True,
            source_file=None,
            confidence_score=0.0,
            risk_level=RiskLevel.CRITICAL,
        )

    async def _check_litigation_person(
        self, person_name: str, role: str
    ) -> ComplianceCheckResult:
        """个人诉讼/被执行人筛查（返回模拟数据）"""
        return ComplianceCheckResult(
            name=f"{role}诉讼及被执行人筛查",
            dimension=CheckDimension.ACTUAL_CONTROLLER if role == "实际控制人" else CheckDimension.CORE_EXECUTIVE,
            result="WARNING",
            details=f"{role}：{person_name}，发现1起民间借贷纠纷（已结案），建议关注",
            requires_manual_verify=True,
            source_file="中国执行信息公开网（模拟）",
            source_location="被执行人记录",
            confidence_score=0.65,
            risk_level=RiskLevel.MEDIUM,
        )

    async def _check_negative_news_person(
        self, person_name: str, role: str
    ) -> ComplianceCheckResult:
        """个人负面舆情筛查（返回模拟数据）"""
        return ComplianceCheckResult(
            name=f"{role}负面舆情筛查",
            dimension=CheckDimension.ACTUAL_CONTROLLER if role == "实际控制人" else CheckDimension.CORE_EXECUTIVE,
            result="PASS",
            details=f"{role}：{person_name}，未发现重大负面舆情",
            requires_manual_verify=False,
            source_file="新闻舆情数据（模拟）",
            source_location="负面新闻记录",
            confidence_score=0.70,
            risk_level=RiskLevel.LOW,
        )
