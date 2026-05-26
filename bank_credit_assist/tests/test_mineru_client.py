"""
tests/test_mineru_client.py
测试 MinerU 客户端：传入 PDF 路径，终端输出清理后的 Markdown
用法: python -m tests.test_mineru_client <pdf_path>
"""
from __future__ import annotations

import sys
import asyncio
import os
from pathlib import Path

from shared.encoding import fix_windows_console_encoding

fix_windows_console_encoding()

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.mineru_client import extract_single_cloud, clean_mineru_markdown


async def main(pdf_path: str) -> None:
    """解析单个 PDF 并在终端打印清理后的 Markdown"""
    path = Path(pdf_path)

    if not path.exists():
        print(f"[错误] 文件不存在: {pdf_path}")
        sys.exit(1)

    if path.suffix.lower() != ".pdf":
        print(f"[警告] 文件后缀不是 .pdf: {pdf_path}")

    print(f"[开始] 正在解析: {path.name}")
    print("=" * 60)

    try:
        md_content: str = await extract_single_cloud(path)
        cleaned_md: str = clean_mineru_markdown(md_content)

        print("\n--- Markdown 结果 ---\n")
        print(cleaned_md)
        print("\n--- END ---")
        print(f"\n[完成] 共 {len(cleaned_md)} 字符")

    except Exception as e:
        print(f"[错误] 解析失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python -m tests.test_mineru_client <pdf_path>")
        print("示例: python -m tests.test_mineru_client ./test.pdf")
        sys.exit(1)

    pdf_path = sys.argv[1]
    asyncio.run(main(pdf_path))
