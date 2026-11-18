"""按 PDF 文本层和版面特征选择本地或结构化解析器。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError

from platform_core.knowledge.parser.base import BaseDocumentProcessor, DocumentParserException
from platform_core.knowledge.parser.capabilities import get_parser_capability
from platform_core.knowledge.parser.result import ParsedDocument
from platform_core.knowledge.utils.pdf_utils import recover_pdf_bytes_after_eof

_CAPABILITY = get_parser_capability("auto")
_COLUMN_GAP_PATTERN = re.compile(r"\S[^\n]{0,120}\s{4,}\S")
_CID_GLYPH_PATTERN = re.compile(r"/G[0-9A-Fa-f]{2,6}(?=$|[\s/])")


@dataclass(frozen=True, slots=True)
class PDFRoutingDecision:
    """不含原文的 PDF 路由结论和可审计特征。"""

    route: str
    total_pages: int
    sampled_pages: int
    text_page_ratio: float
    average_text_chars: float
    image_page_ratio: float
    column_page_ratio: float
    failed_sample_pages: int = 0
    cid_glyph_pages: int = 0
    trailing_data_recovered: bool = False

    def as_metadata(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "total_pages": self.total_pages,
            "sampled_pages": self.sampled_pages,
            "text_page_ratio": round(self.text_page_ratio, 4),
            "average_text_chars": round(self.average_text_chars, 2),
            "image_page_ratio": round(self.image_page_ratio, 4),
            "column_page_ratio": round(self.column_page_ratio, 4),
            "failed_sample_pages": self.failed_sample_pages,
            "cid_glyph_pages": self.cid_glyph_pages,
            "trailing_data_recovered": self.trailing_data_recovered,
        }


class IntelligentDocumentRouter(BaseDocumentProcessor):
    """数字 PDF 走原生文本，扫描件走 OCR，复杂版面走已配置版面解析器。"""

    service_name = _CAPABILITY.service_name
    display_name = _CAPABILITY.display_name
    supported_extensions = list(_CAPABILITY.supported_extensions)

    def __init__(
        self,
        *,
        scan_engine: str = "rapid_ocr",
        complex_engine: str = "docling_pdf",
        complex_engines: tuple[str, ...] | list[str] | None = None,
        engine_kwargs: dict[str, dict[str, Any]] | None = None,
    ):
        resolved_complex_engines = tuple(complex_engines or (complex_engine, scan_engine))
        resolved_complex_engines = tuple(dict.fromkeys(resolved_complex_engines))
        if not resolved_complex_engines:
            raise ValueError("复杂版面至少需要一个解析目标")
        if scan_engine == self.service_name or self.service_name in resolved_complex_engines:
            raise ValueError("智能路由器不能递归委派给 auto")
        self.scan_engine = scan_engine
        self.complex_engine = resolved_complex_engines[0]
        self.complex_engines = resolved_complex_engines
        self.engine_kwargs = {key: dict(value) for key, value in (engine_kwargs or {}).items()}

    def process_file(self, file_path: str, params: dict[str, Any] | None = None) -> str:
        return self.process_file_result(file_path, params).markdown

    def process_file_result(self, file_path: str, params: dict[str, Any] | None = None) -> ParsedDocument:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix != ".pdf":
            result = self._delegate(self.scan_engine, file_path, params)
            return _with_routing_metadata(result, route="image_ocr", engine=self.scan_engine)

        decision = inspect_pdf_routing(path)
        if decision.route == "native_text":
            from platform_core.knowledge.parser.unified import pdfreader_result

            result = pdfreader_result(path)
            engine = "native_pdf"
        elif decision.route == "complex_layout":
            engine, result, attempts = self._delegate_complex(file_path, params)
        else:
            engine = self.scan_engine
            result = self._delegate(engine, file_path, params)
        return _with_routing_metadata(
            result,
            route=decision.route,
            engine=engine,
            decision=decision,
            attempts=attempts if decision.route == "complex_layout" else None,
        )

    def check_health(self) -> dict[str, Any]:
        from platform_core.knowledge.parser.factory import DocumentProcessorFactory

        scan_health = DocumentProcessorFactory.check_health(
            self.scan_engine,
            **self.engine_kwargs.get(self.scan_engine, {}),
        )
        complex_health_results = {}
        for engine_id in self.complex_engines:
            if engine_id == self.scan_engine:
                complex_health_results[engine_id] = scan_health
            else:
                complex_health_results[engine_id] = DocumentProcessorFactory.check_health(
                    engine_id,
                    **self.engine_kwargs.get(engine_id, {}),
                )
        healthy_statuses = {"healthy", "configured"}
        scan_healthy = scan_health.get("status") in healthy_statuses
        structure_engines = tuple(engine_id for engine_id in self.complex_engines if engine_id != self.scan_engine)
        complex_healthy = any(
            complex_health_results[engine_id].get("status") in healthy_statuses for engine_id in structure_engines
        )
        fully_healthy = scan_healthy and complex_healthy
        return {
            "status": "healthy" if fully_healthy else "degraded",
            "message": "智能路由具备本地结构化解析路径" if fully_healthy else "智能路由仅剩非结构化回退路径",
            "details": {
                "native_engine": "native_pdf",
                "scan_engine": self.scan_engine,
                "scan_status": scan_health.get("status", "unknown"),
                "complex_engines": list(self.complex_engines),
                "complex_statuses": {
                    engine_id: result.get("status", "unknown") for engine_id, result in complex_health_results.items()
                },
            },
        }

    def _delegate_complex(
        self,
        file_path: str,
        params: dict[str, Any] | None,
    ) -> tuple[str, ParsedDocument, tuple[dict[str, str], ...]]:
        attempts: list[dict[str, str]] = []
        last_error: Exception | None = None
        for engine_id in self.complex_engines:
            try:
                result = self._delegate(engine_id, file_path, params)
                attempts.append({"engine": engine_id, "status": "succeeded"})
                return engine_id, result, tuple(attempts)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                attempts.append(
                    {
                        "engine": engine_id,
                        "status": "failed",
                        "error_code": str(getattr(exc, "status_code", None) or type(exc).__name__),
                    }
                )
        raise DocumentParserException(
            "复杂版面解析目标均不可用",
            self.service_name,
            "all_complex_engines_failed",
        ) from last_error

    def _delegate(
        self,
        engine_id: str,
        file_path: str,
        params: dict[str, Any] | None,
    ) -> ParsedDocument:
        from platform_core.knowledge.parser.factory import DocumentProcessorFactory

        capability = get_parser_capability(engine_id)
        if Path(file_path).suffix.lower() not in capability.supported_extensions:
            raise DocumentParserException(
                f"路由目标 {engine_id} 不支持 {Path(file_path).suffix.lower()}",
                self.service_name,
                "unsupported_route",
            )
        processor = DocumentProcessorFactory.get_processor(engine_id, **self.engine_kwargs.get(engine_id, {}))
        delegate_params = dict(params or {})
        delegate_params["ocr_engine"] = engine_id
        return processor.process_file_result(file_path, delegate_params)


def inspect_pdf_routing(path: Path, *, sample_limit: int = 12) -> PDFRoutingDecision:
    """只读取少量页面结构，确定数字、扫描/混合或复杂版面路线。"""
    if sample_limit < 1:
        raise ValueError("sample_limit 必须大于 0")
    try:
        with path.open("rb") as source:
            reader, trailing_data_recovered = read_pdf_with_trailing_data_recovery(source)
            total_pages = len(reader.pages)
            sampled = [reader.pages[index] for index in range(min(total_pages, sample_limit))]
            text_pages = 0
            total_text_chars = 0
            image_pages = 0
            column_pages = 0
            failed_sample_pages = 0
            cid_glyph_pages = 0
            for page in sampled:
                try:
                    text = (page.extract_text(extraction_mode="plain") or "").strip()
                except Exception:  # 单页损坏应降级到 OCR，不应阻断整篇路由
                    text = ""
                    failed_sample_pages += 1
                layout_text = _extract_layout_text(page) if text else ""
                readable = sum(character.isalnum() for character in text)
                total_text_chars += readable
                cid_tokens = _CID_GLYPH_PATTERN.findall(text)
                cid_token_chars = sum(len(token) for token in cid_tokens)
                cid_glyph_heavy = len(cid_tokens) >= 8 and cid_token_chars >= max(1, len(text) * 0.08)
                if cid_glyph_heavy:
                    cid_glyph_pages += 1
                if readable >= 80 and text.count("\ufffd") <= max(1, len(text) * 0.02) and not cid_glyph_heavy:
                    text_pages += 1
                if _page_has_image(page):
                    image_pages += 1
                if _COLUMN_GAP_PATTERN.search(layout_text):
                    column_pages += 1
    except PdfReadError as exc:
        raise DocumentParserException(
            f"PDF 页面结构异常: {exc}",
            "auto",
            "invalid_pdf_structure",
        ) from exc
    except Exception as exc:
        raise DocumentParserException(
            f"PDF 智能路由检查失败: {exc}",
            "auto",
            "routing_inspection_failed",
        ) from exc

    sampled_pages = len(sampled)
    if sampled_pages == 0:
        route = "scanned_or_mixed"
        text_ratio = average_chars = image_ratio = column_ratio = 0.0
    else:
        text_ratio = text_pages / sampled_pages
        average_chars = total_text_chars / sampled_pages
        image_ratio = image_pages / sampled_pages
        column_ratio = column_pages / sampled_pages
        if text_ratio < 0.9 or average_chars < 100:
            route = "scanned_or_mixed"
        elif image_ratio >= 0.35 or column_ratio >= 0.25:
            route = "complex_layout"
        else:
            route = "native_text"
    return PDFRoutingDecision(
        route=route,
        total_pages=total_pages,
        sampled_pages=sampled_pages,
        text_page_ratio=text_ratio,
        average_text_chars=average_chars,
        image_page_ratio=image_ratio,
        column_page_ratio=column_ratio,
        failed_sample_pages=failed_sample_pages,
        cid_glyph_pages=cid_glyph_pages,
        trailing_data_recovered=trailing_data_recovered,
    )


def read_pdf_with_trailing_data_recovery(source: Any) -> tuple[PdfReader, bool]:
    """遇到 EOF 后附加的下载追踪尾部时，仅在内存中恢复合法 PDF。"""
    recovered_bytes = recover_pdf_bytes_after_eof(source)
    if recovered_bytes is not None:
        return PdfReader(BytesIO(recovered_bytes)), True

    source.seek(0)
    try:
        return PdfReader(source), False
    except PdfStreamError as original_error:
        recovered_bytes = recover_pdf_bytes_after_eof(source, force=True)
        if recovered_bytes is None:
            raise original_error
        return PdfReader(BytesIO(recovered_bytes)), True


def _page_has_image(page: Any) -> bool:
    try:
        resources = page.get("/Resources")
        resources = resources.get_object() if hasattr(resources, "get_object") else resources
        xobjects = resources.get("/XObject") if resources else None
        xobjects = xobjects.get_object() if hasattr(xobjects, "get_object") else xobjects
        if not xobjects:
            return False
        return any(
            str((value.get_object() if hasattr(value, "get_object") else value).get("/Subtype")) == "/Image"
            for value in xobjects.values()
        )
    except Exception:
        return False


def _extract_layout_text(page: Any) -> str:
    """布局文本只用于路由特征，提取失败时不阻断主文本/OCR判定。"""
    try:
        return (
            page.extract_text(
                extraction_mode="layout",
                layout_mode_space_vertically=False,
            )
            or ""
        )
    except Exception:
        return ""


def _with_routing_metadata(
    result: ParsedDocument,
    *,
    route: str,
    engine: str,
    decision: PDFRoutingDecision | None = None,
    attempts: tuple[dict[str, str], ...] | None = None,
) -> ParsedDocument:
    metadata = dict(result.source_metadata)
    metadata.update(
        {
            "routing_mode": "auto",
            "routing_decision": route,
            "routing_engine": engine,
        }
    )
    if decision is not None:
        metadata["routing_features"] = decision.as_metadata()
    if attempts is not None:
        metadata["routing_attempts"] = [dict(attempt) for attempt in attempts]
    return ParsedDocument(
        markdown=result.markdown,
        parser_name=result.parser_name,
        parser_version=result.parser_version,
        source_metadata=metadata,
        blocks=result.blocks,
    )
