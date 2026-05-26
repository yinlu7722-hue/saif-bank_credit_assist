"""
server.py
对公信贷智能化辅助系统 — FastAPI 后端服务

启动方式:
    cd bank_credit_assist
    uvicorn server:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import logging as _logging
import os
import re as _re
import shutil
import sys
import time as _time_module
import traceback
import uuid
from pathlib import Path
from typing import Any

_logger = _logging.getLogger("credit_assist")

from shared.encoding import fix_windows_console_encoding

fix_windows_console_encoding()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from shared.config import API_ACCESS_KEY

from phase1_parser import phase1_parse_documents
from phase2_analysis import run_financial_analysis, extract_tech_innovation_metrics
from phase2_analysis import extract_enterprise_basic_info
from phase2_calculator import compute_financial_ratios, merge_extracted_and_computed
from phase2_inference import run_inference
from phase3_report import generate_report
from phase4_committee import run_committee
from shared.config import PROJECT_ROOT, OUTPUT_DIR
from shared.data_schema import (
    UNIFIED_DOCUMENT_LIST as DOCUMENT_LIST,
    UNIFIED_REQUIRED_CODES as REQUIRED_CODES,
    UNIFIED_EXCEL_EXTENSIONS as EXCEL_EXTENSIONS,
    UNIFIED_TEXT_EXTENSIONS as SUPPORTED_TEXT_EXTENSIONS,
)
from shared.utils import safe_print as _safe_print


def _sanitize_filename(filename: str) -> str:
    """移除路径遍历字符，仅保留安全字符"""
    safe = Path(filename).name
    safe = _re.sub(r'[\\/:*?"<>|]', '_', safe)
    if not safe or safe in ('.', '..'):
        safe = 'unnamed_file'
    return safe


def _safe_error(e: Exception) -> str:
    """脱敏错误信息：记录完整 traceback 到日志，仅返回通用错误提示给前端"""
    _logger.error(f"Internal error: {type(e).__name__}: {e}", exc_info=True)
    return f"处理出错，请联系管理员。错误ID: {uuid.uuid4().hex[:8]}"


SESSION_TTL_SECONDS: int = 3600  # 1 小时过期


def _cleanup_expired_sessions() -> int:
    """清理过期 session，返回清理数量"""
    now = _time_module.time()
    expired_ids = [
        sid for sid, state in sessions.items()
        if now - state.last_accessed > SESSION_TTL_SECONDS
    ]
    for sid in expired_ids:
        state = sessions[sid]
        if state.temp_dir.exists():
            shutil.rmtree(state.temp_dir, ignore_errors=True)
        del sessions[sid]
    return len(expired_ids)


# ============================================================================
# Session 状态管理
# ============================================================================

class SessionState:
    """单个会话的工作流状态"""

    def __init__(self) -> None:
        self.created_at: float = _time_module.time()
        self.last_accessed: float = _time_module.time()
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
    # 每 20 次访问触发一次过期清理
    if len(sessions) % 20 == 0:
        _cleanup_expired_sessions()

    if session_id not in sessions:
        sessions[session_id] = SessionState()
    else:
        sessions[session_id].last_accessed = _time_module.time()
    return sessions[session_id]


# ============================================================================
# FastAPI 应用
# ============================================================================

class APIKeyMiddleware(BaseHTTPMiddleware):
    """简单 API Key 认证中间件"""

    SKIP_PATHS = {"/", "/static", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in self.SKIP_PATHS):
            return await call_next(request)

        api_key = API_ACCESS_KEY
        if not api_key:
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {api_key}":
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        return await call_next(request)


app = FastAPI(title="对公信贷智能化辅助系统")
app.add_middleware(APIKeyMiddleware)

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
        safe_name = _sanitize_filename(file.filename)
        save_path = state.temp_dir / f"{doc_code}_{file_id}_{safe_name}"
        with open(save_path, "wb") as f:
            content = await file.read()
            f.write(content)

        state.uploaded_files[doc_code].append({
            "id": file_id,
            "name": safe_name,
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
        state.error_message = _safe_error(e)
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
        state.error_message = _safe_error(e)
        state.workflow_status = "error"


async def _run_phase3(state: SessionState, corrections: dict) -> None:
    """后台执行 Phase3：AI 推理 → 报告生成（含平滑进度）"""
    import time as _time

    _start_time = _time.time()
    _inference_timeout = 300  # AI 推理单独 5 分钟上限

    async def _update_progress(percent: int, message: str) -> None:
        state.phase3_progress = {"percent": min(percent, 100), "message": message}

    # ── 推理阶段平滑计时器 ──────────────────────────────────
    _tick_done = 0
    _tick_total = 12

    async def _inference_smooth_tick() -> None:
        """后台每 1 秒推进推理阶段进度，以 2 分钟为限平滑增长到 78%"""
        _inference_estimate = 120  # 预估推理耗时上限（秒）
        try:
            while True:
                await asyncio.sleep(1.0)
                elapsed = _time.time() - _start_time
                ratio = _tick_done / _tick_total if _tick_total > 0 else 0
                if ratio > 0:
                    # 有实际完成数据：基于完成比例估算
                    estimated_total = elapsed / ratio
                    remaining = max(0, estimated_total - elapsed)
                    pct = 10 + int(min(ratio * 1.05, 0.95) * 70)
                    if remaining > 10:
                        msg = f"AI智能推理中...预计还需约 {int(remaining)} 秒"
                    elif remaining > 3:
                        msg = f"AI智能推理中...即将完成"
                    else:
                        msg = "AI智能推理中...正在汇总结果"
                else:
                    # 首批尚未完成：基于时间平滑推进（2 分钟为限，最多到 25%）
                    time_ratio = min(elapsed / _inference_estimate, 1.0)
                    pct = 10 + int(time_ratio * 15)
                    if elapsed < 10:
                        msg = "AI智能推理中...正在启动推理引擎"
                    elif elapsed < 30:
                        msg = "AI智能推理中...正在生成分析文本，请耐心等候"
                    elif elapsed < 60:
                        msg = "AI智能推理中...处理较大资料，预计还需约 1 分钟"
                    else:
                        msg = f"AI智能推理中...已处理 {int(elapsed)} 秒，请继续等候"
                _update_progress(pct, msg)
        except asyncio.CancelledError:
            pass

    async def _inference_progress(done: int, total: int) -> None:
        """批次实际完成回调"""
        nonlocal _tick_done, _tick_total
        _tick_done = done
        _tick_total = total

    try:
        if state.phase1_result is None or state.phase2_result is None:
            raise RuntimeError("前置阶段数据缺失，请重新上传资料并解析")

        markdown = state.phase1_result["combined_markdown"]
        phase2 = state.phase2_result

        await _update_progress(0, "正在准备数据...")

        # ── 过滤 financial：只保留扁平键值对 ──
        _nested_keys = {"profitability", "liquidity", "leverage", "operation", "growth", "summary"}
        _flat_financial = {k: v for k, v in phase2.get("financial", {}).items() if k not in _nested_keys}

        await _update_progress(2, "正在提取财务报表关键指标...")

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

        await _update_progress(5, "正在整理企业基本信息...")

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

        await _update_progress(8, "正在启动AI推理引擎...")

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

        await _update_progress(10, "AI智能推理中...正在启动推理引擎")

        # 启动平滑计时器
        _tick_task = asyncio.create_task(_inference_smooth_tick())

        inference_text = await asyncio.wait_for(
            run_inference(
                enterprise_data=enterprise_data_for_inference,
                financial_data=_flat_financial,
                progress_callback=_inference_progress,
            ),
            timeout=_inference_timeout,
        )
        state.inference_text = inference_text

        _tick_task.cancel()
        await _update_progress(80, "AI推理完成，正在汇总分析结果...")

        state.phase2_progress[5]["status"] = "done"
        _safe_print(f"[Phase3.0] Inference done: {len(inference_text)} fields generated")

        # ── Phase 3.1: 文档生成（分步推进，间隔拉长以便前端轮询捕获）──
        state.phase2_progress[6]["status"] = "running"

        await _update_progress(82, "正在构建报告封面及目录...")
        await asyncio.sleep(0.8)

        await _update_progress(85, "正在编制企业基本信息...")
        await asyncio.sleep(0.8)

        await _update_progress(88, "正在编制经营分析及财务报表...")
        await asyncio.sleep(0.8)

        await _update_progress(92, "正在撰写风险分析与授信建议...")
        await asyncio.sleep(0.8)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / f"授信审查报告_{int(_time.time())}.docx"

        await _update_progress(95, "正在编译生成Word文档...")

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
        await _update_progress(98, "正在保存文档...")
        await _update_progress(100, "报告生成完成！")
        state.workflow_status = "done"

    except asyncio.TimeoutError:
        for step in state.phase2_progress:
            if step["status"] == "running":
                step["status"] = "failed"
        _safe_print(f"[Phase3] Inference timed out after {_inference_timeout}s")
        state.error_message = _safe_error(TimeoutError(f"AI推理超时（{_inference_timeout}秒），请检查网络或 API 服务"))
        state.workflow_status = "error"

    except Exception as e:
        for step in state.phase2_progress:
            if step["status"] == "running":
                step["status"] = "failed"
        _safe_print(traceback.format_exc())
        state.error_message = _safe_error(e)
        state.workflow_status = "error"


async def _run_phase4(session_id: str) -> None:
    """后台执行 Phase4 模拟贷审会"""
    state = get_session(session_id)

    try:
        # 准备上下文数据
        session_data = {
            "phase2_result": state.phase2_result or {},
            "inference_text": state.inference_text or {},
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
        final_conc = (result.final_conclusion or {}).get("final_conclusion", "N/A")
        _safe_print(f"[Phase4] Committee done — speeches: {len(result.debate_log)}, conclusion: {final_conc}")

    except Exception as e:
        _safe_print(f"[Phase4] EXCEPTION: {type(e).__name__}: {e}")
        _safe_print(traceback.format_exc())
        state.phase4_result = {
            "status": "error",
            "error": str(e).encode("ascii", errors="replace").decode("ascii"),
        }
        state.error_message = state.phase4_result["error"]
        state.committee_running = False
        state.workflow_status = "error"


# ============================================================================
# 启动入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
