"""Options and metadata only; no weights, receipts, or model inference."""

import hashlib

import pytest

pytest.importorskip("docling")
from docling.datamodel.image_classification_engine_options import (
    OnnxRuntimeImageClassificationEngineOptions,
)
from docling.datamodel.picture_classification_options import DocumentPictureClassifierOptions
from docling.datamodel.stage_model_specs import EngineModelConfig
from docling.models.inference_engines.image_classification.base import ImageClassificationEngineType

from kilix_pdf_conversion.engines import classifier_binding as binding
from kilix_pdf_conversion.engines.base import EngineUnavailable


def preset():
    return DocumentPictureClassifierOptions.from_preset(
        "document_figure_classifier_v2"
    ).model_copy(deep=True)


def test_pins_base_and_overrides_without_mutating_options():
    options = preset()
    options.engine_options.compile_model = False
    options.model_spec.engine_overrides = {
        ImageClassificationEngineType.TRANSFORMERS: EngineModelConfig(revision="main"),
        ImageClassificationEngineType.ONNXRUNTIME: EngineModelConfig(),
    }
    result = binding.pinned_classifier_options(options)
    assert options.revision == "main"
    assert options.model_spec.engine_overrides[ImageClassificationEngineType.TRANSFORMERS].revision == "main"
    assert result is not options
    for engine in (ImageClassificationEngineType.TRANSFORMERS, ImageClassificationEngineType.ONNXRUNTIME):
        selected = result.model_spec.get_engine_config(engine)
        assert selected.repo_id == binding.REPOSITORY
        assert selected.revision == binding.REVISION


def test_binding_does_not_mutate_docling_shared_preset():
    first = DocumentPictureClassifierOptions.from_preset("document_figure_classifier_v2")
    second = DocumentPictureClassifierOptions.from_preset("document_figure_classifier_v2")
    first.engine_options.compile_model = False
    before = second.model_spec.model_dump()
    assert binding.pinned_classifier_options(first).revision == binding.REVISION
    assert second.model_spec.model_dump() == before


@pytest.mark.parametrize("field,value", [
    ("repo_id", "elsewhere/model"), ("revision", "unreviewed"),
    ("torch_dtype", "float16"), ("extra_config", {"unexpected": True}),
])
def test_refuses_conflicting_engine_override(field, value):
    options = preset()
    options.engine_options.compile_model = False
    options.model_spec.engine_overrides = {
        ImageClassificationEngineType.TRANSFORMERS: EngineModelConfig(**{field: value}),
    }
    before = options.model_dump()
    with pytest.raises(EngineUnavailable):
        binding.pinned_classifier_options(options)
    assert options.model_dump() == before


def test_onnx_cpu_options_are_pinned_and_custom_export_refused():
    options = DocumentPictureClassifierOptions.from_preset(
        "document_figure_classifier_v2", engine_options=OnnxRuntimeImageClassificationEngineOptions(),
    ).model_copy(deep=True)
    assert binding.pinned_classifier_options(options).revision == binding.REVISION
    options.engine_options.model_filename = "other.onnx"
    with pytest.raises(EngineUnavailable, match="pinned CPU export"):
        binding.pinned_classifier_options(options)


def test_model_identity_and_restricted_output_are_refused():
    options = preset()
    options.engine_options.compile_model = False
    options.engine_options.top_k = 1
    with pytest.raises(EngineUnavailable, match="all classes"):
        binding.pinned_classifier_options(options)
    options.engine_options.top_k = None
    options.model_spec.repo_id = "unrelated/model"
    with pytest.raises(EngineUnavailable, match="model identity"):
        binding.pinned_classifier_options(options)


def test_wrong_docling_version_is_refused(monkeypatch):
    monkeypatch.setattr(binding, "version", lambda _name: "2.127.0")
    with pytest.raises(EngineUnavailable, match="found 2.127.0"):
        binding.pinned_classifier_options(preset())


def test_metadata_checks_synthetic_hashes_and_refuses_corruption(tmp_path, monkeypatch):
    contents = {"config.json": b"synthetic config", "preprocessor_config.json": b"synthetic processor"}
    for name, data in contents.items():
        (tmp_path / name).write_bytes(data)
    expected = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    monkeypatch.setattr(binding, "METADATA_SHA256", expected)
    assert binding.verify_classifier_metadata(tmp_path) == expected
    (tmp_path / "preprocessor_config.json").write_bytes(b"changed")
    with pytest.raises(EngineUnavailable, match="hash mismatch"):
        binding.verify_classifier_metadata(tmp_path)
    (tmp_path / "config.json").unlink()
    with pytest.raises(EngineUnavailable, match="metadata unavailable"):
        binding.verify_classifier_metadata(tmp_path)
