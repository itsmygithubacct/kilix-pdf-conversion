"""Retain optional enrichment in the supported Docling VLM lifecycle."""

from __future__ import annotations

from functools import cache
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

from .base import EngineUnavailable

if TYPE_CHECKING:
    from docling.datamodel.pipeline_options import VlmPipelineOptions
    from docling.pipeline.vlm_pipeline import VlmPipeline


DOCLING_VERSION = "2.118.0"


@cache
def chart_enrichment_pipeline(
    base_pipeline: type[VlmPipeline] | None = None,
) -> type[VlmPipeline]:
    """Return a stable pipeline class without loading any model.

    Docling 2.118.0 constructs enrichment in ConvertPipeline, then clears it
    in VlmPipeline after initializing the page model. Retain that same list
    across initialization so Docling executes it before unloading backends.
    This adapter relies on the initializer contract of this exact version.
    A custom VlmPipeline subclass may supply its own page-model initializer;
    wrapping it here retains enrichment without initializing that model twice.
    """
    try:
        installed = version("docling-slim")
    except PackageNotFoundError as error:
        raise EngineUnavailable("Chart enrichment requires docling-slim==2.118.0") from error
    if installed != DOCLING_VERSION:
        raise EngineUnavailable(
            f"Chart enrichment requires docling-slim=={DOCLING_VERSION}; found {installed}"
        )

    from docling.pipeline.vlm_pipeline import VlmPipeline

    pipeline_base = VlmPipeline if base_pipeline is None else base_pipeline
    if not issubclass(pipeline_base, VlmPipeline):
        raise TypeError("The enrichment base must derive from Docling VlmPipeline")

    class ChartEnrichmentVlmPipeline(pipeline_base):
        def __init__(self, pipeline_options: VlmPipelineOptions) -> None:
            self._kilix_saved_enrichment = None
            self._kilix_retain_enrichment = (
                pipeline_options.do_picture_classification
                or pipeline_options.do_picture_description
                or pipeline_options.do_chart_extraction
            )
            initialized = False
            try:
                super().__init__(pipeline_options)
                if self._kilix_retain_enrichment:
                    if self._kilix_saved_enrichment is None or not self._kilix_saved_enrichment:
                        raise RuntimeError("Docling did not expose the expected enrichment stages")
                    if self.enrichment_pipe:
                        raise RuntimeError("Docling VLM enrichment initialization contract changed")
                    self.enrichment_pipe = self._kilix_saved_enrichment
                initialized = True
            finally:
                if not initialized:
                    # Release retained enrichment models if any constructor failed.
                    self.enrichment_pipe = []
                self._kilix_saved_enrichment = None
                self._kilix_retain_enrichment = False

        def _initialize_new_runtime_system(self, pipeline_options: VlmPipelineOptions) -> None:
            if self._kilix_retain_enrichment:
                self._kilix_saved_enrichment = self.enrichment_pipe
            super()._initialize_new_runtime_system(pipeline_options)

        def _initialize_legacy_vlm_models(self, pipeline_options: VlmPipelineOptions) -> None:
            if self._kilix_retain_enrichment:
                self._kilix_saved_enrichment = self.enrichment_pipe
            super()._initialize_legacy_vlm_models(pipeline_options)

    return ChartEnrichmentVlmPipeline
