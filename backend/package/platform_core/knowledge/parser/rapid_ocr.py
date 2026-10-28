"""
RapidOCR 解析器 - 纯OCR文字识别

使用 RapidOCR (PP-OCRv5) 进行文字识别
"""

import os
import time
from contextlib import closing
from pathlib import Path

import pypdfium2 as pdfium
from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR

from platform_core.knowledge.parser.base import BaseDocumentProcessor, OCRException
from platform_core.knowledge.parser.capabilities import get_parser_capability
from platform_core.utils import logger

_CAPABILITY = get_parser_capability("rapid_ocr")


class RapidOCRParser(BaseDocumentProcessor):
    """RapidOCR 解析器 - 使用 ONNX 模型进行文字识别"""

    service_name = _CAPABILITY.service_name
    display_name = _CAPABILITY.display_name
    supported_extensions = list(_CAPABILITY.supported_extensions)

    def __init__(self, det_box_thresh: float = 0.3):
        self.ocr = None
        self.det_box_thresh = det_box_thresh

    @staticmethod
    def _resolve_model_dir() -> Path:
        """获取并确保可写的 RapidOCR 模型存放目录。"""
        env_dir = os.getenv("RAPIDOCR_MODEL_DIR")
        if env_dir:
            model_dir = Path(env_dir).expanduser().resolve()
            model_dir.mkdir(parents=True, exist_ok=True)
            return model_dir

        try:
            import rapidocr

            default_dir = Path(rapidocr.__file__).resolve().parent / "models"
            if default_dir.exists() and os.access(default_dir, os.W_OK):
                return default_dir
        except Exception:
            pass

        cache_dir = Path.home() / ".cache" / "rapidocr" / "models"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def _get_model_params(self) -> dict[str, object]:
        model_dir = self._resolve_model_dir()
        return {
            "Global.model_root_dir": str(model_dir),
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Det.lang_type": LangDet.CH,
            "Det.model_type": ModelType.MOBILE,
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.box_thresh": self.det_box_thresh,
            "Cls.engine_type": EngineType.ONNXRUNTIME,
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Rec.lang_type": LangRec.CH,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
        }

    def check_health(self) -> dict:
        """报告本地组件状态，避免选择器刷新时重复加载模型。"""

        return {
            "status": "healthy",
            "message": "RapidOCR PP-OCRv5 组件可用",
            "details": {
                "ocr_version": "PP-OCRv5",
                "engine": "onnxruntime",
                "det_box_thresh": self.det_box_thresh,
            },
        }

    def _load_model(self):
        """延迟加载 OCR 模型"""
        if self.ocr is not None:
            return

        logger.info("加载 RapidOCR 模型...")

        try:
            self.ocr = RapidOCR(params=self._get_model_params())
            logger.info(f"RapidOCR PP-OCRv5 模型加载成功 (det_box_thresh={self.det_box_thresh})")
        except Exception as e:
            raise OCRException(f"RapidOCR模型加载失败: {str(e)}", self.get_service_name(), "load_failed")

    def process_image(self, image, params: dict | None = None) -> str:
        """
        处理单张图像并提取文本

        Args:
            image: 图像数据,支持:
                  - str: 图像文件路径
                  - PIL.Image: PIL图像对象
                  - numpy.ndarray: numpy图像数组
            params: 处理参数 (当前未使用)

        Returns:
            str: 提取的文本内容
        """
        self._load_model()

        try:
            # 原生支持 PIL/ndarray，保留其颜色空间转换并省去 PNG 往返。
            started = time.monotonic()
            result = self.ocr(image)
            label = os.path.basename(image) if isinstance(image, str) else "内存图像"
            if result.txts:
                logger.info("RapidOCR 成功: {} ({:.2f}s)", label, time.monotonic() - started)
                return "\n".join(result.txts)
            logger.warning("RapidOCR 未识别到文本: {}", label)
            return ""

        except Exception as e:
            error_msg = f"图像OCR处理失败: {str(e)}"
            logger.error(error_msg)
            raise OCRException(error_msg, self.get_service_name(), "processing_failed")

    def process_pdf(self, pdf_path: str, params: dict | None = None) -> str:
        """
        处理 PDF 文件并提取文本 (流式处理,避免内存占用)

        Args:
            pdf_path: PDF 文件路径
            params: 处理参数
                - zoom_x: 渲染缩放倍数 (默认 2)

        Returns:
            str: 提取的文本
        """
        if not os.path.exists(pdf_path):
            raise OCRException(f"PDF 文件不存在: {pdf_path}", self.get_service_name(), "file_not_found")

        params = params or {}
        zoom_x = params.get("zoom_x", 2)
        prefer_text = params.get("prefer_text_layer", True)
        if not isinstance(prefer_text, bool):
            raise ValueError("prefer_text_layer 必须是布尔值")
        started = time.monotonic()

        try:
            all_text = []
            text_pages = 0
            with pdfium.PdfDocument(pdf_path) as pdf_doc:
                total_pages = len(pdf_doc)
                logger.info(f"开始处理 PDF: {os.path.basename(pdf_path)} ({total_pages} 页)")
                for page_num in range(total_pages):
                    with closing(pdf_doc[page_num]) as page:
                        text = ""
                        if prefer_text:
                            with closing(page.get_textpage()) as text_page:
                                candidate = text_page.get_text_bounded().strip()
                            readable = sum(char.isalnum() for char in candidate)
                            page_area = page.get_width() * page.get_height()
                            image_dominates = False
                            for image_object in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE]):
                                left, bottom, right, top = image_object.get_bounds()
                                if (right - left) * (top - bottom) >= page_area * 0.5:
                                    image_dominates = True
                                    break
                            # 少量页眉、乱码或仅标题的扫描页仍需 OCR。
                            if (
                                readable >= 80
                                and not image_dominates
                                and candidate.count("\ufffd") <= len(candidate) * 0.02
                            ):
                                text = candidate
                                text_pages += 1
                        if not text:
                            bitmap = page.render(scale=zoom_x)
                            try:
                                image = bitmap.to_pil()
                                try:
                                    text = self.process_image(image)
                                finally:
                                    image.close()
                            finally:
                                bitmap.close()
                        all_text.append(text)

                    if (page_num + 1) % 10 == 0:
                        logger.info(f"已处理 {page_num + 1}/{total_pages} 页")

            result_text = "\n\n".join(all_text)
            logger.info(
                "PDF OCR 完成: {} - {} 字符，文字层 {}/{} 页，耗时 {:.2f}s",
                os.path.basename(pdf_path),
                len(result_text),
                text_pages,
                total_pages,
                time.monotonic() - started,
            )
            return result_text

        except OCRException:
            raise
        except Exception as e:
            error_msg = f"PDF OCR 处理失败: {str(e)}"
            logger.error(error_msg)
            raise OCRException(error_msg, self.get_service_name(), "pdf_processing_failed")

    def process_file(self, file_path: str, params: dict | None = None) -> str:
        """
        处理文件 (PDF 或图像)

        Args:
            file_path: 文件路径
            params: 处理参数

        Returns:
            str: 提取的文本
        """
        file_ext = Path(file_path).suffix.lower()

        if not self.supports_file_type(file_ext):
            raise OCRException(f"不支持的文件类型: {file_ext}", self.get_service_name(), "unsupported_file_type")

        if file_ext == ".pdf":
            return self.process_pdf(file_path, params)
        else:
            return self.process_image(file_path, params)
