"""
app.py
对公信贷智能化辅助系统 — 完整工作流 Web UI（v4.0 商务蓝重构版）
资料上传 → Phase1解析 → Phase2分析 → 人工核对结构化数据 → Phase3报告生成
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

import streamlit as st
import nest_asyncio

# 解决 Streamlit 异步线程冲突
nest_asyncio.apply()

# ============================================================================
# 恢复了所有的后端业务导入
# 如果您本地还没有这些文件，请确保它们存在，或者在测试纯UI时将其注释掉
# ============================================================================
from shared.mineru_client import clean_mineru_markdown
from phase1_parser import phase1_parse_documents, parse_excel_locally
from phase2_analysis import run_financial_analysis, extract_tech_innovation_metrics
from phase2_compliance import ComplianceScreener
from phase3_report import generate_report, FinalReport


# ============================================================================
# 资料清单数据结构
# ============================================================================

class DocumentLevel(str, Enum):
    REQUIRED = "required"
    SUGGESTED = "suggested"
    IF_EXISTS = "if_exists"

@dataclass
class RequiredDocument:
    code: str
    name: str
    category: str
    level: DocumentLevel
    accepted_types: list[str]
    hint: str = ""

DOCUMENT_LIST: list[RequiredDocument] = [
    # 类别A：基础资质与法务合规类（6项）
    RequiredDocument("A1", "营业执照（正副本）",     "A", DocumentLevel.REQUIRED,  [".pdf", ".jpg", ".jpeg", ".png"], "最新版，正副本均需"),
    RequiredDocument("A2", "法定代表人身份证",       "A", DocumentLevel.REQUIRED,  [".pdf", ".jpg", ".jpeg", ".png"], "正反面复印件"),
    RequiredDocument("A3", "实际控制人身份证",        "A", DocumentLevel.SUGGESTED, [".pdf", ".jpg", ".jpeg", ".png"], "如有实际控制人则必填"),
    RequiredDocument("A4", "公司章程",                "A", DocumentLevel.SUGGESTED, [".pdf"], "最新版"),
    RequiredDocument("A5", "验资报告",                "A", DocumentLevel.IF_EXISTS, [".pdf"], "如有则提供"),
    RequiredDocument("A6", "股权树状图",              "A", DocumentLevel.IF_EXISTS, [".pdf", ".jpg", ".jpeg", ".png"], "向上穿透至最终实际控制人"),
    
    # 类别B：财务与税务数据类（4项）
    RequiredDocument("B1", "财务报表（近三年+最新期）", "B", DocumentLevel.REQUIRED, [".pdf", ".xlsx", ".xls", ".xlsm"], "资产负债表、利润表、现金流量表"),
    RequiredDocument("B2", "银行流水（12个月）",       "B", DocumentLevel.REQUIRED, [".pdf", ".xlsx", ".xls"], "主要银行账户交易流水"),
    RequiredDocument("B3", "纳税申报表（近一年）",      "B", DocumentLevel.REQUIRED, [".pdf", ".xlsx", ".xls"], "增值税、企业所得税纳税申报表及完税凭证"),
    RequiredDocument("B4", "现有负债清单",            "B", DocumentLevel.SUGGESTED, [".pdf", ".xlsx", ".xls"], "列明所有尚未结清的融资负债及担保条件"),
    
    # 类别C：经营情况与上下游业务类（4项）
    RequiredDocument("C1", "经营场所证明",            "C", DocumentLevel.SUGGESTED, [".pdf", ".jpg", ".jpeg", ".png"], "产权证明或租赁合同+近期租金支付凭证"),
    RequiredDocument("C2", "上下游交易佐证",          "C", DocumentLevel.SUGGESTED, [".pdf", ".xlsx", ".xls"], "前五大供应商/销售商购销数据、合同、发票"),
    RequiredDocument("C3", "进出口单据",             "C", DocumentLevel.IF_EXISTS, [".pdf"], "报关单、海关单据"),
    RequiredDocument("C4", "在手订单/合同",           "C", DocumentLevel.SUGGESTED, [".pdf"], "重大已签署合同及可行性研究报告"),
    
    # 类别D：科技型企业专属补充资料（4项）
    RequiredDocument("D1", "高新技术企业证书",         "D", DocumentLevel.SUGGESTED, [".pdf", ".jpg", ".jpeg", ".png"], "科技型企业核心资质"),
    RequiredDocument("D2", "知识产权/专利清单",        "D", DocumentLevel.SUGGESTED, [".pdf"], "核心发明专利、实用新型专利、软件著作权"),
    RequiredDocument("D3", "研发费用明细账",          "D", DocumentLevel.SUGGESTED, [".pdf", ".xlsx", ".xls"], "近三年研发费用明细或辅助账册"),
    RequiredDocument("D4", "核心技术团队履历",         "D", DocumentLevel.SUGGESTED, [".pdf", ".jpg", ".jpeg", ".png"], "主要管理层人员详细工作履历"),
]

DOCS_BY_CATEGORY: dict[str, list[RequiredDocument]] = {
    cat: [d for d in DOCUMENT_LIST if d.category == cat]
    for cat in ["A", "B", "C", "D"]
}

CATEGORY_NAMES: dict[str, str] = {
    "A": "基础资质与法务合规类",
    "B": "财务与税务数据类",
    "C": "经营情况与上下游业务类",
    "D": "科技型企业专属补充资料",
}

# 必填项清单
REQUIRED_DOCS: set[str] = {"A1", "A2", "B1", "B2", "B3"}
EXCEL_EXTENSIONS: set[str] = {".xls", ".xlsx", ".xlsm"}

WORKFLOW_STATUS_LABELS: dict[str, str] = {
    "idle":        "等待上传资料",
    "parsing":     "正在解析资料",
    "analyzing":   "正在执行风控筛查",
    "verifying":   "分析完成，待核对",
    "generating":  "正在生成授信报告",
    "done":        "处理完成",
    "error":       "发生异常",
}


# ============================================================================
# 页面配置与深度定制 CSS (商务蓝风格)
# ============================================================================

st.set_page_config(page_title="对公信贷智能化辅助系统", page_icon="🏦", layout="wide")

st.markdown("""
<style>
    /* 全局背景与字体 */
    .stApp { background-color: #F8FAFC; color: #1E293B; }
    
    /* 顶部标题条 */
    .brand-header {
        display: flex; justify-content: space-between; align-items: center;
        padding: 1rem 0 1.5rem 0; border-bottom: 1px solid #E2E8F0; margin-bottom: 2rem;
    }
    .brand-title { font-size: 1.5rem; font-weight: 600; color: #0F172A; display: flex; align-items: center; gap: 8px;}
    .brand-title::before { content: ""; display: inline-block; width: 4px; height: 20px; background-color: #004B87; border-radius: 2px; }
    
    /* 状态指示胶囊 */
    .status-capsule {
        padding: 4px 12px; border-radius: 12px; font-size: 13px; font-weight: 500;
        border: 1px solid #CBD5E1; background: #FFFFFF; color: #64748B;
    }
    .status-capsule.active { background: #E0F2FE; color: #0369A1; border-color: #BAE6FD; }
    
    /* 类别大标题 */
    .category-header { font-size: 1.1rem; font-weight: 600; color: #334155; margin: 1.5rem 0 1rem 0; }
    
    /* 扁平化文档卡片 */
    .doc-card {
        background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px;
        padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.02);
        transition: all 0.2s ease;
    }
    .doc-card:hover { border-color: #CBD5E1; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
    .doc-card.completed { border-left: 4px solid #10B981; background: #F8FAFC; }
    
    /* 标签样式 */
    .badge-req { background: #FEE2E2; color: #B91C1C; padding: 2px 6px; border-radius: 4px; font-size: 12px; font-weight: 500;}
    .badge-sug { background: #F1F5F9; color: #475569; padding: 2px 6px; border-radius: 4px; font-size: 12px; }
    .badge-opt { background: #FFFFFF; color: #94A3B8; border: 1px dashed #CBD5E1; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
    
    /* 已上传文件条目 */
    .uploaded-file-item {
        display: flex; align-items: center; justify-content: space-between;
        background: #F0FDF4; border: 1px solid #BBF7D0;
        padding: 6px 12px; border-radius: 4px; margin-top: 8px; font-size: 13px; color: #166534;
    }
    
    /* 压缩 Streamlit 上传组件高度 */
    [data-testid="stFileUploadDropzone"] { padding: 1rem !important; background-color: #F8FAFC; border: 1px dashed #CBD5E1;}
    [data-testid="stFileUploadDropzone"] div div::before { content: "点击或拖拽上传"; font-size: 13px; color: #64748B; font-weight: 500;}
    [data-testid="stFileUploadDropzone"] div div span, [data-testid="stFileUploadDropzone"] div div small { display: none; }
    
    /* 右侧面板 */
    .side-panel { background: #FFFFFF; padding: 20px; border-radius: 8px; border: 1px solid #E2E8F0; }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# Session State 初始化与辅助函数
# ============================================================================

def init_state():
    defaults = {
        "workflow_status":   "idle",
        "uploaded_files":   {}, 
        "parse_file_paths":  [],
        "file_routes":       {},
        "phase1_result":     None,
        "phase2_result":     None,
        "verified_data":     None,
        "report_path":       None,
        "error_message":     "",
        "file_id_counter":   0,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

def get_uploaded(doc_code: str) -> list:
    return st.session_state.uploaded_files.get(doc_code, [])

def has_uploaded(doc_code: str) -> bool:
    return len(get_uploaded(doc_code)) > 0

def is_required_complete() -> bool:
    return all(has_uploaded(code) for code in REQUIRED_DOCS)

def get_required_progress() -> tuple[int, int]:
    completed = sum(1 for code in REQUIRED_DOCS if has_uploaded(code))
    return completed, len(REQUIRED_DOCS)

def _handle_file_upload(doc_code: str, uploaded_files):
    if uploaded_files is not None:
        if not isinstance(uploaded_files, list):
            uploaded_files = [uploaded_files]
        if doc_code not in st.session_state.uploaded_files:
            st.session_state.uploaded_files[doc_code] = []
            
        existing_names = [f["name"] for f in st.session_state.uploaded_files[doc_code]]
        for uf in uploaded_files:
            if uf.name not in existing_names:
                st.session_state.file_id_counter += 1
                st.session_state.uploaded_files[doc_code].append({
                    "id": st.session_state.file_id_counter,
                    "name": uf.name,
                    "file": uf,
                })
                existing_names.append(uf.name)
        st.rerun()

def _handle_file_delete(doc_code: str, file_id: int):
    """删除单个文件"""
    if doc_code in st.session_state.uploaded_files:
        st.session_state.uploaded_files[doc_code] = [
            f for f in st.session_state.uploaded_files[doc_code]
            if f["id"] != file_id
        ]
        if not st.session_state.uploaded_files[doc_code]:
            del st.session_state.uploaded_files[doc_code]
        st.rerun()

# ============================================================================
# 异步执行函数 (核心业务逻辑)
# ============================================================================

def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def _run_phase2_async(markdown: str) -> dict:
    """执行 Phase2：财务分析 + 科技特征提取 + 合规筛查"""
    financial = await run_financial_analysis(markdown)
    tech = await extract_tech_innovation_metrics(markdown)
    screener = ComplianceScreener()
    enterprise_data = {
        "enterprise_name": "待提取",
        "verified_markdown": markdown,
    }
    compliance = await screener.run_checks(enterprise_data)
    return {
        "financial": financial,
        "tech": tech,
        "compliance": compliance,
    }

async def _run_phase3_async(markdown: str, verified_financial: dict, tech: dict, compliance: dict) -> str:
    """执行 Phase3：Gemini 报告生成"""
    enterprise_data = {
        "enterprise_name": verified_financial.get("enterprise_name", "待提取"),
        "markdown": markdown,
    }
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"授信审查报告_{int(time.time())}.docx"
    report: FinalReport = await generate_report(
        enterprise_data=enterprise_data,
        financial_metrics=verified_financial,
        compliance_results=compliance,
        template_path=Path("templates/授信调查报告模板.docx"),
        output_path=output_path,
    )
    return str(output_path)


# ============================================================================
# 工作流流转函数
# ============================================================================

def _do_start_parsing():
    """触发 Phase1 解析"""
    st.session_state.workflow_status = "parsing"
    st.session_state.error_message = ""

    try:
        all_files = []
        for doc_code, files in st.session_state.uploaded_files.items():
            for f in files:
                all_files.append(f["file"])

        if not all_files:
            st.error("请先上传待解析文件")
            st.session_state.workflow_status = "idle"
            return

        temp_dir = Path("temp")
        temp_dir.mkdir(exist_ok=True)
        saved = []
        routes = {}

        for uploaded in all_files:
            p = temp_dir / uploaded.name
            with open(p, "wb") as f:
                f.write(uploaded.getbuffer())
            ext = Path(uploaded.name).suffix.lower()
            if ext in EXCEL_EXTENSIONS:
                routes[uploaded.name] = "pandas"
            else:
                routes[uploaded.name] = "mineru"
            saved.append(p)

        st.session_state.file_routes = routes
        st.session_state.parse_file_paths = all_files

        # 执行 Phase1
        result = run_async(phase1_parse_documents(temp_dir))

        combined = []
        for fname, content in result["contents"].items():
            combined.append(f"\n\n## 📄 {fname}\n\n{content}")
        combined_md = "\n".join(combined)

        st.session_state.phase1_result = {
            "contents": result["contents"],
            "failed_files": result["failed_files"],
            "combined_markdown": combined_md,
        }

        # 清理临时文件
        for p in saved:
            try:
                os.remove(p)
            except Exception:
                pass

        st.session_state.workflow_status = "analyzing"
        st.rerun()

    except Exception as e:
        st.session_state.error_message = str(e)
        st.session_state.workflow_status = "error"
        st.rerun()

def _do_run_phase2():
    """在 analyzing 状态下执行 Phase2 分析"""
    try:
        markdown = st.session_state.phase1_result["combined_markdown"]
        phase2 = run_async(_run_phase2_async(markdown))
        st.session_state.phase2_result = phase2
        st.session_state.workflow_status = "verifying"
        st.rerun()
    except Exception as e:
        st.session_state.error_message = str(e)
        st.session_state.workflow_status = "error"
        st.rerun()

def _do_confirm_and_generate():
    """用户确认数据无误，触发 Phase3"""
    st.session_state.workflow_status = "generating"
    try:
        markdown = st.session_state.phase1_result["combined_markdown"]
        phase2 = st.session_state.phase2_result

        verified_financial = st.session_state.verified_data or {}
        if not verified_financial or "financial" not in verified_financial:
            verified_financial = phase2.get("financial", {})

        report_path = run_async(_run_phase3_async(
            markdown=markdown,
            verified_financial=verified_financial,
            tech=phase2.get("tech", {}),
            compliance=phase2.get("compliance", {}),
        ))
        st.session_state.report_path = report_path
        st.session_state.workflow_status = "done"
        st.rerun()
    except Exception as e:
        st.session_state.error_message = str(e)
        st.session_state.workflow_status = "error"
        st.rerun()

def _do_reset():
    for key in list(st.session_state.keys()):
        if key not in ["uploaded_files", "file_id_counter"]:
            del st.session_state[key]
    st.session_state.workflow_status = "idle"
    st.rerun()


# ============================================================================
# 主界面流转
# ============================================================================

def main():
    init_state()
    status = st.session_state.workflow_status

    # 极简顶部 Header
    active_cls = "active" if status != "idle" else ""
    st.markdown(f"""
    <div class="brand-header">
        <div class="brand-title">对公信贷智能化辅助系统 <span style="font-size:12px; color:#94A3B8; margin-left:8px; font-weight:normal;">v4.0 Enterprise</span></div>
        <div class="status-capsule {active_cls}">⬤ {WORKFLOW_STATUS_LABELS.get(status, status)}</div>
    </div>
    """, unsafe_allow_html=True)

    if status == "idle":
        _render_idle()
    elif status == "parsing":
        _render_parsing()
    elif status == "analyzing":
        _render_analyzing()
    elif status == "verifying":
        _render_verifying()
    elif status == "generating":
        _render_generating()
    elif status == "done":
        _render_done()
    elif status == "error":
        _render_error()


# ── idle: 资料收集看板 (商务风重构) ──────────────────────────────────────────

def _render_idle():
    col_main, col_spacing, col_side = st.columns([6.5, 0.5, 3])

    with col_main:
        for cat in ["A", "B", "C", "D"]:
            docs = DOCS_BY_CATEGORY[cat]
            completed = sum(1 for d in docs if has_uploaded(d.code))
            
            st.markdown(f'<div class="category-header">{cat}. {CATEGORY_NAMES[cat]} <span style="color:#94A3B8; font-size:14px; font-weight:normal; margin-left:10px;">进度 {completed}/{len(docs)}</span></div>', unsafe_allow_html=True)
            
            for doc in docs:
                is_upl = has_uploaded(doc.code)
                card_cls = "doc-card completed" if is_upl else "doc-card"
                
                if doc.level == DocumentLevel.REQUIRED:
                    badge = '<span class="badge-req">必填</span>'
                elif doc.level == DocumentLevel.SUGGESTED:
                    badge = '<span class="badge-sug">建议</span>'
                else:
                    badge = '<span class="badge-opt">如有</span>'
                
                with st.container():
                    st.markdown(f'<div class="{card_cls}">', unsafe_allow_html=True)
                    c_info, c_upload = st.columns([6, 4])
                    
                    with c_info:
                        st.markdown(f"""
                        <div style="margin-bottom: 4px;">
                            {badge} <span style="font-weight:600; color:#1E293B; margin-left:6px;">{doc.code} {doc.name}</span>
                        </div>
                        <div style="font-size:12px; color:#64748B;">└ {doc.hint}</div>
                        """, unsafe_allow_html=True)
                        
                        if is_upl:
                            for f in get_uploaded(doc.code):
                                c_file_name, c_file_del = st.columns([8, 1])
                                with c_file_name:
                                    st.markdown(f'<div class="uploaded-file-item">✓ {f["name"]}</div>', unsafe_allow_html=True)
                                # 这里注意 Streamlit 按钮可能会打断 HTML 的连续性，但在 st.columns 中没问题
                                with c_file_del:
                                    st.button("✕", key=f"del_{doc.code}_{f['id']}", on_click=_handle_file_delete, args=(doc.code, f["id"]))
                    
                    with c_upload:
                        uploaded_file = st.file_uploader(
                            "upload",
                            type=[t.lstrip(".") for t in doc.accepted_types],
                            key=f"up_{doc.code}_{len(get_uploaded(doc.code))}",
                            label_visibility="collapsed",
                            accept_multiple_files=True,
                        )
                        if uploaded_file:
                            _handle_file_upload(doc.code, uploaded_file)
                            
                    st.markdown('</div>', unsafe_allow_html=True)


    with col_side:
        st.markdown('<div class="side-panel">', unsafe_allow_html=True)
        st.markdown("#### 预审校验中心")
        
        req_completed, req_total = get_required_progress()
        is_complete = is_required_complete()
        total_uploaded_files = sum(len(files) for files in st.session_state.uploaded_files.values())
        has_files = total_uploaded_files > 0
        
        st.progress(req_completed / req_total if req_total > 0 else 0)
        
        if is_complete:
            st.markdown('<div style="color:#059669; font-size:14px; font-weight:500; margin-bottom:16px;">✓ 所有核心必填项已齐备</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="color:#B91C1C; font-size:14px; font-weight:500; margin-bottom:16px;">⚠️ 缺少 {req_total - req_completed} 项必填资料</div>', unsafe_allow_html=True)
            for code in REQUIRED_DOCS:
                if not has_uploaded(code):
                    doc_name = next(d.name for d in DOCUMENT_LIST if d.code == code)
                    st.markdown(f'<div style="color:#64748B; font-size:13px; margin-bottom:4px;">- {code} {doc_name}</div>', unsafe_allow_html=True)
        
        st.markdown("<hr style='margin:20px 0;'>", unsafe_allow_html=True)
        
        if is_complete and has_files:
            st.button("🚀 开始智能解析", type="primary", use_container_width=True, on_click=_do_start_parsing)
        else:
            st.button("需补齐资料解锁", type="primary", disabled=True, use_container_width=True)
            
        st.markdown('</div>', unsafe_allow_html=True)


# ── 后续状态页 ─────────────────────────────────────────────────────────────

def _render_parsing():
    st.markdown("### 🔄 正在解析资料")
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i in range(100):
        progress_bar.progress(i + 1)
        if i < 50:
            status_text.markdown("⏳ 正在调用 MinerU 解析模型...")
        else:
            status_text.markdown("📋 正在整合与清洗多模态数据...")
        import time
        time.sleep(0.05)

    st.spinner("MinerU 云端处理中...")
    _do_start_parsing()

def _render_analyzing():
    st.markdown("### 📈 正在执行智能分析与筛查")
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i in range(100):
        progress_bar.progress(i + 1)
        if i < 30:
            status_text.markdown("⏳ 正在提取核心财务数据...")
        elif i < 60:
            status_text.markdown("🔍 正在筛查企业及个人合规风险...")
        else:
            status_text.markdown("🔬 正在提取科技型创新指标...")
        import time
        time.sleep(0.05)

    st.spinner("深度分析中...")
    _do_run_phase2()

def _render_verifying():
    phase2 = st.session_state.phase2_result
    if not phase2:
        st.error("分析结果为空，请重新解析")
        st.button("🔄 重新开始", on_click=_do_reset)
        return

    financial = phase2.get("financial", {})
    tech = phase2.get("tech", {})
    compliance = phase2.get("compliance", {})

    st.markdown("### ✅ Phase 2 分析结果 — 数据核对")

    st.markdown("#### 📊 核心财务指标 (仅供核对修正)")
    financial_rows = []
    if financial:
        key_labels = {
            "gross_margin": "毛利率(%)",
            "net_profit": "净利润(万元)",
            "operating_revenue": "营业收入(万元)",
            "current_ratio": "流动比率",
            "debt_to_asset_ratio": "资产负债率(%)",
            "revenue_cagr": "营收CAGR(%)",
            "rd_expense_ratio": "研发费用占比(%)",
        }
        for key, label in key_labels.items():
            value = financial.get(key, "")
            financial_rows.append({
                "指标名称": label,
                "AI提取值": str(round(value, 2)) if isinstance(value, (int, float)) else str(value),
                "人工修正值": "",
            })

    if financial_rows:
        edited = st.data_editor(
            financial_rows,
            column_config={
                "指标名称": st.column_config.TextColumn("指标名称", disabled=True),
                "AI提取值": st.column_config.TextColumn("AI提取值", disabled=True),
                "人工修正值": st.column_config.TextColumn("人工修正值（修正时请填入正确数值）"),
            },
            hide_index=True, height=280, key="financial_editor",
        )
        st.session_state.verified_data = {"financial": financial, "edited": edited}
    else:
        st.warning("未能提取到财务指标，请手动补充")

    st.markdown("#### ⚖️ 合规与科技特征速览")
    col1, col2, col3 = st.columns(3)
    with col1:
        overall = compliance.get("overall", "UNKNOWN")
        st.metric("综合风控评级", overall)
    with col2:
        st.metric("核心专利数量", tech.get("patent_count", "N/A"))
    with col3:
        cert = tech.get("high_tech_cert", {})
        st.metric("高新企业资质", "有效" if cert.get("valid") else "无效/未知")

    st.divider()
    col_reset, col_confirm = st.columns([1, 4])
    with col_reset:
        st.button("返回重传", on_click=_do_reset, use_container_width=True)
    with col_confirm:
        st.button("数据核实无误，一键生成授信报告", type="primary", use_container_width=True, on_click=_do_confirm_and_generate)

def _render_generating():
    st.info("📝 正在调度大语言模型生成标准化授信审查报告，请稍候...")
    st.spinner("文档排版中...")

def _render_done():
    st.success("🎉 授信报告生成完毕！")
    if st.session_state.report_path:
        with open(st.session_state.report_path, "rb") as f:
            st.download_button(
                label="📥 下载 Word 版审查报告",
                data=f,
                file_name=Path(st.session_state.report_path).name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
                use_container_width=True,
            )
    st.button("启动新笔业务", on_click=_do_reset)

def _render_error():
    st.error(f"系统运行异常：{st.session_state.error_message}")
    st.button("🔄 重新尝试", on_click=_do_reset)

if __name__ == "__main__":
    main()