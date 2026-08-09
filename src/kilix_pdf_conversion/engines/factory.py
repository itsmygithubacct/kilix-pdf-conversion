from __future__ import annotations

from ..config import AppConfig
from ..models import EngineName
from .base import ConversionEngine
from .granite_engine import GraniteEngine
from .marker_engine import MarkerEngine
from .pymupdf_engine import PyMuPDFEngine


def create_engine(name: EngineName, config: AppConfig) -> ConversionEngine:
    if name is EngineName.PYMUPDF:
        return PyMuPDFEngine(config.pymupdf)
    if name in {EngineName.GRANITE_HYBRID, EngineName.GRANITE_PURE}:
        return GraniteEngine(name, config.granite)
    if name is EngineName.MARKER:
        return MarkerEngine(config.marker)
    raise ValueError(f"unsupported engine: {name}")
