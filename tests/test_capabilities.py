from __future__ import annotations

from kilix_pdf_conversion.capabilities import available_engine_names
from kilix_pdf_conversion.models import EngineName


def test_available_engine_names_maps_shared_docling_runtime() -> None:
    capabilities = {
        "base": {
            "pymupdf": {"available": True},
            "pymupdf4llm": {"available": True},
        },
        "optional": {
            "docling": {"available": True},
            "marker": {"available": False},
        },
    }

    assert available_engine_names(capabilities) == {
        EngineName.PYMUPDF,
        EngineName.GRANITE_HYBRID,
        EngineName.GRANITE_PURE,
    }
