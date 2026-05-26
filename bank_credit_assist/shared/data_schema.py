"""
shared/data_schema.py
Pydantic 数据模型
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any, Optional


class DataSource(BaseModel):
    """数据溯源字段（所有财务数据/风险结论必须包含）"""
    source_file: str = Field(description="信息来源文件名，如'2023年度审计报告.pdf'")
    source_location: str | None = Field(default=None, description="文件中位置，如'第3个表格'")
    confidence_score: float = Field(ge=0.0, le=1.0, description="数据置信度，0.0-1.0")


class CompanyBasicInfo(BaseModel):
    """一、申请人基本信息"""
    company_name: str = Field(description="企业名称")
    unified_social_credit_code: str = Field(description="统一社会信用代码")
    legal_representative: str = Field(description="法定代表人")
    registered_capital: str = Field(description="注册资本")
    registration_date: str = Field(description="注册日期")
    business_scope: str = Field(description="经营范围")
    main_products: list[str] = Field(default_factory=list, description="主营业务产品")
    shareholder_structure: list[dict] = Field(default_factory=list, description="股东结构")
    actual_controller: str | None = Field(default=None, description="实际控制人")
    data_source: DataSource | None = Field(default=None)


class BusinessAnalysis(BaseModel):
    """二、申请人经营情况"""
    business_model: str = Field(description="经营模式概述")
    upstream_suppliers: list[dict] = Field(default_factory=list, description="上游供应商情况")
    downstream_customers: list[dict] = Field(default_factory=list, description="下游销售商情况")
    core_technology: str | None = Field(default=None, description="核心技术描述")
    high_tech_certificate: str | None = Field(default=None, description="高新技术证书有效期")
    rd_expense_ratio: str | None = Field(default=None, description="研发费用占比")
    core_team_size: int | None = Field(default=None, description="核心技术团队人数")
    data_source: DataSource | None = Field(default=None)


class FinancialAnalysis(BaseModel):
    """三、申请人财务状况"""
    balance_sheet_summary: dict = Field(description="资产负债表摘要（关键科目）")
    income_statement_summary: dict = Field(description="损益表摘要（关键科目）")
    cash_flow_summary: dict = Field(description="现金流量表摘要（关键科目）")
    financial_metrics: dict = Field(description="财务指标计算结果")
    revenue_verification: dict = Field(description="收入核实情况")
    data_source: DataSource | None = Field(default=None)


class CreditStatus(BaseModel):
    """四、申请人信用状况"""
    overall_credit_status: str = Field(description="总体信用情况")
    bank_financing: list[dict] = Field(default_factory=list, description="银行融资情况")
    bonds_outstanding: list[dict] = Field(default_factory=list, description="存续债券情况")
    non_standard_financing: list[dict] = Field(default_factory=list, description="非标融资情况")
    external_guarantees: list[dict] = Field(default_factory=list, description="对外担保余额")
    data_source: DataSource | None = Field(default=None)


class IndustryAnalysis(BaseModel):
    """五、行业地位比较分析"""
    industry_position: str = Field(description="行业地位描述")
    market_share: str | None = Field(default=None, description="市场份额")
    competitive_advantages: list[str] = Field(default_factory=list, description="竞争优势")
    competitive_disadvantages: list[str] = Field(default_factory=list, description="竞争劣势")
    data_source: DataSource | None = Field(default=None)


class OtherImportantMatters(BaseModel):
    """六、其他重要事项"""
    litigation_status: list[dict] = Field(default_factory=list, description="诉讼情况")
    negative_news: list[str] = Field(default_factory=list, description="重大负面消息")
    other_matters: list[str] = Field(default_factory=list, description="其他重要事项")
    data_source: DataSource | None = Field(default=None)


class CreditUsageRepayment(BaseModel):
    """七、授信用途及还款来源"""
    credit_usage: str = Field(description="授信资金用途")
    repayment_source: str = Field(description="还款来源分析")
    repayment_method: str = Field(description="还款方式分析")
    data_source: DataSource | None = Field(default=None)


class GuaranteeInfo(BaseModel):
    """八、担保情况"""
    legal_guarantee: list[dict] = Field(default_factory=list, description="法人保证担保")
    collateral_pledge: list[dict] = Field(default_factory=list, description="抵质押担保")
    natural_person_guarantee: list[dict] = Field(default_factory=list, description="自然人保证担保")
    guarantee_evaluation: str = Field(description="担保综合评价")
    data_source: DataSource | None = Field(default=None)


class RiskReturnAnalysis(BaseModel):
    """九、授信收益与风险分析"""
    return_analysis: str = Field(description="收益分析")
    risk_evaluation: str = Field(description="风险评价")
    risk_level: str = Field(description="风险等级（低/中/高）")
    risk_mitigation_measures: list[str] = Field(default_factory=list, description="风险缓释措施")
    data_source: DataSource | None = Field(default=None)


class ConclusionRecommendation(BaseModel):
    """十、授信调查结论和授信方案"""
    investigation_conclusion: str = Field(description="调查结论")
    reported_opinion: str = Field(description="上报意见")
    recommended_credit_type: str | None = Field(default=None, description="建议授信品种")
    recommended_credit_amount: str | None = Field(default=None, description="建议授信金额")
    recommended_term: str | None = Field(default=None, description="建议授信期限")
    recommended_guarantee: str | None = Field(default=None, description="建议担保方式")
    data_source: DataSource | None = Field(default=None)


class ReportChapter(BaseModel):
    """单个报告章节"""
    chapter_name: str = Field(description="章节名称")
    chapter_number: int = Field(description="章节编号（1-10）")
    content: dict = Field(description="章节内容（对应Pydantic模型）")
    generation_status: str = Field(default="pending", description="生成状态：pending/success/failed")
    error_message: str | None = Field(default=None)


class FinalReport(BaseModel):
    """完整报告结构"""
    enterprise_name: str = Field(description="企业名称")
    report_date: str = Field(description="报告生成日期")
    overall_risk_level: str = Field(description="综合风险等级")
    chapters: list[ReportChapter] = Field(default_factory=list)
    compliance_status: str = Field(description="合规状态：PASS/WARNING/FAIL/REQUIRES_MANUAL")
    manual_verify_items: list[str] = Field(default_factory=list, description="需人工内网核验项")


# ============================================================================
# 统一资料清单（server.py 和 app_streamlit.py 共用）
# ============================================================================

from enum import Enum


class DocumentLevel(str, Enum):
    REQUIRED = "required"
    SUGGESTED = "suggested"
    IF_EXISTS = "if_exists"
    CONDITIONAL = "conditional"


UNIFIED_DOCUMENT_LIST: list[dict] = [
    # A 类 — 主体资格
    {"code": "A1", "name": "营业执照（正副本）", "category": "A", "level": "required", "accepted_types": [".pdf", ".jpg", ".jpeg", ".png"], "hint": "最新版，正副本均需"},
    {"code": "A2", "name": "法定代表人身份证", "category": "A", "level": "required", "accepted_types": [".pdf", ".jpg", ".jpeg", ".png"], "hint": "正反面复印件"},
    {"code": "A3", "name": "公司章程", "category": "A", "level": "suggested", "accepted_types": [".pdf"], "hint": "最新版"},
    {"code": "A4", "name": "验资报告", "category": "A", "level": "if_exists", "accepted_types": [".pdf"], "hint": "如有则提供"},
    {"code": "A5", "name": "股权树状图", "category": "A", "level": "if_exists", "accepted_types": [".pdf", ".jpg", ".jpeg", ".png"], "hint": "向上穿透至最终实际控制人"},
    # B 类 — 财务资料
    {"code": "B1", "name": "财务报表（近三年+最新一期）", "category": "B", "level": "required", "accepted_types": [".pdf", ".xlsx", ".xls", ".xlsm"], "hint": "资产负债表、利润表、现金流量表"},
    {"code": "B2", "name": "银行流水（12个月）", "category": "B", "level": "required", "accepted_types": [".pdf", ".xlsx", ".xls"], "hint": "主要银行账户交易流水"},
    {"code": "B3", "name": "纳税申报表（近一年）", "category": "B", "level": "suggested", "accepted_types": [".pdf", ".xlsx", ".xls"], "hint": "增值税、企业所得税纳税申报表及完税凭证"},
    {"code": "B4", "name": "银行授信清单", "category": "B", "level": "suggested", "accepted_types": [".pdf", ".xlsx", ".xls"], "hint": "列明所有尚未结清的融资负债及担保条件"},
    # C 类 — 经营佐证
    {"code": "C1", "name": "经营场所证明", "category": "C", "level": "suggested", "accepted_types": [".pdf", ".jpg", ".jpeg", ".png"], "hint": "产权证明或租赁合同+近期租金支付凭证"},
    {"code": "C2", "name": "上下游交易佐证", "category": "C", "level": "suggested", "accepted_types": [".pdf", ".xlsx", ".xls"], "hint": "前五大供应商/销售商购销数据、合同、发票"},
    {"code": "C3", "name": "进出口单据", "category": "C", "level": "if_exists", "accepted_types": [".pdf"], "hint": "报关单、海关单据"},
    {"code": "C4", "name": "在手订单/合同", "category": "C", "level": "suggested", "accepted_types": [".pdf"], "hint": "重大已签署合同及可行性研究报告"},
    # D 类 — 科技属性
    {"code": "D1", "name": "高新技术企业证书", "category": "D", "level": "suggested", "accepted_types": [".pdf", ".jpg", ".jpeg", ".png"], "hint": "科技型企业核心资质"},
    {"code": "D2", "name": "知识产权/专利清单", "category": "D", "level": "suggested", "accepted_types": [".pdf"], "hint": "核心发明专利、实用新型专利、软件著作权"},
    {"code": "D3", "name": "研发费用明细账", "category": "D", "level": "suggested", "accepted_types": [".pdf", ".xlsx", ".xls"], "hint": "近三年研发费用明细或辅助账册"},
    {"code": "D4", "name": "核心技术团队履历", "category": "D", "level": "suggested", "accepted_types": [".pdf", ".jpg", ".jpeg", ".png"], "hint": "主要管理层人员详细工作履历"},
    # G 类 — 担保资料（条件触发）
    {"code": "G1", "name": "法人担保资料", "category": "G", "level": "conditional", "accepted_types": [".pdf"], "hint": "法人保证人相关材料"},
    {"code": "G2", "name": "抵质押物资料", "category": "G", "level": "conditional", "accepted_types": [".pdf"], "hint": "抵质押物权属及评估材料"},
    {"code": "G3", "name": "自然人担保资料", "category": "G", "level": "conditional", "accepted_types": [".pdf"], "hint": "自然人保证人相关材料"},
]

UNIFIED_REQUIRED_CODES: set[str] = {"A1", "A2", "B1", "B2"}
UNIFIED_EXCEL_EXTENSIONS: set[str] = {".xls", ".xlsx", ".xlsm"}
UNIFIED_TEXT_EXTENSIONS: set[str] = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".jpg", ".jpeg", ".png", ".html", ".htm"}
