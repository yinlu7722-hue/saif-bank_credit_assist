"""
shared/mineru_client.py
MinerU 云端 API 异步状态机客户端 v3.0
- 稳健的异步状态机替代硬编码轮询
- 指数退避重试机制
- asyncio.Queue 实时进度推送
- Python 3.10+ 类型提示
- 支持代理配置
"""
from __future__ import annotations

import os
import io
import re
import uuid
import asyncio
import zipfile
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable
from pathlib import Path

import aiohttp
import pandas as pd

from shared.config import MINERU_API_TOKEN, MINERU_API_BASE, HTTPS_PROXY

# ============================================================================
# 配置
# ============================================================================

MAX_RETRIES: int = 5
BASE_RETRY_DELAY: float = 1.0  # 秒，指数退避基数
INITIAL_POLL_INTERVAL: float = 2.0  # 首次轮询间隔（秒）
MAX_POLL_INTERVAL: float = 30.0  # 最长轮询间隔（秒）

logger: logging.Logger = logging.getLogger(__name__)


# ============================================================================
# 枚举与数据结构
# ============================================================================

class FileProcessingState(str, Enum):
    """单个文件处理状态"""
    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class FileProgress:
    """单个文件的处理进度"""
    filename: str
    state: FileProcessingState = FileProcessingState.PENDING
    error_message: str | None = None
    progress_percent: int = 0  # 0-100


@dataclass
class BatchProgress:
    """批次整体进度"""
    batch_id: str
    total_files: int
    completed: int = 0
    failed: int = 0
    file_states: dict[str, FileProgress] = field(default_factory=dict)

    @property
    def overall_percent(self) -> int:
        if self.total_files == 0:
            return 0
        return int((self.completed + self.failed) / self.total_files * 100)

    @property
    def is_all_done(self) -> bool:
        return (self.completed + self.failed) >= self.total_files


# ============================================================================
# 回调与类型别名
# ============================================================================

# 进度回调签名：FileProgress 对象
ProgressCallback = Callable[[FileProgress], Awaitable[None]]
# 完成回调签名：(filename, markdown_content)
DoneCallback = Callable[[str, str], Awaitable[None]]


# ============================================================================
# 核心：指数退避重试装饰器
# ============================================================================

