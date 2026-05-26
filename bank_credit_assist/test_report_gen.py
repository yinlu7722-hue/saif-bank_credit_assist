"""
test_report_gen.py — 单独测试报告生成环节（跳过 Phase1/Phase2/AI推理）
"""
import asyncio
import time
from pathlib import Path

from phase3_report import generate_report


def build_mock_data() -> dict:
    """构造模拟 Phase2 数据，覆盖报告全部10章"""

    enterprise_name = "中兴通讯技术股份有限公司"

    basic_info = {
        "company_name": enterprise_name,
        "unified_social_credit_code": "91440300100000000X",
        "legal_representative": "赵建国",
        "registered_capital": "50000万元人民币",
        "registration_date": "2008年05月15日",
        "business_scope": "通信设备研发、生产、销售及技术服务；信息系统集成；软件开发；技术进出口",
        "shareholder_structure": "赵建国持股35%，深圳中兴控股有限公司持股25%，员工持股平台持股15%",
        "actual_controller": "赵建国通过直接持股及一致行动人协议实际控制公司",
    }

    financial_metrics = {
        "enterprise_name": enterprise_name,
        "is_consolidated": True,
        "total_assets": 285000.0,
        "total_liabilities": 142500.0,
        "total_equity": 142500.0,
        "current_assets": 168000.0,
        "current_liabilities": 95000.0,
        "operating_revenue": 320000.0,
        "operating_cost": 224000.0,
        "total_profit": 48000.0,
        "net_profit": 40800.0,
        "operating_cash_flow": 35600.0,
        "investing_cash_flow": -18000.0,
        "financing_cash_flow": -5200.0,
        "debt_to_asset_ratio": 50.0,
        "debt_to_asset_ratio_calc": 50.0,
        "current_ratio": 1.768,
        "current_ratio_calc": 1.768,
        "quick_ratio": 1.35,
        "receivables_turnover_days": 85.0,
        "payables_turnover_days": 62.0,
        "inventory_turnover_days": 45.0,
        "sales_profit_margin": 12.75,
        "gross_margin": 30.0,
        "gross_margin_calc": 30.0,
        "rigid_liabilities": 65000.0,
        "cash_assets": 45000.0,
        "rigid_liability_net": 20000.0,
        "revenue_cagr": 18.5,
        "rd_expense_ratio": 8.2,
        "dupont_analysis": {
            "roe_pct": 28.6,
            "net_margin_pct": 12.75,
            "asset_turnover": 1.12,
            "equity_multiplier": 2.0,
        },
    }

    tech_metrics = {
        "high_tech_cert": {"value": "GR202344000123", "valid": True},
        "rd_expense_ratio": {"value": 8.2},
        "patent_count": 156,
        "team_size": 45,
        "core_team_size": 12,
    }

    inference_text = {
        # 一、申请人基本信息
        "main_products": "中兴通讯技术股份有限公司主营业务产品包括5G基站设备、核心网设备、光通信传输设备、企业级路由器及交换机、通信电源模块、以及通信系统集成服务。根据企业经营范围及财务报表推算，基站设备及传输设备贡献约60%的营业收入，为该公司核心产品线。",
        "actual_controller": "根据提供的公司章程及股权穿透分析，赵建国直接持有公司35%的股份，并通过一致行动人协议实际控制深圳中兴控股有限公司所持25%股份的表决权，合计控制60%的表决权，为公司的实际控制人。赵建国先生从事通信行业超过25年，具有丰富的行业管理经验。",
        "management_team_summary": "公司核心管理团队由7人组成，均具有15年以上通信行业从业经验。总经理赵建国为通信工程博士、教授级高级工程师，曾任国家863计划通信主题专家组成员。财务总监具备注册会计师资格，技术总监拥有多项核心专利。管理层团队结构合理，内部控制制度健全。",
        "group_introduction": "中兴通讯技术股份有限公司隶属于中兴控股集团，该集团下辖5家子公司，涵盖通信设备制造、系统集成、软件开发、国际贸易四大业务板块。集团2024年度合并营业收入约52亿元，净利润约6.5亿元，整体经营状况良好，盈利能力稳定。",
        # 二、申请人经营情况
        "business_model": "该公司属于典型的研发驱动型轻资产高科技企业，商业模式以自主研发+生产外包+直销为主。公司专注于通信设备的设计研发和系统集成，将标准化生产环节外包给专业代工厂，通过直销团队和渠道伙伴向电信运营商、政府及大型企业客户销售产品和解决方案。",
        "core_technology": "根据高新技术企业证书（GR202344000123）及财务报表研发费用推算，该公司核心技术集中在5G Massive MIMO天线技术、高速光模块设计、网络切片算法、通信设备热管理和电磁兼容设计五个领域。公司拥有156项授权专利，其中发明专利占比超过60%，核心技术具有较高的技术壁垒。",
        "operation_analysis": "公司采用'以销定产'的经营模式，销售人员获取订单后，由研发部门进行定制化设计，再交由合作代工厂进行标准化生产。盈利模式为'硬件销售+软件许可+技术服务费'三位一体，其中硬件销售占比约70%，技术服务费占比逐年提升至20%。",
        "capacity_output_summary": "根据所提供的财务报表推算，公司近三年产能利用率保持在85%-92%之间，处于行业合理水平。2024年度主要产品5G基站设备年产量约1.2万台，光传输设备年产量约8000套。公司在东莞和成都设有两个研发生产基地，总建筑面积约5万平方米。",
        "gross_margin_analysis": "根据所提供的财务报表推算，公司近三年毛利率分别为31.5%（2022年）、30.8%（2023年）、30.0%（2024年），呈小幅下降趋势，主要原因是行业竞争加剧及原材料成本上升。但毛利率仍高于通信设备行业均值25%，体现了公司在技术研发方面的竞争优势。",
        "current_orders_summary": "根据现有资料无法确定具体在手订单金额，建议实地调研补充。根据行业惯例及公司经营规模推算，预计在手订单约8-10亿元，主要客户为中国移动、中国电信、中国联通等三大运营商。",
        "major_investments": "根据所提供的财务报表推算，公司近两年重大投资包括：成都研发中心二期建设项目（总投资1.2亿元，已投入7000万元）、5G开放实验室建设项目（总投资5000万元，已完成）。无大规模并购活动，在建项目均按计划推进。",
        # 三、申请人财务状况
        "financial_metrics_summary": "根据所提供的财务报表推算，公司整体财务状况良好。盈利能力方面，营业收入保持18.5%的年复合增长率，销售利润率12.75%，ROE达28.6%，均优于行业平均水平。偿债能力方面，资产负债率50%处于合理区间，流动比率1.77，短期偿债能力充足。营运能力方面，应收账款周转天数85天、存货周转天数45天，均处于行业正常水平。",
        "financial_analysis_conclusion": "综合财务分析，中兴通讯技术股份有限公司财务状况健康。公司盈利能力较强且持续增长，偿债指标稳健，营运效率良好。现金流方面，经营性现金净流入3.56亿元，投资性现金净流出1.8亿元，融资性现金净流出5200万元，整体现金流结构合理。财务风险较低，具备偿还新增授信的能力。",
        # 四、申请人信用状况
        "overall_credit_status": "根据现有资料无法确定企业征信报告具体情况，建议实地调研补充。根据企业提供的基本信息及经营情况推断，该公司作为高新技术企业，经营历史超过15年，注册资本5亿元，资产规模28.5亿元，整体信用状况应处于较好水平。",
        "bank_financing": "根据所提供的财务报表推算，公司短期借款余额约2.5亿元，长期借款余额约4亿元，合计银行融资约6.5亿元。主要合作银行包括工商银行、建设银行和中国银行，授信品种以流动资金贷款和固定资产贷款为主，融资结构以长期借款为主，期限匹配较为合理。",
        # 五、行业地位比较分析
        "industry_position": "根据所提供的财务指标与行业均值比较，中兴通讯技术股份有限公司在通信设备行业中处于中上游水平。营业收入32亿元，超过行业75分位数；销售利润率12.75%，超过行业中位数（约8%）；研发费用占比8.2%，远高于行业均值（约4.5%）。在5G基站设备细分领域，公司市场份额约12%，排名行业前五。",
        "competitive_advantages": "公司核心竞争优势包括：（1）技术研发优势——156项专利、8.2%研发投入占比为行业领先水平；（2）客户资源优势——与三大运营商建立长期稳定合作关系；（3）人才优势——核心技术团队45人，行业经验丰富；（4）资质优势——高新技术企业认证，具备军品科研生产相关资质。",
        "competitive_disadvantages": "公司面临的竞争劣势包括：（1）规模劣势——与华为、中兴通讯（股份）等行业龙头相比，营收规模仅为龙头企业的5%-8%，规模效应不足；（2）品牌劣势——在国际市场品牌知名度较低，海外业务占比不足8%；（3）成本劣势——因采购规模有限，上游议价能力低于行业龙头企业。",
        "industry_trend": "通信设备行业当前处于5G建设中后期向6G预研过渡阶段，行业生命周期处于成熟期。市场结构呈寡头竞争格局，华为、中兴（股份）占据约60%市场份额。未来五年行业增长驱动因素包括：5G-A网络升级、算力网络建设、工业互联网应用深化。预计行业复合增长率维持在8%-12%之间。",
        "price_trend": "近三年主要原材料价格走势：芯片类（FPGA、DSP）价格因全球供应链紧张呈现5%-10%的温和上涨；PCB板材价格基本稳定；铝型材、铜材等金属材料价格波动较大，2024年同比上涨约8%。产成品价格方面，5G基站设备单价年均降幅约5%-8%，符合通信设备行业摩尔定律规律。",
        # 六、其他重要事项
        "litigation_events": '[{"category":"合同纠纷","description":"与北京恒通科技有限公司就设备采购合同产生争议，涉案金额约350万元","amount":350,"date":"2024-09","impact":"待法院判决","status":"审理中"},{"category":"知识产权","description":"公司作为原告提起专利侵权诉讼，主张被告侵犯其5G天线相关专利权","amount":1200,"date":"2024-11","impact":"若胜诉将形成技术壁垒","status":"已立案"}]',
        # 七、授信用途及还款来源
        "credit_usage": "根据企业经营情况推断，本次申请授信主要用于补充流动资金和扩大生产规模。具体用途包括：采购通信芯片及电子元器件备货（约60%），支付代工厂生产加工费用（约25%），研发投入及人员薪酬支出（约15%）。",
        "credit_usage_analysis": "授信用途合理性分析：公司2024年度营业收入32亿元，按行业惯例流动资金缺口约为月均营收的2-3倍即5-8亿元，申请流动资金贷款用于补充经营周转具有合理性。采购备货对象均为长期合作供应商，交易背景真实。授信资金用途与公司经营规模和业务模式相匹配，用途真实合规。",
        "repayment_source": "根据所提供的财务报表推算，公司主要还款来源为经营性现金流入。2024年度经营性现金净流入3.56亿元，按授信金额1亿元的30%安全边际计算，经营性现金流可完全覆盖到期还款。辅助还款来源包括应收账款回收（应收账款余额约7.5亿元）和存量货币资金（约4.5亿元）。",
        "repayment_method": "根据现有资料无法确定具体还款方式，待与客户协商确定。建议采用按月付息、到期还本的方式，或根据企业现金流特点设计按季付息、分期还本的个性化方案。",
        # 八、担保情况
        "collateral_pledge": "根据所提供的财务报表推算，可用于抵押的资产包括：固定资产（厂房及设备）账面价值约1.8亿元、土地使用权约5000万元、应收账款约7.5亿元（可按50%-70%质押率办理保理或质押）。存货约4.2亿元，其中产成品约2.5亿元可按60%质押率办理仓单质押。",
        "guarantee_evaluation": "担保综合评价：企业可提供足值抵质押物，抵押物价值合计约3.5亿元（不含应收账款），抵质押率约28.6%，担保充足性良好。同时建议追加实际控制人赵建国个人连带责任保证，形成'资产抵质押+个人保证'的复合担保结构，进一步增强风险缓释效果。",
        # 九、授信收益与风险分析
        "return_analysis": "根据所提供的财务指标和模拟利率计算，本次授信预期收益分析如下：贷款金额1亿元，按年利率4.5%计算年利息收入450万元。同时可带动存款沉淀（预计日均存款约2000万元）、国际结算（年结算量约5000万元）、代发工资等综合收益约180万元/年，综合年化收益率约6.3%，收益水平符合银行对公信贷业务考核要求。",
        "risk_evaluation": "综合风险评价：（1）经营风险——行业竞争加剧可能导致毛利率进一步下行，但公司技术壁垒较高，风险可控；（2）财务风险——资产负债率50%健康，流动比率充足，财务风险较低；（3）市场风险——5G建设进入成熟期，但5G-A升级和算力网络建设带来新增量；（4）信用风险——企业征信情况待确认，建议补充查询；（5）担保风险——抵质押物价值充足，担保风险较低。",
        "risk_level": "中低风险（R2级）",
        "risk_mitigation_measures": "风险缓释措施建议：（1）办理应收账款质押登记，锁定主要下游客户回款账户；（2）追加实际控制人个人连带责任保证；（3）在贷款合同中约定财务约束条款（资产负债率不超过65%、流动比率不低于1.2）；（4）按季进行贷后检查，重点关注应收账款回收和毛利率变动；（5）建议分两笔发放，首笔5000万元，待贷后检查正常后发放剩余额度。",
        # 十、授信调查结论和授信方案
        "investigation_conclusion": "综合十方面分析，中兴通讯技术股份有限公司作为通信设备行业高新技术企业，经营状况良好，财务指标健康，研发实力突出，具备按期偿还贷款本息的能力。公司实际控制人清晰，管理层经验丰富，行业前景向好。主要风险点在于行业竞争加剧可能影响毛利率水平，建议通过担保措施和财务约束条款进行风险缓释。总体评价：符合银行对公信贷准入标准，建议予以授信支持。",
        "reported_opinion": "建议予以授信审批。推荐授信金额1亿元，期限36个月，利率不低于同期LPR上浮50BP，担保方式为'固定资产抵押+应收账款质押+实际控制人连带责任保证'。首批发放5000万元，贷后6个月检查正常后发放剩余额度。",
        "recommended_credit_type": "流动资金贷款",
        "recommended_credit_amount": "10000万元（人民币壹亿元整）",
        "recommended_term": "36个月",
        "recommended_guarantee": "固定资产抵押+应收账款质押+实际控制人赵建国个人连带责任保证",
        # 结构化字段
        "upstream_suppliers": '[{"name":"深圳华为技术有限公司","amount":12000,"ratio":28.5,"product":"通信芯片及模块","years":8,"payment":"月结60天","relation":"战略合作","remark":"核心供应商"},{"name":"中芯国际集成电路制造有限公司","amount":8500,"ratio":20.2,"product":"定制芯片","years":5,"payment":"月结45天","relation":"框架协议","remark":"单一来源"},{"name":"鹏鼎控股（深圳）股份有限公司","amount":5200,"ratio":12.3,"product":"PCB印制电路板","years":10,"payment":"月结30天","relation":"长期合作","remark":"多家比价"}]',
        "downstream_customers": '[{"name":"中国移动通信集团有限公司","amount":95000,"ratio":29.7,"product":"5G基站设备及运维","years":12,"payment":"发票日后90天","relation":"战略客户","remark":"框架招标"},{"name":"中国电信集团有限公司","amount":78000,"ratio":24.4,"product":"光传输及接入设备","years":10,"payment":"发票日后90天","relation":"战略客户","remark":"集采入围"},{"name":"中国联合网络通信集团有限公司","amount":52000,"ratio":16.3,"product":"核心网及传输设备","years":8,"payment":"发票日后90天","relation":"战略客户","remark":"区域供应商"}]',
    }

    income_verification = {
        "report_revenue": 320000.0,
        "bank_inflow": 295000.0,
        "tax_revenue": 310000.0,
        "bank_deviation_pct": 7.8,
        "tax_deviation_pct": 3.1,
        "bank_result": "偏差7.8%，在可接受范围内",
        "tax_result": "偏差3.1%，高度一致",
        "conclusion": "收入交叉核验：财务报表收入32亿元与纳税申报收入31亿元偏差3.1%，与银行流水贷方发生额29.5亿元偏差7.8%，三者数据基本吻合，财务报表收入真实性较高。银行流水偏差主要因部分大额回款跨期入账，属于正常时间性差异。",
    }

    guarantee_types = ["legal", "collateral"]

    annual_indicators = {
        2022: {
            "debt_to_asset_ratio": 48.5,
            "current_ratio": 1.82,
            "quick_ratio": 1.40,
            "receivables_turnover_days": 78.0,
            "payables_turnover_days": 58.0,
            "inventory_turnover_days": 42.0,
            "sales_profit_margin": 13.5,
            "gross_margin": 31.5,
            "rigid_liabilities": 55000.0,
            "cash_assets": 38000.0,
            "rigid_liability_net": 17000.0,
        },
        2023: {
            "debt_to_asset_ratio": 49.2,
            "current_ratio": 1.80,
            "quick_ratio": 1.38,
            "receivables_turnover_days": 82.0,
            "payables_turnover_days": 60.0,
            "inventory_turnover_days": 44.0,
            "sales_profit_margin": 13.1,
            "gross_margin": 30.8,
            "rigid_liabilities": 60000.0,
            "cash_assets": 42000.0,
            "rigid_liability_net": 18000.0,
        },
        2024: {
            "debt_to_asset_ratio": 50.0,
            "current_ratio": 1.77,
            "quick_ratio": 1.35,
            "receivables_turnover_days": 85.0,
            "payables_turnover_days": 62.0,
            "inventory_turnover_days": 45.0,
            "sales_profit_margin": 12.75,
            "gross_margin": 30.0,
            "rigid_liabilities": 65000.0,
            "cash_assets": 45000.0,
            "rigid_liability_net": 20000.0,
        },
    }

    markdown_content = """
## 资产负债表（合并）

| 项目 | 2024年 | 2023年 | 2022年 |
|------|--------|--------|--------|
| 流动资产 | 168,000 | 155,000 | 138,000 |
| 非流动资产 | 117,000 | 108,000 | 95,000 |
| 资产总计 | 285,000 | 263,000 | 233,000 |
| 流动负债 | 95,000 | 86,000 | 76,000 |
| 非流动负债 | 47,500 | 42,500 | 37,000 |
| 负债合计 | 142,500 | 128,500 | 113,000 |
| 所有者权益 | 142,500 | 134,500 | 120,000 |

## 利润表（合并）

| 项目 | 2024年 | 2023年 | 2022年 |
|------|--------|--------|--------|
| 营业收入 | 320,000 | 270,000 | 228,000 |
| 营业成本 | 224,000 | 186,800 | 156,200 |
| 利润总额 | 48,000 | 42,000 | 35,000 |
| 净利润 | 40,800 | 35,700 | 29,750 |

## 现金流量表（合并）

| 项目 | 2024年 | 2023年 | 2022年 |
|------|--------|--------|--------|
| 经营性净现金流 | 35,600 | 31,200 | 26,500 |
| 投资性净现金流 | -18,000 | -15,500 | -12,000 |
| 融资性净现金流 | -5,200 | 3,800 | -8,500 |
"""

    return {
        "enterprise_name": enterprise_name,
        "basic_info": basic_info,
        "financial_metrics": financial_metrics,
        "tech_metrics": tech_metrics,
        "inference_text": inference_text,
        "income_verification": income_verification,
        "guarantee_types": guarantee_types,
        "annual_indicators": annual_indicators,
        "markdown_content": markdown_content,
    }


async def main():
    data = build_mock_data()
    output_path = Path(__file__).parent / "output" / f"测试报告_{int(time.time())}.docx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("开始生成测试报告...")
    t0 = time.time()

    await generate_report(
        enterprise_name=data["enterprise_name"],
        basic_info=data["basic_info"],
        financial_metrics=data["financial_metrics"],
        tech_metrics=data["tech_metrics"],
        inference_text=data["inference_text"],
        income_verification=data["income_verification"],
        guarantee_types=data["guarantee_types"],
        markdown_content=data["markdown_content"],
        output_path=output_path,
        annual_indicators=data["annual_indicators"],
    )

    elapsed = time.time() - t0
    size_kb = output_path.stat().st_size / 1024
    print(f"报告已生成: {output_path}")
    print(f"文件大小: {size_kb:.1f} KB")
    print(f"耗时: {elapsed:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
