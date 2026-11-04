"""Prepare the pinned Docling classifier configuration without loading a model.

This helper does not establish licence coverage, verify model weights, or enable
the chart workflow. A future caller must independently verify the complete
asset and a covering first-use receipt before using these options for inference.
"""

from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING

from .base import EngineUnavailable

if TYPE_CHECKING:
    from docling.datamodel.picture_classification_options import DocumentPictureClassifierOptions

REPOSITORY = "docling-project/DocumentFigureClassifier-v2.5"
REVISION = "f859dfbff5c9916cd996942d4b0db7fa25808220"
DOCLING_VERSION = "2.118.0"
METADATA_SHA256 = {
    "config.json": "dbed0349fb8b12fad95d8ff7f43b062c40971e06d9d957b25e90d91dfd3bd77e",
    "preprocessor_config.json": "118dc069572036346fbacc3e15586089d3f8a9aaf9036c0c54b4666236a28032",
}
_MAX_METADATA_BYTES = 1024 * 1024


def verify_classifier_metadata(directory: Path) -> dict[str, str]:
    """Check the pinned model and processor metadata, without touching weights."""
    observed = {}
    for name, expected in METADATA_SHA256.items():
        path = directory / name
        try:
            with path.open("rb") as stream:
                data = stream.read(_MAX_METADATA_BYTES + 1)
        except OSError as error:
            raise EngineUnavailable(f"Classifier metadata unavailable: {name}") from error
        if len(data) > _MAX_METADATA_BYTES:
            raise EngineUnavailable(f"Classifier metadata too large: {name}")
        observed[name] = hashlib.sha256(data).hexdigest()
        if observed[name] != expected:
            raise EngineUnavailable(f"Classifier metadata hash mismatch: {name}")
    return observed


def pinned_classifier_options(
    options: DocumentPictureClassifierOptions,
) -> DocumentPictureClassifierOptions:
    """Return a deep copy with the selected repo revision pinned for local CPU work.

    Docling's default is mutable ``main``, and engine overrides can supersede
    the main model revision. Both are resolved here, without constructing an
    engine. Nonlocal engines, custom model identities and unqualified settings
    are rejected; this function does not authorize or perform inference.
    """
    try:
        installed = version("docling-slim")
    except PackageNotFoundError as error:
        raise EngineUnavailable("Classifier binding requires docling-slim==2.118.0") from error
    if installed != DOCLING_VERSION:
        raise EngineUnavailable(
            f"Classifier binding requires docling-slim=={DOCLING_VERSION}; found {installed}"
        )

    result = options.model_copy(deep=True)
    spec = result.model_spec
    if spec.repo_id != REPOSITORY or spec.revision not in ("main", REVISION):
        raise EngineUnavailable("Classifier model identity is not the selected pinned model")
    engine = result.engine_options
    kind = engine.engine_type.value
    if kind not in ("transformers", "onnxruntime") or engine.top_k is not None:
        raise EngineUnavailable("Classifier binding requires a local engine with all classes")
    if kind == "transformers" and (
        engine.torch_dtype not in (None, "float32") or engine.compile_model
    ):
        raise EngineUnavailable("Classifier Transformers binding requires uncompiled float32")
    if kind == "onnxruntime" and (
        engine.model_filename != "model.onnx" or engine.providers != ["CPUExecutionProvider"]
    ):
        raise EngineUnavailable("Classifier ONNX binding requires the pinned CPU export")
    for engine_type, override in spec.engine_overrides.items():
        if engine_type.value not in ("transformers", "onnxruntime"):
            raise EngineUnavailable("Unsupported classifier engine override")
        if override.repo_id not in (None, REPOSITORY) or override.revision not in (
            None, "main", REVISION,
        ):
            raise EngineUnavailable("Classifier engine override changes the pinned identity")
        if override.torch_dtype not in (None, "float32"):
            raise EngineUnavailable("Classifier engine override changes the pinned dtype")
        if override.extra_config and not (
            engine_type.value == "onnxruntime"
            and override.extra_config == {"model_filename": "model.onnx"}
        ):
            raise EngineUnavailable("Unsupported classifier engine override settings")
        override.repo_id = REPOSITORY
        override.revision = REVISION
    spec.revision = REVISION
    return result
