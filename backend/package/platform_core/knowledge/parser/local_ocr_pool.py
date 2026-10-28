"""独立进程运行本地 OCR，避免共享推理实例和 PDFium 的线程状态。"""

import asyncio
import atexit
import multiprocessing
import os
import weakref
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

_pool: ProcessPoolExecutor | None = None
_capacity: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
OCR_WORKERS = max(1, min(int(os.getenv("KNOWLEDGE_OCR_WORKERS", "4")), 8))


def _process_local_document(path: str, params: dict) -> str:
    """每个进程只执行一份文档，复用该进程自己的模型。"""
    from platform_core.knowledge.parser.factory import DocumentProcessorFactory

    kwargs = params.pop("_ocr_processor_kwargs", {})
    return DocumentProcessorFactory.process_file("rapid_ocr", path, params, kwargs)


def _shutdown_pool() -> None:
    """退出时回收子进程。"""
    if _pool is not None:
        _pool.shutdown(wait=True, cancel_futures=True)


async def process_local_document(path: str, params: dict) -> str:
    """限制全局在途文档数，取消时等待只读解析完成再释放临时文件。"""
    global _pool
    loop = asyncio.get_running_loop()
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=OCR_WORKERS, mp_context=multiprocessing.get_context("spawn"))
        atexit.register(_shutdown_pool)
    if loop not in _capacity:
        _capacity[loop] = asyncio.Semaphore(OCR_WORKERS)
    async with _capacity[loop]:
        pool = _pool
        try:
            future = loop.run_in_executor(pool, _process_local_document, path, dict(params))
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                # 父层 finally 会删除下载文件，因此不能让子进程继续读取已删除的路径。
                await asyncio.shield(future)
                raise
        except BrokenProcessPool:
            if _pool is pool:
                _pool = None
                pool.shutdown(wait=False, cancel_futures=True)
            raise
