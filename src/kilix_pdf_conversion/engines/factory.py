from __future__ import annotations

from ..config import AppConfig
from ..models import EngineName
from .base import ConversionEngine
from .granite_engine import GraniteEngine
from .marker_engine import MarkerEngine
from .page_ocr_engine import PageOCREngine
from .pymupdf_engine import PyMuPDFEngine


def create_engine(name: EngineName, config: AppConfig) -> ConversionEngine:
    if name is EngineName.PYMUPDF:
        return PyMuPDFEngine(config.pymupdf)
    if name in {EngineName.GRANITE_HYBRID, EngineName.GRANITE_PURE}:
        return GraniteEngine(name, config.granite)
    if name is EngineName.MARKER:
        return MarkerEngine(config.marker)
    if name is EngineName.PAGE_OCR:
        return PageOCREngine(config.ocr)
    raise ValueError(f"unsupported engine: {name}")
