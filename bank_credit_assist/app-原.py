"""
app.py
对公信贷智能化辅助系统 — 完整工作流 Web UI（v4.0）
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

from shared.mineru_client import clean_mineru_markdown
from phase1_parser import phase1_parse_documents, parse_excel_locally
from phase2_analysis import run_financial_analysis, extract_tech_innovation_metrics
from phase2_compliance import ComplianceScreener
from phase3_gemini import generate_report, FinalReport


# ============================================================================
# 资料清单数据结构（来自 资料清单.txt）
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
    RequiredDocument("B1", "财务报表（近三年+最新一期）", "B", DocumentLevel.REQUIRED, [".pdf", ".xlsx", ".xls", ".xlsm"], "资产负债表、利润表、现金流量表"),
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
CATEGORY_ICONS: dict[str, str] = {
    "A": "📜", "B": "💰", "C": "🏭", "D": "🔬",
}
# 必填项清单（5项）：A1营业执照、A2法定代表人身份证、B1财务报表、B2银行流水、B3纳税申报表
REQUIRED_DOCS: set[str] = {"A1", "A2", "B1", "B2", "B3"}

EXCEL_EXTENSIONS: set[str] = {".xls", ".xlsx", ".xlsm"}

WORKFLOW_STATUS_LABELS: dict[str, str] = {
    "idle":        "⏳ 等待上传资料",
    "parsing":     "🔄 正在解析资料",
    "analyzing":   "📈 正在执行财务分析与合规筛查",
    "verifying":   "✅ 分析完成，请核对结构化数据",
    "generating":  "📝 正在生成授信报告",
    "done":        "🎉 处理完成",
    "error":       "❌ 发生错误",
}


# ============================================================================
# 页面配置
# ============================================================================

st.set_page_config(
    page_title="对公信贷智能化辅助系统",
    page_icon="🏦",
    layout="wide",
)

st.markdown("""
<style>
    .main-header { font-size: 1.8rem; font-weight: 700; color: #1f4e79; }
    .status-badge { padding: 6px 16px; border-radius: 20px; font-size: 14px; display: inline-flex; align-items: center; gap: 8px; }
    .status-badge.idle { background: #95a5a6; color: white; }
    .status-badge.parsing { background: #3498db; color: white; }
    .status-badge.analyzing { background: #9b59b6; color: white; }
    .status-badge.verifying { background: #f39c12; color: white; }
    .status-badge.generating { background: #e67e22; color: white; }
    .status-badge.done { background: #27ae60; color: white; }
    .status-badge.error { background: #e74c3c; color: white; }
    .required-badge { background-color: #dc3545; color: white; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; }
    .suggested-badge { background-color: #ffc107; color: #333; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; }
    .if-exists-badge { background-color: #6c757d; color: white; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; }
    .doc-file-item { display: flex; align-items: center; gap: 6px; padding: 4px 0; }
    .doc-file-name { font-size: 12px; color: #27ae60; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .doc-file-delete { width: 20px; height: 20px; border: none; background: #ffebee; color: #c0392b; border-radius: 4px; cursor: pointer; font-size: 10px; display: flex; align-items: center; justify-content: center; }
    .doc-file-delete:hover { background: #c0392b; color: white; }
    .doc-item-uploaded { border: 1px solid #27ae60 !important; background: #f0faf4 !important; }
    .stExpander { border: 1px solid #eee; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# Session State 初始化
# ============================================================================

def init_state():
    defaults = {
        "workflow_status":   "idle",
        "uploaded_files":   {},    # {doc_code: [{id, name, file}, ...]} - 支持多文件
        "parse_file_paths":  [],   # 临时保存的待解析文件路径
        "file_routes":       {},   # {filename: "pandas" | "mineru"}
        "phase1_result":     None, # Phase1 解析结果
        "phase2_result":     None, # Phase2 分析结果
        "verified_data":     None, # 用户核对后的数据
        "report_path":       None,
        "error_message":     "",
        "file_id_counter":   0,    # 用于生成唯一文件ID
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def get_uploaded(doc_code: str) -> list:
    """获取某文档已上传的文件列表"""
    return st.session_state.uploaded_files.get(doc_code, [])


def has_uploaded(doc_code: str) -> bool:
    """检查某文档是否有文件上传"""
    return len(get_uploaded(doc_code)) > 0


def is_required_complete() -> bool:
    return all(has_uploaded(code) for code in REQUIRED_DOCS)


def get_required_progress() -> tuple[int, int]:
    completed = sum(1 for code in REQUIRED_DOCS if has_uploaded(code))
    return completed, len(REQUIRED_DOCS)


def level_badge_html(level: DocumentLevel) -> str:
    if level == DocumentLevel.REQUIRED:
        return '<span class="required-badge">必填</span>'
    elif level == DocumentLevel.SUGGESTED:
        return '<span class="suggested-badge">建议</span>'
    return '<span class="if-exists-badge">如有则提供</span>'


def get_file_icon(filename: str) -> str:
    """根据文件扩展名返回图标"""
    ext = Path(filename).suffix.lower()
    icons = {
        ".pdf": "📄", ".doc": "📝", ".docx": "📝",
        ".xls": "📊", ".xlsx": "📊", ".xlsm": "📊",
        ".jpg": "🖼️", ".jpeg": "🖼️", ".png": "🖼️",
        ".html": "🌐", ".pptx": "📽️", ".ppt": "📽️"
    }
    return icons.get(ext, "📁")


# ============================================================================
# 异步运行器
# ============================================================================

def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================================
# Phase2 执行（异步）
# ============================================================================

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


async def _run_phase3_async(
    markdown: str,
    verified_financial: dict,
    tech: dict,
    compliance: dict,
) -> str:
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
# 工作流触发函数
# ============================================================================

def _do_start_parsing():
    """触发 Phase1 + Phase2"""
    st.session_state.workflow_status = "parsing"
    st.session_state.error_message = ""

    try:
        # 收集所有已上传文件作为待解析文件
        all_files = []
        for doc_code, files in st.session_state.uploaded_files.items():
            for f in files:
                all_files.append(f["file"])

        if not all_files:
            st.error("请先上传待解析文件")
            st.session_state.workflow_status = "idle"
            return

        # 保存临时文件并记录路由
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

        # Phase1 解析
        result = run_async(phase1_parse_documents(temp_dir))

        # 合并 Markdown
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

        # 切换到 analyzing
        st.session_state.workflow_status = "analyzing"
        st.rerun()

    except Exception as e:
        st.session_state.error_message = str(e)
        st.session_state.workflow_status = "error"
        st.rerun()


def _do_run_phase2():
    """在 analyzing 状态下：运行 Phase2 分析"""
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

        # 从 verified_data 获取用户修正后的财务指标
        verified_financial = st.session_state.verified_data or {}
        # 如果 verified_data 为空或无效，使用 phase2 的原始值
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
    """重置工作流"""
    for key in list(st.session_state.keys()):
        if key not in ["uploaded_files", "file_id_counter"]:
            del st.session_state[key]
    st.session_state.workflow_status = "idle"
    st.rerun()


def _handle_file_upload(doc_code: str, uploaded_files):
    """处理文件上传 - 支持多文件"""
    if uploaded_files is not None:
        # 如果是单个文件（accept_multiple_files=False的情况），包装成列表
        if not isinstance(uploaded_files, list):
            uploaded_files = [uploaded_files]

        if doc_code not in st.session_state.uploaded_files:
            st.session_state.uploaded_files[doc_code] = []

        # 获取已存在的文件名
        existing_names = [f["name"] for f in st.session_state.uploaded_files[doc_code]]

        # 遍历处理每个上传的文件
        for uploaded_file in uploaded_files:
            if uploaded_file.name not in existing_names:
                st.session_state.file_id_counter += 1
                st.session_state.uploaded_files[doc_code].append({
                    "id": st.session_state.file_id_counter,
                    "name": uploaded_file.name,
                    "file": uploaded_file,
                })
                existing_names.append(uploaded_file.name)

        st.rerun()


def _handle_file_delete(doc_code: str, file_id: int):
    """删除单个文件"""
    if doc_code in st.session_state.uploaded_files:
        st.session_state.uploaded_files[doc_code] = [
            f for f in st.session_state.uploaded_files[doc_code]
            if f["id"] != file_id
        ]
        # 如果列表为空，删除整个key
        if not st.session_state.uploaded_files[doc_code]:
            del st.session_state.uploaded_files[doc_code]
        st.rerun()


# ============================================================================
# 主 UI
# ============================================================================

def main():
    init_state()
    status = st.session_state.workflow_status

    # 头部
    col_header1, col_header2 = st.columns([1, 4])
    with col_header1:
        st.markdown('<p class="main-header">🏦 对公信贷智能化辅助系统</p>', unsafe_allow_html=True)
    with col_header2:
        status_class = status
        st.markdown(f'<div class="status-badge {status_class}">{WORKFLOW_STATUS_LABELS.get(status, status)}</div>', unsafe_allow_html=True)

    st.divider()

    # ── idle：资料上传 + 解析 ─────────────────────────────────────────
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


# ── idle ────────────────────────────────────────────────────────────────────

def _render_idle():
    col_doclist, col_action = st.columns([3, 1])

    with col_doclist:
        st.markdown("### 📋 资料清单")

        for cat in ["A", "B", "C", "D"]:
            docs = DOCS_BY_CATEGORY[cat]
            completed = sum(1 for d in docs if has_uploaded(d.code))
            total = len(docs)

            with st.expander(f"{CATEGORY_ICONS[cat]} 类别{cat}：{CATEGORY_NAMES[cat]}  ({completed}/{total})", expanded=True):
                pct = int(completed / total * 100) if total > 0 else 0
                st.progress(pct, text=f"完成 {completed}/{total} 项")

                for doc in docs:
                    uploaded_list = get_uploaded(doc.code)
                    is_uploaded = len(uploaded_list) > 0

                    # 根据是否有文件应用不同样式
                    item_class = "doc-item-uploaded" if is_uploaded else ""
                    c1, c2, c3 = st.columns([4, 1, 1])

                    with c1:
                        st.markdown(f"**{doc.code}** {doc.name}")
                        if doc.hint:
                            st.caption(f"└ {doc.hint}")
                        # 显示已上传文件列表
                        if is_uploaded:
                            for f in uploaded_list:
                                c_file1, c_file2, c_file3 = st.columns([1, 4, 1])
                                with c_file1:
                                    st.markdown(get_file_icon(f["name"]))
                                with c_file2:
                                    st.markdown(f'<span class="doc-file-name">{f["name"]}</span>', unsafe_allow_html=True)
                                with c_file3:
                                    if st.button("✕", key=f"del_{doc.code}_{f['id']}", on_click=_handle_file_delete, args=(doc.code, f["id"])):
                                        pass
                    with c2:
                        st.markdown(level_badge_html(doc.level), unsafe_allow_html=True)
                    with c3:
                        # 文件上传按钮
                        uploaded_file = st.file_uploader(
                            "上传",
                            type=[t.lstrip(".") for t in doc.accepted_types],  # 移除前缀.
                            key=f"upload_{doc.code}_{len(uploaded_list)}",
                            label_visibility="collapsed",
                            accept_multiple_files=True,
                        )
                        if uploaded_file:
                            _handle_file_upload(doc.code, uploaded_file)

    with col_action:
        st.markdown("### 📤 解析操作")
        req_completed, req_total = get_required_progress()
        is_complete = is_required_complete()

        # 必填项进度
        st.markdown(f"**必填项进度：{req_completed}/{req_total}**")
        progress_pct = int(req_completed / req_total * 100) if req_total > 0 else 0
        if is_complete:
            st.success("✅ 所有必填资料已上传")
        else:
            st.error(f"⚠️ 缺少 {req_total - req_completed} 项必填资料")

        # 缺少的必填项列表
        if not is_complete:
            with st.expander("查看缺少的必填项"):
                for code in REQUIRED_DOCS:
                    if not has_uploaded(code):
                        doc = next(d for d in DOCUMENT_LIST if d.code == code)
                        st.markdown(f"- `{code}` {doc.name}")

        st.divider()

        # 检查是否有任何文件上传
        total_uploaded_files = sum(len(files) for files in st.session_state.uploaded_files.values())
        has_files = total_uploaded_files > 0

        # 显示已上传文件汇总
        if has_files:
            st.markdown("#### 已上传文件汇总")
            for doc_code, files in st.session_state.uploaded_files.items():
                for f in files:
                    doc = next((d for d in DOCUMENT_LIST if d.code == doc_code), None)
                    doc_name = doc.name if doc else doc_code
                    ext = Path(f["name"]).suffix.lower()
                    route = "📊 pandas" if ext in EXCEL_EXTENSIONS else "🤖 MinerU"
                    st.caption(f"{route} {doc_code} - {f['name']}")

        st.divider()

        if is_complete and has_files:
            st.button("🚀 开始解析", type="primary", use_container_width=True, on_click=_do_start_parsing)
        else:
            st.button("🚀 开始解析", type="primary", disabled=True, use_container_width=True)
            if not has_files:
                st.caption("请先上传待解析文件")
            else:
                st.caption("请先上传所有必填资料")


# ── parsing ─────────────────────────────────────────────────────────────────

def _render_parsing():
    st.markdown("### 🔄 正在解析资料")

    # 步骤指示器
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("""
        <div style="text-align: center; padding: 20px; background: #27ae60; color: white; border-radius: 10px;">
            <div style="font-size: 24px;">1</div>
            <div style="font-size: 12px;">上传文件</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown("""
        <div style="text-align: center; padding: 20px; background: #27ae60; color: white; border-radius: 10px;">
            <div style="font-size: 24px;">2</div>
            <div style="font-size: 12px;">MinerU解析</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown("""
        <div style="text-align: center; padding: 20px; background: #bdc3c7; color: white; border-radius: 10px;">
            <div style="font-size: 24px;">3</div>
            <div style="font-size: 12px;">财务分析</div>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown("""
        <div style="text-align: center; padding: 20px; background: #bdc3c7; color: white; border-radius: 10px;">
            <div style="font-size: 24px;">4</div>
            <div style="font-size: 12px;">报告生成</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # 当前状态
    st.markdown("#### 📄 正在通过 MinerU 解析上传的资料...")
    st.markdown("""
    <div style="padding: 15px; background: #f8f9fa; border-radius: 8px; margin: 10px 0;">
        <p style="margin: 5px 0;">🔬 <b>MinerU 文档智能解析云服务</b></p>
        <p style="margin: 5px 0; color: #666; font-size: 14px;">• 支持 PDF、Word、PPT、图片等多种格式</p>
        <p style="margin: 5px 0; color: #666; font-size: 14px;">• Excel 文件将自动使用本地 pandas 解析</p>
        <p style="margin: 5px 0; color: #666; font-size: 14px;">• 请耐心等待，解析过程可能需要几分钟...</p>
    </div>
    """, unsafe_allow_html=True)

    # 进度动画
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i in range(100):
        progress_bar.progress(i + 1)
        if i < 30:
            status_text.markdown("⏳ 正在上传文件...")
        elif i < 70:
            status_text.markdown("🔄 正在调用 MinerU 解析...")
        else:
            status_text.markdown("📋 正在整理解析结果...")
        import time
        time.sleep(0.1)

    st.spinner("MinerU 云端解析中...")

    # 触发 Phase1 + Phase2
    _do_start_parsing()


# ── analyzing ────────────────────────────────────────────────────────────────

def _render_analyzing():
    st.markdown("### 📈 正在执行分析与筛查")

    # 步骤指示器
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("""
        <div style="text-align: center; padding: 20px; background: #27ae60; color: white; border-radius: 10px;">
            <div style="font-size: 24px;">✓</div>
            <div style="font-size: 12px;">上传完成</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown("""
        <div style="text-align: center; padding: 20px; background: #27ae60; color: white; border-radius: 10px;">
            <div style="font-size: 24px;">✓</div>
            <div style="font-size: 12px;">解析完成</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown("""
        <div style="text-align: center; padding: 20px; background: #3498db; color: white; border-radius: 10px;">
            <div style="font-size: 24px;">3</div>
            <div style="font-size: 12px;">财务分析</div>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown("""
        <div style="text-align: center; padding: 20px; background: #bdc3c7; color: white; border-radius: 10px;">
            <div style="font-size: 24px;">4</div>
            <div style="font-size: 12px;">报告生成</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # 当前状态
    st.markdown("#### 🔍 正在执行财务分析、合规筛查和科技特征提取...")
    st.markdown("""
    <div style="padding: 15px; background: #f8f9fa; border-radius: 8px; margin: 10px 0;">
        <p style="margin: 5px 0;">📊 <b>Phase 2 分析模块</b></p>
        <p style="margin: 5px 0; color: #666; font-size: 14px;">• 提取财务指标（毛利率、净利润、资产负债率等）</p>
        <p style="margin: 5px 0; color: #666; font-size: 14px;">• 筛查企业合规风险（反洗钱、诉讼、负面舆情等）</p>
        <p style="margin: 5px 0; color: #666; font-size: 14px;">• 提取科技型中小企业特征（研发费用、专利、团队等）</p>
    </div>
    """, unsafe_allow_html=True)

    # 进度动画
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i in range(100):
        progress_bar.progress(i + 1)
        if i < 20:
            status_text.markdown("⏳ 正在提取财务数据...")
        elif i < 40:
            status_text.markdown("📈 正在计算财务指标...")
        elif i < 60:
            status_text.markdown("🔍 正在筛查企业合规风险...")
        elif i < 80:
            status_text.markdown("👤 正在筛查个人合规风险...")
        else:
            status_text.markdown("🔬 正在提取科技特征...")
        import time
        time.sleep(0.05)

    st.spinner("分析中...")

    # 触发 Phase2
    _do_run_phase2()


# ── verifying ────────────────────────────────────────────────────────────────

def _render_verifying():
    phase2 = st.session_state.phase2_result
    if not phase2:
        st.error("分析结果为空，请重新解析")
        st.button("🔄 重新开始", on_click=_do_reset)
        return

    financial = phase2.get("financial", {})
    tech = phase2.get("tech", {})
    compliance = phase2.get("compliance", {})

    st.markdown("### ✅ Phase 2 分析结果 — 请核对以下数据")

    # ── 财务指标核对（可编辑）──────────────────────────────────────
    st.markdown("#### 📊 财务指标（AI提取值，仅供核对）")

    # 将财务指标整理为可编辑表格
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
                "指标名称": st.column_config.TextColumn("指标名称", width="medium", disabled=True),
                "AI提取值": st.column_config.TextColumn("AI提取值", width="medium", disabled=True),
                "人工修正值": st.column_config.TextColumn("人工修正值（修正时请填入正确数值）", width="large"),
            },
            hide_index=True,
            height=300,
            key="financial_editor",
        )
        # 保存用户修正值
        st.session_state.verified_data = {"financial": financial, "edited": edited}
    else:
        st.warning("未能提取到财务指标，请手动补充")
        edited = []

    st.caption("💡 如 AI 提取值有误，请在「人工修正值」列填入正确数值")

    # ── 合规筛查结果（只读）────────────────────────────────────────
    st.markdown("#### ⚖️ 合规筛查结论")

    col_企业, col_个人, col_综合 = st.columns(3)
    overall = compliance.get("overall", "UNKNOWN")
    overall_color = {"PASS": "✅", "FAIL": "❌", "WARNING": "⚠️"}.get(overall, "❓")
    with col_企业:
        ent = compliance.get("enterprise_check", {})
        st.metric("企业维度", ent.get("status", "未知"))
    with col_个人:
        personal = compliance.get("personal_check", {})
        st.metric("个人维度", personal.get("status", "未知"))
    with col_综合:
        st.metric("综合风险", f"{overall_color} {overall}")

    with st.expander("🔍 查看详细合规筛查结果"):
        st.json(compliance)

    # ── 科技型中小企业特征（只读）──────────────────────────────────
    if tech:
        st.markdown("#### 🔬 科技型中小企业特征")
        col_rd, col_cert, col_patent, col_team = st.columns(4)
        with col_rd:
            st.metric("研发费用占比", f"{tech.get('rd_expense_ratio', 'N/A')}%")
        with col_cert:
            cert = tech.get("high_tech_cert", {})
            st.metric("高新企业证书", "✅ 有效" if cert.get("valid") else "❌ 无效")
        with col_patent:
            st.metric("核心专利数量", tech.get("patent_count", "N/A"))
        with col_team:
            st.metric("核心技术团队", f"{tech.get('team_size', 'N/A')} 人")

        with st.expander("🔍 查看详细科技特征"):
            st.json(tech)

    st.divider()

    # ── 按钮行 ────────────────────────────────────────────────────
    col_reset, col_confirm = st.columns(2)
    with col_reset:
        st.button("🔄 重新分析", on_click=_do_start_parsing, use_container_width=True)
    with col_confirm:
        st.button("✅ 确认数据无误，生成授信报告", type="primary", use_container_width=True, on_click=_do_confirm_and_generate)


# ── generating ────────────────────────────────────────────────────────────────

def _render_generating():
    st.info("📝 正在调用 Gemini API 生成授信审查报告，请稍候...")
    st.spinner("报告生成中，这可能需要几分钟...")


# ── done ────────────────────────────────────────────────────────────────────

def _render_done():
    st.success("🎉 报告生成完成！")

    if st.session_state.report_path:
        with open(st.session_state.report_path, "rb") as f:
            st.download_button(
                label="📥 下载授信审查报告",
                data=f,
                file_name=Path(st.session_state.report_path).name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
                use_container_width=True,
            )

    st.button("🔄 开始新任务", on_click=_do_reset, use_container_width=True)


# ── error ────────────────────────────────────────────────────────────────────

def _render_error():
    st.error(f"❌ 发生错误：{st.session_state.error_message}")
    st.button("🔄 重新开始", on_click=_do_reset, use_container_width=True)


if __name__ == "__main__":
    main()
