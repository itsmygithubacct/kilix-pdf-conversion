"""Construct the pinned parity engines only from verified in-memory bytes.

Calling this function initializes models and must be separately admitted by the
caller. It does not enable the chart workflow or qualify the decoder.
"""

from __future__ import annotations

import json

from . import classifier_asset
from .base import EngineUnavailable
from .classifier_asset import VerifiedClassifierAsset


def load_classifier_for_parity(snapshot: VerifiedClassifierAsset):
    """Load both engines without reopening any classifier asset path."""
    if type(snapshot) is not VerifiedClassifierAsset:
        raise EngineUnavailable("Classifier snapshot type mismatch")
    classifier_asset._require_classifier_receipt()
    assets = snapshot._verified_copy()
    try:
        config_data = json.loads(assets["config.json"])
        processor_data = json.loads(assets["preprocessor_config.json"])
    except (KeyError, ValueError, UnicodeError) as error:
        raise EngineUnavailable("Classifier snapshot metadata invalid") from error
    if (config_data.get("model_type") != "efficientnet"
            or config_data.get("architectures") != ["EfficientNetForImageClassification"]
            or processor_data.get("image_processor_type") != "ViTImageProcessor"):
        raise EngineUnavailable("Classifier snapshot metadata identity mismatch")
    try:
        labels = {int(k): v for k, v in config_data["id2label"].items()}
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise EngineUnavailable("Classifier label metadata invalid") from error
    if sorted(labels) != list(range(26)):
        raise EngineUnavailable("Classifier class mapping mismatch")

    # These imports and constructors can load models. They are deliberately
    # after snapshot admission; the caller must hold the compute reservation.
    import onnxruntime as ort
    from safetensors.torch import load as load_safetensors
    from transformers import (
        EfficientNetConfig,
        EfficientNetForImageClassification,
        ViTImageProcessor,
    )

    processor = ViTImageProcessor.from_dict(processor_data)
    config = EfficientNetConfig.from_dict(config_data)
    model = EfficientNetForImageClassification(config)
    model.load_state_dict(load_safetensors(assets["model.safetensors"]), strict=True)
    model.eval()
    session_options = ort.SessionOptions()
    session_options.intra_op_num_threads = 2
    session_options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        assets["model.onnx"], sess_options=session_options,
        providers=["CPUExecutionProvider"],
    )
    return processor, model, session, labels