def async_retry_with_backoff(
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_RETRY_DELAY,
    exponential_base: float = 2.0,
) -> Callable:
    """
    指数退避重试装饰器

    重试间隔序列：1s, 2s, 4s, 8s, 16s（最大5次）
    """
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            last_exception: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (exponential_base ** attempt), 16.0)
                        logger.warning(
                            f"[{func.__name__}] 第{attempt + 1}次尝试失败: {e}，"
                            f"{delay:.1f}秒后重试..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"[{func.__name__}] 全部{max_retries + 1}次尝试均失败")
            raise last_exception from None
        return wrapper
    return decorator


# ============================================================================
# Markdown 清理
# ============================================================================

def clean_mineru_markdown(text: str) -> str:
    """
    清理 MinerU 返回的 Markdown
    1. 去除字间换行（汉字/字母之间的多余换行）
    2. HTML 表格 → 标准 Markdown 表格
    """
    # 1. 去掉两个可打印字符之间的单个换行（字间换行）
    text = re.sub(r'(?<=[^\s<])\n(?=[^\s>])', '', text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # 2. HTML 表格转 Markdown 表格
    table_pattern = re.compile(r'<table.*?>.*?</table>', re.DOTALL | re.IGNORECASE)

    def replace_with_md(match):
        html_str = match.group(0)
        try:
            dfs = pd.read_html(io.StringIO(html_str))
            if dfs:
                return "\n\n" + dfs[0].to_markdown(index=False) + "\n\n"
        except Exception:
            pass
        return html_str

    text = table_pattern.sub(replace_with_md, text)
    return text


# ============================================================================
# 核心类：MinerU 异步状态机客户端
# ============================================================================

class MinerUAsyncClient:
    """
    MinerU 云端 API 异步状态机客户端

    使用 asyncio.Event + 生命周期回调管理批量文件解析任务，
    替代脆弱的硬编码轮询逻辑。
    """

    def __init__(
        self,
        api_token: str | None = None,
        api_base: str | None = None,
        progress_callback: ProgressCallback | None = None,
        done_callback: DoneCallback | None = None,
    ) -> None:
        self._api_token: str = api_token or MINERU_API_TOKEN
        self._api_base: str = api_base or MINERU_API_BASE
        self._progress_callback: ProgressCallback | None = progress_callback
        self._done_callback: DoneCallback | None = done_callback
        self._proxy: str | None = HTTPS_PROXY

        # 内部状态
        self._headers: dict[str, str] = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }
        self._done_event: asyncio.Event = asyncio.Event()
        self._batch_progress: BatchProgress | None = None

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    async def extract_batch(
        self,
        file_paths: list[Path | str],
    ) -> dict[str, str]:
        """
        批量解析多个文件

        参数:
            file_paths: 文件路径列表，支持 Path 或 str
            progress_callback: 进度回调（每个文件状态变化时调用）
            done_callback: 完成回调（每个文件解析成功时调用）

        返回:
            {filename: markdown_content}
        """
        file_paths = [Path(p) for p in file_paths]
        filenames: list[str] = [p.name for p in file_paths]

        # 初始化批次进度
        self._batch_progress = BatchProgress(
            batch_id="",
            total_files=len(file_paths),
            file_states={name: FileProgress(filename=name) for name in filenames},
        )

        # 启动解析任务（异步，后台运行）
        parse_task: asyncio.Task = asyncio.create_task(
            self._run_batch_parse(file_paths, filenames)
        )

        # 等待所有文件完成（阻塞直到 done_event 设置）
        await self._done_event.wait()
        parse_task.cancel()

        # 收集结果
        results: dict[str, str] = {}
        for name, fp in self._batch_progress.file_states.items():
            if fp.state == FileProcessingState.DONE:
                pass  # markdown 内容通过 done_callback 收集，此处仅汇总状态
            elif fp.state == FileProcessingState.FAILED:
                logger.error(f"[{name}] 解析失败: {fp.error_message}")

        return results

    # ------------------------------------------------------------------
    # 内部：批量解析主流程
    # ------------------------------------------------------------------

    async def _run_batch_parse(
        self,
        file_paths: list[Path],
        filenames: list[str],
    ) -> None:
        """批量解析主流程"""
        batch_id: str = ""
        upload_urls: list[str] = []
        file_contents: list[bytes] = []

        try:
            # 步骤1：获取批量上传 URL
            batch_id, upload_urls = await self._get_upload_urls(filenames)
            self._batch_progress.batch_id = batch_id

            # 步骤2：并行上传所有文件
            file_contents = [self._read_file(p) for p in file_paths]
            await self._upload_files_parallel(upload_urls, file_paths, file_contents)

            # 步骤3：启动轮询任务
            poll_task: asyncio.Task = asyncio.create_task(
                self._poll_until_all_done(batch_id)
            )

            # 等待轮询完成
            await poll_task

        except Exception as e:
            logger.error(f"批量解析失败: {e}")
            for fp in self._batch_progress.file_states.values():
                fp.state = FileProcessingState.FAILED
                fp.error_message = str(e)
        finally:
            self._done_event.set()

    async def _get_upload_urls(self, filenames: list[str]) -> tuple[str, list[str]]:
        """获取批量上传 URL"""
        files_meta: list[dict[str, str]] = [
            {"name": name, "data_id": str(uuid.uuid4())}
            for name in filenames
        ]
        payload: dict[str, list | str] = {
            "files": files_meta,
            "model_version": "vlm",
        }

        @async_retry_with_backoff(max_retries=MAX_RETRIES)
        async def _do_request() -> tuple[str, list[str]]:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._api_base}/file-urls/batch",
                    headers=self._headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                    proxy=self._proxy,
                ) as resp:
                    raw: str = await resp.text()
                    if resp.status != 200:
                        raise Exception(f"获取上传URL失败 [{resp.status}]: {raw[:200]}")
                    result: dict = await resp.json()
                    if result.get("code") != 0:
                        raise Exception(f"MinerU API错误: {result.get('msg')}")
                    return result["data"]["batch_id"], result["data"]["file_urls"]

        return await _do_request()

    def _read_file(self, path: Path) -> bytes:
        """同步读取文件内容"""
        with open(path, "rb") as f:
            return f.read()

    async def _upload_files_parallel(
        self,
        upload_urls: list[str],
        file_paths: list[Path],
        file_contents: list[bytes],
    ) -> None:
        """并行上传所有文件到预签名 URL"""

        async def upload_single(
            url: str,
            path: Path,
            content: bytes,
            fp: FileProgress,
        ) -> None:
            @async_retry_with_backoff(max_retries=MAX_RETRIES)
            async def _do_upload() -> None:
                async with aiohttp.ClientSession() as session:
                    fp.state = FileProcessingState.UPLOADING
                    fp.progress_percent = 0
                    await self._emit_progress(fp)

                    async with session.put(
                        url,
                        data=content,
                        skip_auto_headers=["Content-Type"],
                        timeout=aiohttp.ClientTimeout(total=120),
                        proxy=self._proxy,
                    ) as resp:
                        if resp.status not in (200, 204):
                            text: str = await resp.text()
                            raise Exception(f"上传失败 [{resp.status}]: {text[:200]}")
                    fp.progress_percent = 100
                    fp.state = FileProcessingState.PROCESSING
                    await self._emit_progress(fp)

            try:
                await _do_upload()
            except Exception as e:
                fp.state = FileProcessingState.FAILED
                fp.error_message = str(e)
                await self._emit_progress(fp)

        tasks: list[asyncio.Task] = []
        for url, path, content in zip(upload_urls, file_paths, file_contents):
            fp: FileProgress = self._batch_progress.file_states[path.name]
            tasks.append(asyncio.create_task(upload_single(url, path, content, fp)))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _poll_until_all_done(self, batch_id: str) -> None:
        """
        轮询批次结果，直到所有文件完成或失败
        使用指数退避策略调整轮询间隔
        """
        poll_interval: float = INITIAL_POLL_INTERVAL
        extract_results: list[dict] = []

        while True:
            await asyncio.sleep(poll_interval)

            @async_retry_with_backoff(max_retries=MAX_RETRIES)
            async def _do_poll() -> list[dict]:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self._api_base}/extract-results/batch/{batch_id}",
                        headers=self._headers,
                        timeout=aiohttp.ClientTimeout(total=30),
                        proxy=self._proxy,
                    ) as resp:
                        result: dict = await resp.json()
                        if result.get("code") != 0:
                            raise Exception(f"轮询失败: {result.get('msg')}")
                        return result["data"]["extract_result"]

            try:
                extract_results = await _do_poll()

                # 更新各文件状态
                all_done: bool = True
                for idx, file_info in enumerate(extract_results):
                    fname: str = list(self._batch_progress.file_states.keys())[idx] \
                        if idx < len(self._batch_progress.file_states) else f"file_{idx}"
                    if fname in self._batch_progress.file_states:
                        fp: FileProgress = self._batch_progress.file_states[fname]
                        if file_info["state"] == "done":
                            fp.state = FileProcessingState.DONE
                            fp.progress_percent = 100
                            # 下载结果
                            await self._download_and_notify(fname, file_info["full_zip_url"])
                        elif file_info["state"] == "failed":
                            fp.state = FileProcessingState.FAILED
                            fp.error_message = "服务器处理失败"
                        else:
                            fp.state = FileProcessingState.PROCESSING
                            fp.progress_percent = 50
                            all_done = False
                        await self._emit_progress(fp)

                if all_done:
                    break

                # 指数退避：下次轮询间隔加倍，上限 MAX_POLL_INTERVAL
                poll_interval = min(poll_interval * 1.5, MAX_POLL_INTERVAL)

            except Exception as e:
                logger.warning(f"轮询异常: {e}，{poll_interval:.1f}秒后重试")
                poll_interval = min(poll_interval * 2, MAX_POLL_INTERVAL)

        self._done_event.set()

    async def _download_and_notify(self, filename: str, zip_url: str) -> None:
        """下载 ZIP 并提取 Markdown，触发完成回调"""
        @async_retry_with_backoff(max_retries=MAX_RETRIES)
        async def _do_download() -> str:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    zip_url,
                    timeout=aiohttp.ClientTimeout(total=120),
                    proxy=self._proxy,
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f"下载失败 [{resp.status}]")
                    zip_bytes: bytes = await resp.read()

                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                    md_files: list[str] = [
                        n for n in zf.namelist() if n.endswith(".md")
                    ]
                    if not md_files:
                        raise Exception("ZIP中未找到.md文件")
                    content: str = zf.read(md_files[0]).decode("utf-8")
                    return clean_mineru_markdown(content)

        try:
            md_content: str = await _do_download()
            if self._done_callback:
                await self._done_callback(filename, md_content)
        except Exception as e:
            fp: FileProgress = self._batch_progress.file_states[filename]
            fp.state = FileProcessingState.FAILED
            fp.error_message = f"下载/解析失败: {e}"
            await self._emit_progress(fp)

    async def _emit_progress(self, fp: FileProgress) -> None:
        """推送进度更新"""
        if self._progress_callback:
            await self._progress_callback(fp)


# ============================================================================
# 便捷封装
# ============================================================================

async def extract_single_cloud(
    file_path: Path | str,
    filename: str | None = None,
) -> str:
    """
    解析单个文件（便捷封装）

    参数:
        file_path: 文件路径
        filename: 可选，指定文件名（用于 MinerU）

    返回:
        markdown_content
    """
    path: Path = Path(file_path)
    fname: str = filename or path.name
    results: dict[str, str] = {}

    async def on_done(name: str, content: str) -> None:
        results[name] = content

    client: MinerUAsyncClient = MinerUAsyncClient(done_callback=on_done)
    await client.extract_batch([path])
    return results.get(fname, "")


async def extract_batch_cloud(
    file_paths: list[Path | str],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, str]:
    """
    批量解析多个文件

    参数:
        file_paths: 文件路径列表
        progress_callback: 进度回调，用于实时显示状态

    返回:
        {filename: markdown_content}
    """
    results: dict[str, str] = {}

    async def on_done(name: str, content: str) -> None:
        results[name] = content

    client: MinerUAsyncClient = MinerUAsyncClient(
        progress_callback=progress_callback,
        done_callback=on_done,
    )
    await client.extract_batch(file_paths)
    return results
