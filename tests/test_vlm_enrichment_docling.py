"""Real Docling lifecycle/crops/serialization, with neural predictions stubbed.

Requires the optional docling-slim 2.118.0 test environment. These generated
PDFs have fixed bar-chart/table regions. Stub predictions test plumbing;
they do not measure either model's classification or chart-value accuracy.
"""

from __future__ import annotations

import gc
import importlib.util
import weakref
from collections import Counter

import pymupdf
import pytest

if importlib.util.find_spec("docling") is None:
    pytest.skip("requires the optional Docling test runtime", allow_module_level=True)

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import ConversionStatus, InputFormat, VlmPrediction
from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.models.inference_engines.image_classification.base import (
    ImageClassificationEngineOutput,
)
from docling.models.stages.chart_extraction.granite_vision import (
    ChartExtractionModelGraniteVisionV4,
)
from docling.pipeline.base_pipeline import PaginatedPipeline
from docling.pipeline.vlm_pipeline import VlmPipeline
from docling_core.types.doc import PictureMeta, TableCell, TableData, TabularChartMetaField
from docling_core.types.doc.base import ImageRefMode

from kilix_pdf_conversion.engines.vlm_enrichment import chart_enrichment_pipeline

DOCTAGS = (
    "<doctag><picture><loc_50><loc_50><loc_225><loc_250></picture>"
    "<picture><loc_275><loc_50><loc_450><loc_250></picture></doctag>"
)


@pytest.fixture
def fixture_pdf(tmp_path):
    path = tmp_path / "chart-and-table.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=500)
        page.draw_rect((50, 50, 225, 250), fill=(1, 0.95, 0.95), color=None)
        for left, top in [(80, 150), (120, 100), (160, 175)]:
            page.draw_rect((left, top, left + 20, 225), fill=(0.8, 0.1, 0.1), color=None)
        page.draw_rect((275, 50, 450, 250), fill=(0.95, 0.95, 1), color=None)
        for y in (80, 120, 160, 200):
            page.draw_line((290, y), (435, y), color=(0.1, 0.1, 0.8))
        page.draw_line((365, 80), (365, 200), color=(0.1, 0.1, 0.8))
        page.insert_text((300, 105), "A    12", fontsize=10)
        page.insert_text((300, 145), "B    20", fontsize=10)
        pdf.save(path)
    return path


