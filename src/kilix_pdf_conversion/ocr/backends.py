"""The two OCR engines. Each reads one PIL image and returns text paragraphs."""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import threading
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from ..engines.base import EngineUnavailable

DESKEW_FROM_DEGREES = 0.3
RAPIDOCR_VERSION = "3.10.0"
LANGUAGE = re.compile(r"^[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*$")


class OcrFailed(RuntimeError):
    pass


def level(image, skew_degrees: float):
    """Rotate a skewed page upright, filling the corners with the page colour."""
    import numpy as np
    from PIL import Image

    if abs(skew_degrees) < DESKEW_FROM_DEGREES:
        return image
    rgb = image.convert("RGB")
    ground = tuple(int(v) for v in np.median(np.asarray(rgb).reshape(-1, 3), axis=0))
    return rgb.rotate(-skew_degrees, resample=Image.BICUBIC, expand=True, fillcolor=ground)


def _paragraphs(text: str) -> tuple[str, ...]:
    blocks = re.split(r"\n(?:[ \t]*\n)+", text.replace("\f", "\n\n"))
    return tuple(b.strip("\n") for b in blocks if b.strip())


class TesseractBackend:
    """Tesseract 5 with full page layout analysis, run as a subprocess."""

    def __init__(self, binary: str | None, language: str, threads: int, timeout: float) -> None:
        if not LANGUAGE.match(language):
            raise ValueError("ocr.language must be Tesseract language codes joined by +")
        self.binary = binary or os.environ.get("KILIX_OCR_TESSERACT") or shutil.which("tesseract")
        self.language = language
        self.threads = threads
        self.timeout = timeout
        self._checked: dict | None = None

    def _env(self) -> dict[str, str]:
        return {**os.environ, "OMP_THREAD_LIMIT": str(self.threads)}

    def check(self) -> dict:
        """Version and language support; raises EngineUnavailable."""
        if self._checked is not None:
            return self._checked
        if not self.binary or not Path(self.binary).is_file():
            raise EngineUnavailable("tesseract is not installed (Debian: tesseract-ocr)")
        try:
            shown = subprocess.run([self.binary, "--version"], capture_output=True, text=True,
                                   timeout=30, env=self._env())
            listed = subprocess.run([self.binary, "--list-langs"], capture_output=True,
                                    text=True, timeout=30, env=self._env())
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EngineUnavailable(f"tesseract cannot run: {error}") from error
        first = (shown.stdout or shown.stderr).splitlines()
        if shown.returncode != 0 or not first or not first[0].startswith("tesseract "):
            raise EngineUnavailable("tesseract did not report its version")
        languages = {line.strip() for line in listed.stdout.splitlines()[1:]}
        missing = [code for code in self.language.split("+") if code not in languages]
        if missing:
            raise EngineUnavailable(
                f"tesseract language data missing: {', '.join(missing)} "
                "(Debian: tesseract-ocr-" + missing[0] + ")"
            )
        self._checked = {"version": first[0].split()[1], "languages": sorted(languages),
                         "binary": self.binary}
        return self._checked

    def read(self, image, skew_degrees: float, dpi: int | None) -> tuple[str, ...]:
        self.check()
        buffer = io.BytesIO()
        page = level(image, skew_degrees)
        page.save(buffer, format="PNG", **({"dpi": (dpi, dpi)} if dpi else {}))
        command = [self.binary, "stdin", "stdout", "--psm", "3", "-l", self.language]
        if dpi:
            command += ["--dpi", str(dpi)]
        try:
            done = subprocess.run(command, input=buffer.getvalue(), capture_output=True,
                                  timeout=self.timeout, env=self._env())
        except subprocess.TimeoutExpired as error:
            raise OcrFailed(f"tesseract exceeded {self.timeout:g} s") from error
        except OSError as error:
            raise OcrFailed(f"tesseract cannot run: {error}") from error
        if done.returncode != 0:
            message = done.stderr.decode(errors="replace").strip().splitlines()
            raise OcrFailed("tesseract failed: " + (message[-1] if message else "no message"))
        return _paragraphs(done.stdout.decode("utf-8", errors="replace"))


