"""
server.py
对公信贷智能化辅助系统 — FastAPI 后端服务

启动方式:
    cd bank_credit_assist
    uvicorn server:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

# ── Windows 终端 UTF-8 编码修复（防止 GBK 编码错误）─────────────
# 在 Windows 上，默认终端编码为 GBK，无法编码 ✗✔✅❌ 等 Unicode 符号。
# 重新配置 stdout/stderr 为 UTF-8，从根源上避免所有 GBK 编码问题。
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from phase1_parser import phase1_parse_documents
from phase2_analysis import run_financial_analysis, extract_tech_innovation_metrics
from phase2_analysis import extract_enterprise_basic_info
from phase2_calculator import compute_financial_ratios, merge_extracted_and_computed
from phase2_inference import run_inference
from phase3_report import generate_report
from phase4_committee import run_committee
from shared.config import PROJECT_ROOT, OUTPUT_DIR
from shared.utils import safe_print as _safe_print


# ============================================================================
# 资料清单常量（与前端保持一致）
# ============================================================================

REQUIRED_CODES: set[str] = {"A1", "A2", "B1", "B2"}
EXCEL_EXTENSIONS: set[str] = {".xls", ".xlsx", ".xlsm"}

DOCUMENT_LIST: list[dict] = [
    # A 类 — 主体资格
    {"code": "A1", "name": "营业执照（正副本）", "level": "required"},
    {"code": "A2", "name": "法定代表人身份证", "level": "required"},
    {"code": "A3", "name": "公司章程", "level": "suggested"},
    {"code": "A4", "name": "验资报告", "level": "if-exists"},
    {"code": "A5", "name": "股权树状图", "level": "if-exists"},
    # B 类 — 财务资料
    {"code": "B1", "name": "财务报表（近三年+最新一期）", "level": "required"},
    {"code": "B2", "name": "银行流水（12个月）", "level": "required"},
    {"code": "B3", "name": "纳税申报表（近三年）", "level": "suggested"},
    {"code": "B4", "name": "银行授信清单", "level": "suggested"},
    # C 类 — 经营佐证
    {"code": "C1", "name": "经营场所证明", "level": "suggested"},
    {"code": "C2", "name": "上下游交易佐证", "level": "suggested"},
    {"code": "C3", "name": "进出口单据", "level": "if-exists"},
    {"code": "C4", "name": "在手订单/合同", "level": "suggested"},
    # D 类 — 科技属性
    {"code": "D1", "name": "高新技术企业证书", "level": "suggested"},
    {"code": "D2", "name": "知识产权/专利清单", "level": "suggested"},
    {"code": "D3", "name": "研发费用明细账", "level": "suggested"},
    {"code": "D4", "name": "核心技术团队履历", "level": "suggested"},
    # E 类 — 经营概况
    {"code": "E1", "name": "主营业务情况", "level": "suggested"},
    {"code": "E2", "name": "公司基本介绍", "level": "suggested"},
    # G 类 — 担保资料（条件触发：前端勾选担保类型后显示）
    {"code": "G1", "name": "法人担保资料", "level": "conditional"},
    {"code": "G2", "name": "抵质押物资料", "level": "conditional"},
    {"code": "G3", "name": "自然人担保资料", "level": "conditional"},
]

# 支持的文件格式（后端 MinerU 解析支持）
SUPPORTED_TEXT_EXTENSIONS: set[str] = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".jpg", ".jpeg", ".png", ".html", ".htm"}


# ============================================================================
# Session 状态管理
# ============================================================================

class SessionState:
    """单个会话的工作流状态"""

    def __init__(self) -> None:
        self.workflow_status: str = "idle"
        self.uploaded_files: dict[str, list[dict]] = {}  # {doc_code: [{id, name, path}]}
        self.file_id_counter: int = 0
        self.phase1_result: dict | None = None
        self.phase2_result: dict | None = None
        self.inference_text: dict | None = None
        self.report_path: str | None = None
        self.error_message: str = ""
        self.phase2_progress: list[dict] = []  # [{step, label, status}]
        self.guarantee_types: list[str] = []  # ["legal", "collateral", "natural_person"]
        self.phase3_progress: dict = {"percent": 0, "message": ""}
        self.phase4_result: dict | None = None
        self.committee_running: bool = False
        self.temp_dir: Path = PROJECT_ROOT / "temp" / str(uuid.uuid4())
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def get_next_file_id(self) -> int:
        self.file_id_counter += 1
        return self.file_id_counter


# session_id → SessionState
sessions: dict[str, SessionState] = {}


def get_session(session_id: str) -> SessionState:
    if session_id not in sessions:
        sessions[session_id] = SessionState()
    return sessions[session_id]


# ============================================================================
# FastAPI 应用
# ============================================================================

app = FastAPI(title="对公信贷智能化辅助系统")

# 挂载项目根目录的静态文件（index.html 在根目录）
STATIC_DIR = PROJECT_ROOT
app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=False), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    """返回根目录的 index.html"""
    html_path = PROJECT_ROOT / "index.html"
    if not html_path.exists():
        raise HTTPException(404, "index.html not found in project root")
    return FileResponse(str(html_path), media_type="text/html")


# ============================================================================
# API 端点
# ============================================================================

@app.post("/api/upload")
async def upload_files(
    session_id: str = Form(...),
    doc_code: str = Form(...),
    files: list[UploadFile] = File(...),
):
    """上传文件到指定 doc_code"""
    state = get_session(session_id)
    if doc_code not in state.uploaded_files:
        state.uploaded_files[doc_code] = []

    existing_names = {f["name"] for f in state.uploaded_files[doc_code]}
    uploaded = []

    for file in files:
        if file.filename in existing_names:
            continue

        file_id = state.get_next_file_id()
        save_path = state.temp_dir / f"{doc_code}_{file_id}_{file.filename}"
        with open(save_path, "wb") as f:
            content = await file.read()
            f.write(content)

        state.uploaded_files[doc_code].append({
            "id": file_id,
            "name": file.filename,
            "path": str(save_path),
        })
        existing_names.add(file.filename)
        uploaded.append({"id": file_id, "name": file.filename})

    return {"uploaded": uploaded, "doc_code": doc_code}


@app.delete("/api/upload/{session_id}/{doc_code}/{file_id}")
async def delete_file(session_id: str, doc_code: str, file_id: int):
    """删除指定已上传文件"""
    state = get_session(session_id)
    if doc_code not in state.uploaded_files:
        raise HTTPException(404, "doc_code not found")

    files = state.uploaded_files[doc_code]
    target = None
    for f in files:
        if f["id"] == file_id:
            target = f
            break

    if target is None:
        raise HTTPException(404, "file not found")

    # 删除磁盘文件
    try:
        os.remove(target["path"])
    except OSError:
        pass

    state.uploaded_files[doc_code] = [f for f in files if f["id"] != file_id]
    if not state.uploaded_files[doc_code]:
        del state.uploaded_files[doc_code]

    return {"deleted": file_id}


@app.post("/api/guarantee-types/{session_id}")
async def set_guarantee_types(session_id: str, types: str = Form("[]")):
    """设置担保类型"""
    import json
    state = get_session(session_id)
    try:
        state.guarantee_types = json.loads(types)
    except json.JSONDecodeError:
        state.guarantee_types = []
    return {"guarantee_types": state.guarantee_types}


@app.get("/api/status/{session_id}")
async def get_status(session_id: str):
    """查询当前工作流状态和进度"""
    state = get_session(session_id)

    required_uploaded = sum(
        1 for code in REQUIRED_CODES
        if code in state.uploaded_files and state.uploaded_files[code]
    )
    required_total = len(REQUIRED_CODES)

    suggested_uploaded = 0
    suggested_total = 0
    for doc in DOCUMENT_LIST:
        if doc["level"] == "suggested":
            suggested_total += 1
            if doc["code"] in state.uploaded_files and state.uploaded_files[doc["code"]]:
                suggested_uploaded += 1

    return {
        "status": state.workflow_status,
        "error_message": state.error_message,
        "required_progress": {"completed": required_uploaded, "total": required_total},
        "suggested_progress": {"completed": suggested_uploaded, "total": suggested_total},
        "uploaded_files": {
            code: [{"id": f["id"], "name": f["name"]} for f in files]
            for code, files in state.uploaded_files.items()
        },
        "report_path": state.report_path,
        "phase2_progress": state.phase2_progress,
        "guarantee_types": state.guarantee_types,
        "phase3_progress": state.phase3_progress,
        "phase4_result": state.phase4_result,
        "committee_running": state.committee_running,
    }


@app.post("/api/start-parse")
async def start_parse(session_id: str = Form(...)):
    """触发 Phase1 解析（后台执行）"""
    state = get_session(session_id)

    if state.workflow_status not in ("idle",):
        raise HTTPException(400, f"Cannot start parsing from status: {state.workflow_status}")

    # 校验必填项
    for code in REQUIRED_CODES:
        if code not in state.uploaded_files or not state.uploaded_files[code]:
            raise HTTPException(400, f"Missing required document: {code}")

    state.workflow_status = "parsing"
    state.error_message = ""

    # 后台执行 Phase1
    asyncio.create_task(_run_phase1(state))

    return {"status": "parsing"}


@app.post("/api/start-analyze")
async def start_analyze(session_id: str = Form(...)):
    """触发 Phase2 分析（后台执行）"""
    state = get_session(session_id)

    if state.workflow_status != "parsing_done":
        raise HTTPException(400, f"Cannot start analyzing from status: {state.workflow_status}")

    state.workflow_status = "analyzing"
    asyncio.create_task(_run_phase2(state))

    return {"status": "analyzing"}


@app.get("/api/phase2-result/{session_id}")
async def get_phase2_result(session_id: str):
    """获取 Phase2 分析结果"""
    state = get_session(session_id)

    if not state.phase2_result:
        raise HTTPException(404, "Phase2 result not available")

    return state.phase2_result


@app.post("/api/confirm-generate")
async def confirm_generate(session_id: str = Form(...), corrections: str = Form("{}")):
    """确认数据并触发 Phase3 报告生成"""
    import json

    state = get_session(session_id)

    if state.workflow_status != "verifying":
        raise HTTPException(400, f"Cannot generate report from status: {state.workflow_status}")

    state.workflow_status = "generating"

    # 合并用户修正数据
    try:
        corrections_dict = json.loads(corrections)
    except json.JSONDecodeError:
        corrections_dict = {}

    asyncio.create_task(_run_phase3(state, corrections_dict))

    return {"status": "generating"}


@app.get("/api/download-report/{session_id}")
async def download_report(session_id: str):
    """下载生成的 Word 报告"""
    state = get_session(session_id)

    if not state.report_path or not Path(state.report_path).exists():
        raise HTTPException(404, "Report not found")

    return FileResponse(
        state.report_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=Path(state.report_path).name,
    )


@app.post("/api/start-committee/{session_id}")
async def start_committee(session_id: str):
    """触发 Phase4 模拟贷审会（后台执行）"""
    state = get_session(session_id)

    if state.workflow_status != "done":
        raise HTTPException(400, f"Cannot start committee from status: {state.workflow_status}")

    if state.committee_running:
        raise HTTPException(400, "Committee is already running")

    state.committee_running = True
    state.phase4_result = {"debate_log": [], "status": "running"}
    state.workflow_status = "reviewing"
    asyncio.create_task(_run_phase4(session_id))

    return {"status": "reviewing"}


@app.post("/api/reset")
async def reset_workflow(session_id: str = Form(...)):
    """重置工作流"""
    if session_id in sessions:
        state = sessions[session_id]
        # 清理临时文件
        if state.temp_dir.exists():
            shutil.rmtree(state.temp_dir, ignore_errors=True)
        del sessions[session_id]

    return {"status": "reset"}


# ============================================================================
# 后台任务
# ============================================================================

async def _run_phase1(state: SessionState) -> None:
    """后台执行 Phase1 解析 + 自动链式启动 Phase2"""
    try:
        # 将所有已上传文件复制到解析目录
        parse_dir = state.temp_dir / "parse_input"
        parse_dir.mkdir(exist_ok=True)

        for doc_code, files in state.uploaded_files.items():
            for f in files:
                src = Path(f["path"])
                if src.exists():
                    dst = parse_dir / f["name"]
                    shutil.copy2(src, dst)

        result = await phase1_parse_documents(parse_dir)

        combined = []
        for fname, content in result["contents"].items():
            combined.append(f"\n\n## 📄 {fname}\n\n{content}")
        combined_md = "\n".join(combined)

        state.phase1_result = {
            "contents": result["contents"],
            "failed_files": result["failed_files"],
            "combined_markdown": combined_md,
        }

        # Phase1 完成，自动进入 Phase2（无需前端额外请求）
        state.workflow_status = "analyzing"
        await _run_phase2(state)

    except Exception as e:
        state.error_message = str(e).encode("ascii", errors="replace").decode("ascii")
        state.workflow_status = "error"


async def _run_phase2(state: SessionState) -> None:
    """后台执行 Phase2 分析"""
    try:
        markdown = state.phase1_result["combined_markdown"]

        # 初始化进度
        state.phase2_progress = [
            {"step": "2.1", "label": "财务报表提取", "status": "running"},
            {"step": "2.2", "label": "科技创新特征提取", "status": "pending"},
            {"step": "2.3", "label": "企业基本信息提取", "status": "pending"},
            {"step": "2.4", "label": "财务指标计算", "status": "pending"},
            {"step": "2.5", "label": "收入交叉核验", "status": "pending"},
        ]

        _safe_print(f"\n[Phase2] Markdown length: {len(markdown)} chars")

        # ── Phase 2.1: 财务报表提取 ───────────────────────────────
        financial = await run_financial_analysis(markdown)
        state.phase2_progress[0]["status"] = "done"
        _safe_print(f"[Phase2.1] Financial extracted: total_assets={financial.get('total_assets')}, op_rev={financial.get('operating_revenue')}")

        # ── Phase 2.2: 科技型中小企业特征提取 ───────────────────
        state.phase2_progress[1]["status"] = "running"
        tech = await extract_tech_innovation_metrics(markdown)
        state.phase2_progress[1]["status"] = "done"
        _safe_print(f"[Phase2.2] Tech extracted: rd_ratio={tech.get('rd_expense_ratio')}, patents={tech.get('patent_count')}")

        # ── Phase 2.3: 企业基本信息提取（营业执照、公司章程）──────
        state.phase2_progress[2]["status"] = "running"
        basic_info = await extract_enterprise_basic_info(markdown)
        state.phase2_progress[2]["status"] = "done"
        _safe_print(f"[Phase2.3] Basic info extracted: {list(basic_info.keys())}")

        # ── Phase 2.4: 财务指标计算（衍生指标精准计算 + 杜邦分析 + 年度指标）─
        state.phase2_progress[3]["status"] = "running"
        computed_ratios = compute_financial_ratios(financial)
        financial_merged = merge_extracted_and_computed(financial, computed_ratios)
        state.phase2_progress[3]["status"] = "done"
        _safe_print(f"[Phase2.4] Computed ratios: {list(computed_ratios.keys())}")

        # ── Phase 2.5: 收入交叉核验 ────────────────────────────────
        state.phase2_progress[4]["status"] = "running"
        from phase2_analysis import run_income_verification
        income_verification = await run_income_verification(markdown, financial_merged)
        state.phase2_progress[4]["status"] = "done"
        _safe_print(f"[Phase2.5] Income verification: {income_verification.get('conclusion', 'N/A')[:60]}")

        # ── 年度财务数据提取 + 年度指标计算 ──────────────────────
        from phase2_analysis import extract_annual_financial_data
        from phase2_calculator import compute_annual_indicators_per_year
        annual_data = extract_annual_financial_data(markdown)
        annual_indicators = compute_annual_indicators_per_year(annual_data) if annual_data else {}
        _safe_print(f"[Phase2] Annual data: {len(annual_data)} years, indicators: {list(annual_indicators.keys())}")

        # ── 汇总 Phase2 结果（AI 推理后置到 Phase3）────────────────
        state.phase2_result = {
            "financial": financial_merged,
            "tech": tech,
            "basic_info": basic_info,
            "income_verification": income_verification,
            "annual_data": annual_data,
            "annual_indicators": annual_indicators,
        }
        state.workflow_status = "verifying"

    except Exception as e:
        for step in state.phase2_progress:
            if step["status"] == "running":
                step["status"] = "failed"
        _safe_print(traceback.format_exc())
        state.error_message = str(e).encode("ascii", errors="replace").decode("ascii")
        state.workflow_status = "error"


async def _run_phase3(state: SessionState, corrections: dict) -> None:
    """后台执行 Phase3：AI 推理 → 报告生成（含进度计时）"""
    import time as _time
    _start_time = _time.time()
    _timeout = 180  # 3 分钟

    async def _update_progress(percent: int, message: str) -> None:
        state.phase3_progress = {"percent": percent, "message": message}

    async def _tick_progress() -> None:
        """按时间推进百分比，最多到 85%（留给推理完成跳转）"""
        elapsed = _time.time() - _start_time
        pct = min(85, int(elapsed / _timeout * 100))
        await _update_progress(pct, "正在生成报告...")

    try:
        markdown = state.phase1_result["combined_markdown"]
        phase2 = state.phase2_result

        await _update_progress(0, "正在准备数据...")

        # 合并修正数据到财务指标
        financial = phase2.get("financial", {})
        for key, value in corrections.items():
            if value != "" and value is not None:
                try:
                    financial[key] = float(value)
                except (ValueError, TypeError):
                    pass

        basic_info = phase2.get("basic_info", {})
        tech = phase2.get("tech", {})
        income_verification = phase2.get("income_verification", {})

        await _update_progress(5, "正在准备数据...")

        # ── Phase 3.0: AI 推理 ──────────────────────────────────
        state.phase2_progress = [
            {"step": "2.1", "label": "财务报表提取", "status": "done"},
            {"step": "2.2", "label": "科技创新特征提取", "status": "done"},
            {"step": "2.3", "label": "企业基本信息提取", "status": "done"},
            {"step": "2.4", "label": "财务指标计算", "status": "done"},
            {"step": "2.5", "label": "收入交叉核验", "status": "done"},
            {"step": "3.1", "label": "AI智能推理", "status": "running"},
            {"step": "3.2", "label": "文档生成", "status": "pending"},
        ]

        await _update_progress(10, "正在执行AI智能推理...")

        enterprise_data_for_inference = {
            "enterprise_name": (basic_info.get("company_name") or financial.get("enterprise_name") or "待提取"),
            "registration_date": basic_info.get("registration_date", ""),
            "business_scope": basic_info.get("business_scope", ""),
            "legal_representative": basic_info.get("legal_representative", ""),
            "shareholder_structure": basic_info.get("shareholder_structure", "待从公司章程提取"),
            "actual_controller": basic_info.get("actual_controller", "待穿透分析"),
            "main_products": "",
            "business_model": "",
        }

        # 启动计时更新（每秒 tick 一次，后台运行）
        _tick_task = asyncio.create_task(_tick_loop(_start_time, _timeout, _update_progress))

        inference_text = await run_inference(
            enterprise_data=enterprise_data_for_inference,
            financial_data=financial,
        )
        state.inference_text = inference_text

        _tick_task.cancel()
        await _update_progress(85, "AI推理完成，正在生成文档...")

        state.phase2_progress[5]["status"] = "done"
        _safe_print(f"[Phase3.0] Inference done: {len(inference_text)} fields generated")

        # ── Phase 3.1: 文档生成 ──────────────────────────────────
        state.phase2_progress[6]["status"] = "running"
        await _update_progress(88, "正在构建报告文档...")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / f"授信审查报告_{int(time.time())}.docx"

        await generate_report(
            enterprise_name=(basic_info.get("company_name") or financial.get("enterprise_name") or "待提取"),
            basic_info=basic_info,
            financial_metrics=financial,
            tech_metrics=tech,
            inference_text=inference_text,
            income_verification=income_verification,
            guarantee_types=state.guarantee_types,
            markdown_content=markdown,
            output_path=output_path,
            annual_indicators=phase2.get("annual_indicators", {}),
        )

        state.phase2_progress[6]["status"] = "done"
        state.report_path = str(output_path)
        await _update_progress(100, "报告生成完成！")
        state.workflow_status = "done"

    except Exception as e:
        for step in state.phase2_progress:
            if step["status"] == "running":
                step["status"] = "failed"
        _safe_print(traceback.format_exc())
        state.error_message = str(e).encode("ascii", errors="replace").decode("ascii")
        state.workflow_status = "error"


async def _run_phase4(session_id: str) -> None:
    """后台执行 Phase4 模拟贷审会"""
    state = get_session(session_id)

    try:
        # 准备上下文数据
        session_data = {
            "phase2_result": state.phase2_result,
            "inference_text": getattr(state, "inference_text", {}),
        }

        # 进度回调：将每轮发言实时写入 state
        def on_progress(log_entry: dict) -> None:
            if state.phase4_result is not None:
                state.phase4_result["debate_log"].append(log_entry)
                state.phase4_result["status"] = f"Round {log_entry['round']}: {log_entry['speaker_name']} 发言中..."

        result = await run_committee(session_data, on_progress)

        # 序列化结果
        state.phase4_result = {
            "status": "done",
            "briefing": result.briefing,
            "initial_positions": result.initial_positions,
            "debate_log": result.debate_log,
            "final_positions": result.final_positions,
            "final_conclusion": result.final_conclusion,
            "position_shifts": result.position_shifts,
        }
        state.committee_running = False
        state.workflow_status = "done"

    except Exception as e:
        _safe_print(traceback.format_exc())
        state.phase4_result = {
            "status": "error",
            "error": str(e).encode("ascii", errors="replace").decode("ascii"),
        }
        state.committee_running = False
        state.workflow_status = "error"


async def _tick_loop(start_time: float, timeout: float, update_fn) -> None:
    """后台每秒更新进度百分比"""
    import time as _time
    try:
        while True:
            await asyncio.sleep(1)
            elapsed = _time.time() - start_time
            pct = min(85, int(elapsed / timeout * 100))
            await update_fn(pct, "正在生成报告...")
    except asyncio.CancelledError:
        pass


# ============================================================================
# 启动入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