@pytest.fixture
def models(monkeypatch, tmp_path):
    events = []
    failures = set()
    engine_refs = []

    class PageModel:
        def __init__(self, **_kwargs):
            events.append(("construct", "page"))
            if "page_init" in failures:
                raise RuntimeError("page construction failed")

        def __call__(self, _result, pages):
            for page in pages:
                events.append(("run", "page"))
                page.predictions.vlm_response = VlmPrediction(text=DOCTAGS)
                yield page

    class ClassifierEngine:
        def __init__(self):
            events.append(("construct", "classifier"))
            engine_refs.append(weakref.ref(self))

        def initialize(self):
            if "classifier_init" in failures:
                raise RuntimeError("classifier construction failed")

        def get_label_mapping(self):
            return {5: "bar_chart", 7: "table"}

        def predict_batch(self, inputs):
            events.append(("run", "classifier"))
            if "classifier_run" in failures:
                raise RuntimeError("classifier prediction failed")
            outputs = []
            for item in inputs:
                assert item.image.mode == "RGB"
                assert item.image.size == (175, 200)
                red, _green, blue = item.image.getpixel((10, 10))
                label = 5 if red > blue else 7
                outputs.append(ImageClassificationEngineOutput(
                    label_ids=[label, 7 if label == 5 else 5], scores=[0.99, 0.01]
                ))
            return outputs

    def load_chart(_self, _path):
        events.append(("construct", "chart"))
        if "chart_init" in failures:
            raise RuntimeError("chart construction failed")

    def predict_chart(self, _doc=None, element_batch=(), **_kwargs):
        if not self.enabled:
            yield from (element.item for element in element_batch)
            return
        for element in element_batch:
            events.append(("run", "chart"))
            assert element.image.size == (175, 200)
            assert element.item.meta.classification.get_main_prediction().class_name == "bar_chart"
            if "chart_run" in failures:
                raise RuntimeError("chart prediction failed")
            cells = []
            for row, values in enumerate((("metric", "value"), ("widgets", "12"))):
                for col, text in enumerate(values):
                    cells.append(TableCell(
                        text=text, start_row_offset_idx=row, end_row_offset_idx=row + 1,
                        start_col_offset_idx=col, end_col_offset_idx=col + 1,
                        column_header=row == 0,
                    ))
            element.item.meta.tabular_chart = TabularChartMetaField(
                chart_data=TableData(num_rows=2, num_cols=2, table_cells=cells)
            )
            yield element.item

    original_unload = PaginatedPipeline._unload

    def unload(self, result):
        events.append(("unload", "backend"))
        return original_unload(self, result)

    monkeypatch.setattr("docling.pipeline.vlm_pipeline.VlmConvertModel", PageModel)
    monkeypatch.setattr("docling.pipeline.vlm_pipeline.HuggingFaceTransformersVlmModel", PageModel)
    monkeypatch.setattr(
        "docling.models.stages.picture_classifier.document_picture_classifier."
        "create_image_classification_engine", lambda **_kwargs: ClassifierEngine()
    )
    monkeypatch.setattr(ChartExtractionModelGraniteVisionV4, "download_models",
                        classmethod(lambda cls, **_kwargs: tmp_path))
    monkeypatch.setattr(ChartExtractionModelGraniteVisionV4, "_load_model", load_chart)
    monkeypatch.setattr(ChartExtractionModelGraniteVisionV4, "__call__", predict_chart)
    monkeypatch.setattr(PaginatedPipeline, "_unload", unload)
    chart_enrichment_pipeline.cache_clear()
    yield events, failures, engine_refs
    chart_enrichment_pipeline.cache_clear()


def converter(*, fixed=True, charts=True, classify=False, legacy=False):
    options = VlmPipelineOptions(
        accelerator_options=AcceleratorOptions(device="cpu", num_threads=2),
        do_chart_extraction=charts,
        do_picture_classification=classify,
        generate_page_images=True,
        generate_picture_images=True,
    )
    if not legacy:
        options.vlm_options = VlmConvertOptions.from_preset("granite_docling")
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(
        backend=PyPdfiumDocumentBackend,
        pipeline_cls=chart_enrichment_pipeline() if fixed else VlmPipeline,
        pipeline_options=options,
    )})


def test_original_discards_initialized_enrichment(models, fixture_pdf):
    events, _, _ = models
    result = converter(fixed=False).convert(fixture_pdf, raises_on_error=False)
    assert result.status == ConversionStatus.SUCCESS
    assert len(result.document.pictures) == 2
    assert ("construct", "classifier") in events and ("construct", "chart") in events
    assert ("run", "classifier") not in events and ("run", "chart") not in events
    assert all(picture.meta is None for picture in result.document.pictures)


@pytest.mark.parametrize("legacy", [False, True])
def test_chart_flag_runs_each_stage_once_before_unload_and_serializes(
    models, fixture_pdf, tmp_path, legacy
):
    events, _, _ = models
    pipeline_type = chart_enrichment_pipeline()
    assert chart_enrichment_pipeline() is pipeline_type
    assert events == []  # Resolving the class must not construct a model.
    result = converter(legacy=legacy).convert(fixture_pdf, raises_on_error=False)
    assert result.status == ConversionStatus.SUCCESS
    counts = Counter(events)
    for stage in ("page", "classifier", "chart"):
        assert counts[("construct", stage)] == 1
        assert counts[("run", stage)] == 1
    assert events.index(("run", "classifier")) < events.index(("run", "chart"))
    assert events.index(("run", "chart")) < events.index(("unload", "backend"))
    first, second = result.document.pictures
    assert isinstance(first.meta, PictureMeta)
    assert first.meta.classification.get_main_prediction().class_name == "bar_chart"
    assert second.meta.classification.get_main_prediction().class_name == "table"
    assert first.meta.tabular_chart is not None and second.meta.tabular_chart is None
    path = tmp_path / "document.md"
    result.document.save_as_markdown(
        path, artifacts_dir=tmp_path / "assets", image_mode=ImageRefMode.REFERENCED,
        enable_chart_tables=True, traverse_pictures=True,
    )
    text = path.read_text()
    assert "widgets" in text and "12" in text
    assert text.count("![Image]") == 2
    assert len(list((tmp_path / "assets").glob("*.png"))) == 2