def _refuse_download(*_args, **_kwargs):
    raise OcrFailed("RapidOCR attempted a download; models must come from verified assets")


class RapidOcrBackend:
    """RapidOCR with PaddlePaddle's PP-OCRv6 small models on ONNX Runtime, CPU only."""

    def __init__(self, model_directory: Path | None, threads: int) -> None:
        self.model_directory = model_directory
        self.threads = threads
        self._engine = None
        self._models = None
        self._checked: dict | None = None
        self._lock = threading.Lock()

    def check(self) -> dict:
        """Package versions and verified assets; raises EngineUnavailable."""
        if self._checked is not None:
            return self._checked
        try:
            import numpy  # noqa: F401
            import onnxruntime  # noqa: F401
            import PIL  # noqa: F401
            import rapidocr  # noqa: F401
        except ImportError as error:
            raise EngineUnavailable(
                f"RapidOCR runtime missing {error.name}; rebuild the frozen runtime"
            ) from error
        try:
            found = version("rapidocr")
            ort_version = version("onnxruntime")
        except PackageNotFoundError as error:
            raise EngineUnavailable("RapidOCR package metadata is missing") from error
        if found != RAPIDOCR_VERSION:
            raise EngineUnavailable(
                f"OCR requires rapidocr=={RAPIDOCR_VERSION}, found {found}; "
                "rebuild the frozen runtime"
            )
        from .assets import verify_models

        self._models = verify_models(self.model_directory)
        self._checked = {"version": found, "onnxruntime": ort_version,
                         "models": dict(self._models.revisions),
                         "model_directory": str(self._models.directory)}
        return self._checked

    def _build(self):
        import tempfile

        import onnxruntime as ort
        from omegaconf import flag_override
        from rapidocr import RapidOCR
        from rapidocr.utils import download_file
        from rapidocr.utils.typings import ModelType, OCRVersion

        self.check()
        models = self._models
        # Nothing below may fetch a model or dictionary from the network.
        download_file.DownloadFile.run = staticmethod(_refuse_download)

        def session(model: bytes):
            options = ort.SessionOptions()
            options.log_severity_level = 3
            options.intra_op_num_threads = self.threads
            options.inter_op_num_threads = 1
            return ort.InferenceSession(model, sess_options=options,
                                        providers=["CPUExecutionProvider"])

        with tempfile.TemporaryDirectory(prefix="kilix-ocr-") as scratch:
            # The official recogniser keeps its dictionary in inference.yml, not in
            # the model, so RapidOCR reads the verified table from a private file.
            keys = Path(scratch) / "characters.txt"
            keys.write_text("\n".join(models.characters) + "\n", encoding="utf-8")
            engine = RapidOCR(params={
                "Global.log_level": "error",
                # The text-angle classifier turns some upright lines upside down
                # and garbles them; input pages are taken to be upright.
                "Global.use_cls": False,
                "Global.model_root_dir": str(Path(scratch) / "unused"),
                "Det.ocr_version": OCRVersion.PPOCRV6, "Det.model_type": ModelType.SMALL,
                "Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_type": ModelType.SMALL,
                "Rec.rec_keys_path": str(keys),
            })
            with flag_override(engine.cfg, "allow_objects", True):
                engine.cfg.Det.session = session(models.det_model)
                engine.cfg.Rec.session = session(models.rec_model)
            # Load both stages while the dictionary file exists.
            engine._load_det_model()
            engine._load_rec_model()
        return engine

    def read(self, image) -> tuple[str, ...]:
        import numpy as np

        from .layout import order_blocks

        with self._lock:
            if self._engine is None:
                self._engine = self._build()
            bgr = np.ascontiguousarray(np.asarray(image.convert("RGB"))[:, :, ::-1])
            try:
                result = self._engine(bgr)
            except OcrFailed:
                raise
            except Exception as error:
                raise OcrFailed(f"RapidOCR failed: {type(error).__name__}: {error}") from error
        if result.txts is None or result.boxes is None:
            return ()
        blocks = order_blocks(result.boxes.tolist(), list(result.txts))
        return tuple("\n".join(lines) for lines in blocks)

    def close(self) -> None:
        self._engine = None
        self._models = None
        self._checked = None
