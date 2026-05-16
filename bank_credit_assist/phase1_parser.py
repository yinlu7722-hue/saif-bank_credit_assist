"""
phase1_parser.py
Step1: 多模态资料解析
支持 PDF/Word/PPT/图片/HTML 批量解析，实时显示解析进度
Excel 强制走 pandas 本地解析（绝对禁止发给 MinerU）
"""
from __future__ import annotations

import asyncio
import os
import pandas as pd
from pathlib import Path
from typing import TypedDict

from shared.utils import safe_print as _safe_print
from shared.mineru_client import (
    extract_batch_cloud,
    FileProcessingState,
    FileProgress,
)


# ============================================================================
# 文件类型分流配置
# ============================================================================

EXCEL_EXTENSIONS: set[str] = {".xls", ".xlsx", ".xlsm"}
MINERU_EXTENSIONS: set[str] = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt",
    ".jpg", ".jpeg", ".png", ".html", ".htm",
}


class Phase1Result(TypedDict):
    """Phase1 输出结果"""
    contents: dict[str, str]  # {filename: markdown_content}
    failed_files: list[str]


async def print_progress(fp: FileProgress) -> None:
    """实时打印各文件解析进度（避免 emoji 以兼容 Windows GBK 终端）"""
    bar_length: int = 30
    filled: int = int(fp.progress_percent / 100 * bar_length)
    bar: str = "=" * filled + "-" * (bar_length - filled)

    state_indicator: str = {
        FileProcessingState.PENDING: "[PEND]",
        FileProcessingState.UPLOADING: "[UP  ]",
        FileProcessingState.PROCESSING: "[PROC]",
        FileProcessingState.DONE: "[DONE]",
        FileProcessingState.FAILED: "[FAIL]",
    }.get(fp.state, "[????]")

    try:
        _safe_print(f"\r{state_indicator} [{bar}] {fp.progress_percent:3d}% | {fp.filename}")
    except UnicodeEncodeError:
        pass  # Windows GBK 终端无法打印某些字符，静默忽略

    if fp.state == FileProcessingState.DONE:
        _safe_print("")  # 换行
    elif fp.state == FileProcessingState.FAILED:
        _safe_print(f"   ERR: {fp.error_message}")


async def parse_excel_locally(excel_path: Path) -> str:
    """
    使用 pandas 读取 Excel，转换为 Markdown 表格
    绝对不允许将 Excel 原始文件发给 MinerU API
    """
    all_sheets_md: list[str] = []
    xl_file = pd.ExcelFile(excel_path)

    for sheet_name in xl_file.sheet_names:
        df = pd.read_excel(xl_file, sheet_name=sheet_name)
        # 转为 Markdown 表格
        md_table = df.to_markdown(index=False)
        all_sheets_md.append(f"\n\n### Sheet: {sheet_name}\n\n{md_table}\n")

    return "".join(all_sheets_md)


async def phase1_parse_documents(
    input_dir: str | Path,
) -> Phase1Result:
    """
    解析目录下所有支持的文件

    分流规则：
    - .xls/.xlsx → pandas 本地解析，转 Markdown 表格
    - 其他格式 → MinerU 云端 API

    参数:
        input_dir: 包含待解析文件的目录路径

    返回:
        Phase1Result:
          - contents: {filename: markdown_content}
          - failed_files: 解析失败的文件列表
    """
    input_path: Path = Path(input_dir)

    all_files: list[Path] = [input_path / f for f in os.listdir(input_path) if (input_path / f).is_file()]

    mineru_files: list[Path] = []
    excel_files: list[Path] = []

    for f in all_files:
        if f.suffix.lower() in EXCEL_EXTENSIONS:
            excel_files.append(f)
        elif f.suffix.lower() in MINERU_EXTENSIONS:
            mineru_files.append(f)

    results: dict[str, str] = {}

    # 1. Excel 文件：pandas 本地解析（绝对禁止发给 MinerU）
    for excel_file in excel_files:
        md_content = await parse_excel_locally(excel_file)
        results[excel_file.name] = md_content
        _safe_print(f"[Excel本地解析] {excel_file.name} -> {len(md_content)} char")

    # 2. 其他文件：MinerU 批量解析
    if mineru_files:
        _safe_print(f"\n{'='*60}")
        _safe_print(f"开始通过 MinerU 解析 {len(mineru_files)} 个文件...")
        _safe_print(f"{'='*60}\n")

        mineru_results = await extract_batch_cloud(
            mineru_files,
            progress_callback=print_progress,
        )
        results.update(mineru_results)

    # 汇总失败文件
    failed_files: list[str] = [
        name for name, content in results.items()
        if not content  # 空内容视为失败
    ]

    _safe_print(f"\n{'='*60}")
    _safe_print(f"解析完成！成功: {len(results) - len(failed_files)}, 失败: {len(failed_files)}")
    _safe_print(f"{'='*60}\n")

    return Phase1Result(contents=results, failed_files=failed_files)


def generate_markdown_preview(markdown_contents: dict[str, str]) -> str:
    """
    将 Markdown 内容合并为单个可预览的 Markdown 文件
    （用于后续人工核对）
    """
    sections: list[str] = []
    for filename, content in markdown_contents.items():
        sections.append(f"\n\n## 📄 {filename}\n\n{content}")

    return (
        "# 企业尽调资料解析结果\n"
        f"共 {len(markdown_contents)} 个文件\n"
        + "\n".join(sections)
    )


def save_markdown_output(
    markdown_contents: dict[str, str],
    output_dir: str | Path,
) -> Path:
    """
    将解析结果保存为 Markdown 文件
    """
    import markdown

    output_path: Path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 保存合并的 Markdown
    combined_md: str = generate_markdown_preview(markdown_contents)
    output_file: Path = output_path / "解析结果.md"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(combined_md)

    _safe_print(f"Markdown 已保存: {output_file}")

    # 同时生成 HTML 预览
    html_content = markdown.markdown(
        combined_md,
        extensions=['tables', 'fenced_code', 'toc']
    )
    html_file: Path = output_path / "解析结果预览.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: 'Microsoft YaHei', sans-serif; padding: 20px; max-width: 1200px; margin: 0 auto; }}
        .file-section {{ margin-bottom: 40px; }}
        .file-section h2 {{ color: #2c5f2d; border-bottom: 2px solid #2c5f2d; padding-bottom: 10px; }}
        .markdown-content {{ line-height: 1.6; }}
        table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        hr {{ border: none; border-top: 1px solid #ccc; margin: 30px 0; }}
    </style>
</head>
<body>
    <h1>企业尽调资料解析结果</h1>
    {html_content}
</body>
</html>""")

    _safe_print(f"HTML 预览已生成: {html_file}")
    return output_file