def test_flag_off_never_initializes_or_runs_optional_models(models, fixture_pdf):
    events, _, _ = models
    result = converter(charts=False).convert(fixture_pdf, raises_on_error=False)
    assert result.status == ConversionStatus.SUCCESS
    assert all(stage not in {"classifier", "chart"} for _, stage in events)
    assert all(picture.meta is None for picture in result.document.pictures)


def test_repeat_conversion_reuses_models_without_duplicate_enrichment(models, fixture_pdf):
    events, _, _ = models
    instance = converter()
    for _ in range(2):
        result = instance.convert(fixture_pdf, raises_on_error=False)
        assert result.status == ConversionStatus.SUCCESS
        assert len(result.document.pictures[0].meta.classification.predictions) == 2
    counts = Counter(events)
    for stage in ("page", "classifier", "chart"):
        assert counts[("construct", stage)] == 1
        assert counts[("run", stage)] == 2


def test_classification_only_does_not_construct_the_chart_model(models, fixture_pdf):
    events, _, _ = models
    result = converter(charts=False, classify=True).convert(fixture_pdf, raises_on_error=False)
    assert result.status == ConversionStatus.SUCCESS
    assert Counter(events)[("run", "classifier")] == 1
    assert all(stage != "chart" for _, stage in events)
    assert all(picture.meta.classification is not None for picture in result.document.pictures)


@pytest.mark.parametrize("failure", ["classifier_run", "chart_run"])
def test_stage_failure_fails_conversion_and_still_unloads(models, fixture_pdf, failure):
    events, failures, _ = models
    failures.add(failure)
    result = converter().convert(fixture_pdf, raises_on_error=False)
    assert result.status == ConversionStatus.FAILURE
    assert result.errors
    assert events[-1] == ("unload", "backend")
    assert Counter(events)[("run", "classifier")] == 1
    assert Counter(events)[("run", "chart")] == (failure == "chart_run")


@pytest.mark.parametrize("failure", ["classifier_init", "chart_init", "page_init"])
def test_failed_initialization_releases_retained_models(models, failure):
    _, failures, references = models
    failures.add(failure)
    instance = converter()
    with pytest.raises(RuntimeError, match="construction failed"):
        instance.initialize_pipeline(InputFormat.PDF)
    gc.collect()
    assert references and all(reference() is None for reference in references)


def test_conversion_failure_does_not_corrupt_reused_pipeline(models, fixture_pdf):
    events, failures, _ = models
    instance = converter()
    failures.add("chart_run")
    failed = instance.convert(fixture_pdf, raises_on_error=False)
    assert failed.status == ConversionStatus.FAILURE
    failures.clear()
    recovered = instance.convert(fixture_pdf, raises_on_error=False)
    assert recovered.status == ConversionStatus.SUCCESS
    assert recovered.document.pictures[0].meta.tabular_chart is not None
    assert Counter(events)[("construct", "classifier")] == 1
    assert Counter(events)[("construct", "chart")] == 1
    assert Counter(events)[("run", "classifier")] == 2
    assert Counter(events)[("run", "chart")] == 2


def test_separate_converters_do_not_share_model_instances(models, fixture_pdf):
    events, _, references = models
    first, second = converter(), converter()
    for instance in (first, second):
        assert instance.convert(fixture_pdf, raises_on_error=False).status == ConversionStatus.SUCCESS
    assert len(references) == 2 and references[0]() is not references[1]()
    assert Counter(events)[("run", "chart")] == 2
