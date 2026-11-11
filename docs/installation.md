# Installation and development

How to build the managed runtime, the optional model engines and the
development tools. This text was moved from the README; the
[README](../README.md) is the short entry point.

## Installation

Python 3.11 or newer and `uv` are required.

### Plebian OS and Kilix runtime

The managed runtime is created from the checked-in `runtime/uv.lock`.
That lock contains only the small AGPL-compatible base runtime; optional model
engines cannot leak into it. `--frozen` prevents installation from silently
changing that dependency closure:

~~~sh
make runtime
./kilix-pdf doctor
./kilix-pdf
~~~

The no-argument launcher starts a guided terminal session. A PDF may also be
opened directly, which is the path used by desktop launchers and file
associations:

~~~sh
./kilix-pdf report.pdf
~~~

### Base and development tools

The Make targets provision their development tools through `uv`; they do not
depend on pytest, Ruff, or build being installed in the system interpreter:

~~~sh
make test
make lint
make build
~~~

### Granite-Docling

Granite has a separate frozen CPU runtime for Linux x86-64 and Python 3.12.8.
The default launcher continues to use the native-only `.runtime`; select the
optional `.runtime-granite` explicitly:

~~~sh
make runtime-granite
KILIX_PDF_RUNTIME=granite ./kilix-pdf doctor --json
KILIX_PDF_RUNTIME=granite ./kilix-pdf convert report.pdf --engine granite-pure-vlm
~~~

`runtime-granite/uv.lock` freezes the full dependency closure, including Docling
2.118.0, Docling Core 2.90.0, Transformers 4.57.3 and CPU PyTorch 2.6.0. Merely
installing the extra in another environment does not change the shell launcher.
The frozen runtime uses two CPU threads, FP32, eager SDPA, the slow pinned image
processor and one image per generation. CUDA and alternate runtime versions are
not supported by this profile.

Install/accept the Granite asset through the host's normal model acquisition
flow. The host supplies `KILIX_CONTENT_ROOT`; the adapter verifies all files in
its `assets/granite-docling-258m` directory against revision
`982fe3b40f2fa73c365bdb1bcacf6c81b7184bfe`. For a standalone accepted copy, set
`KILIX_GRANITE_MODEL_DIR` or `[granite].model_directory` to the model directory.
Missing or mismatched files fail before loading. Conversion never downloads a
replacement, requests `main`, or creates a license receipt.

Successful Granite outputs include `document.json` and `generation.json` beside
Markdown. The latter records the model identity, raw/cleaned text, generated IDs,
prompt and generated counts, stop cause, limits and timing. Complete trailing pad
tokens are removed without stripping ordinary characters. A generation cap or
incomplete DocTags fails conversion. `[granite].max_new_tokens` defaults to 8192;
the effective limit also respects the remaining configured context. Syntax and
successful conversion do not establish content correctness. Hybrid preserves
model text unless a complete backend crop has supported visible-text evidence
and agrees with the whole item after whitespace normalization. Empty, partial,
hidden or conflicting crops retain the original model item. `hybrid-text.json`
records each decision. Hybrid does not correct table cells or reading order.

The chart-enrichment lifecycle helper is integrated, but chart extraction stays
unavailable until accepted, pinned classifier and chart assets are supplied.
The adapter fails before constructing any chart model. Lifecycle tests with
substituted predictions do not establish numerical chart accuracy.

### Page OCR

The base runtime includes RapidOCR and ONNX Runtime. Page OCR also needs the
Debian packages `tesseract-ocr` and `tesseract-ocr-eng`, and the two accepted
PP-OCRv6 small assets under `$KILIX_CONTENT_ROOT/assets`. Either engine alone
is enough; **kilix-pdf doctor** shows which are ready. See [page OCR](OCR.md).

~~~sh
kilix-pdf ocr page.png
kilix-pdf ocr --route-only page.png
~~~

### Marker

~~~sh
uv pip install --python .venv/bin/python -e '.[marker]'
~~~

Marker and Granite have large, mutually incompatible model/runtime dependency
closures and must use separate virtual environments. Neither is installed by
the base runtime. The CLI can be invoked with the interpreter that owns
the desired engine. The **--device** override applies to both model adapters,
so **--device cpu** provides a low-memory Marker fallback. Review the model and
code licenses in [the third-party notices](../THIRD-PARTY-NOTICES.md) first.

## Development

~~~sh
make test
make lint
make verify
make build
~~~

The unit tests create PDFs in temporary directories and do not require bundled
document fixtures. Granite and Marker integration tests are intentionally
separate from the fast unit suite.
