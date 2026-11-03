# Kilix PDF Conversion

Kilix PDF Conversion is a multi-engine PDF-to-Markdown workflow with explicit
source and output checks. It uses fast native extraction for embedded text, adds
Granite-Docling when visual layout analysis is useful, and can escalate scans
to an independent Marker OCR pass.

The project does not assume that the most expensive output is the best output.
Every candidate is retained and checked before one file is selected as canonical.
Scores are heuristics; transcription, numeric cells and reading order are not
independently verified by a pass. Uncertain source text is reported for review.

## Why this workflow

PDF conversion has three different problems:

1. recover exact text and numeric values;
2. recover reading order, tables, formulas, and figure placement;
3. detect when an apparently valid conversion silently lost content.

No single engine is uniformly best at all three. The default balanced profile
therefore analyzes first and routes by document type:

| Document | Initial conversion |
|---|---|
| Extractable native text, simple layout | PyMuPDF4LLM |
| Extractable native text, complex layout | PyMuPDF4LLM + Granite hybrid |
| Mixed native and image-only pages | PyMuPDF4LLM + Granite pure-VLM |
| Image-only scan | Granite pure-VLM |

Marker is an optional fallback for concrete conversion/check failures.
Uncertain source evidence alone retains a usable native result for review and
does not start another OCR model. The forensic profile runs every installed engine.

## Features

- content-addressed, resumable run directories;
- crash-safe per-run locks and archived recovery of interrupted runs;
- PDF text-layer and layout inspection before conversion;
- first-class engine recommendation API and CLI with installed-engine checks;
- PyMuPDF4LLM native-text baseline;
- Granite-Docling pure-VLM and hybrid modes;
- optional Marker OCR candidate;
- referenced image assets instead of invisible placeholders;
- independent visual page renders for difficult pages;
- atomic source staging, Markdown, asset, and manifest writes;
- native-token recall/precision diagnostics;
- table-width, caption-completeness, empty-math, and repetition checks;
- canonical selection with full candidate retention;
- JSON manifests, JSONL events, and a human-readable report;
- single-file and reusable batch workflows;
- one resident model engine at a time for bounded accelerator memory.

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

### Marker

~~~sh
uv pip install --python .venv/bin/python -e '.[marker]'
~~~

Marker and Granite have large, mutually incompatible model/runtime dependency
closures and must use separate virtual environments. Neither is installed by
the base runtime. The CLI can be invoked with the interpreter that owns
the desired engine. The **--device** override applies to both model adapters,
so **--device cpu** provides a low-memory Marker fallback. Review the model and
code licenses in [the third-party notices](THIRD-PARTY-NOTICES.md) first.

## Quick start

Start the guided terminal interface:

~~~sh
kilix-pdf
~~~

Ask which program is best for a source PDF without loading a model:

~~~sh
kilix-pdf recommend report.pdf
kilix-pdf recommend report.pdf --json
~~~

Inspect the raw signals or preview the complete route:

~~~sh
kilix-pdf inspect report.pdf
kilix-pdf plan report.pdf
~~~

Run the balanced workflow:

~~~sh
kilix-pdf convert report.pdf --output-root ./output
~~~

Force a specific comparison:

~~~sh
kilix-pdf convert report.pdf \
  --engine pymupdf4llm \
  --engine granite-hybrid \
  --output-root ./output
~~~

Convert a directory while reusing loaded model instances:

~~~sh
kilix-pdf batch ./pdfs --pattern '*.pdf' --output-root ./output
~~~

Audit an existing conversion:

~~~sh
kilix-pdf validate report.pdf converted.md --engine granite-hybrid
~~~

Commands accept **--json** for machine-readable output. Use
**configs/default.toml** as a starting configuration.

## Profiles

| Profile | Behavior |
|---|---|
| fast | PyMuPDF4LLM only; useful for trusted native-text corpora |
| balanced | Route by text reliability and visual complexity; default |
| quality | Adds broader OCR comparison for mixed/scanned documents |
| forensic | Runs PyMuPDF4LLM, both Granite modes, and Marker |

Explicit **--engine** options override automatic routing.

The recommendation routine distinguishes the ideal engine, the best installed
engine with complete page coverage, and any partial baseline. For example, it
will not claim that native-only extraction is sufficient for a scan merely
because the OCR engines are absent. Automatic conversion uses this same routine
and records its decision in the manifest. See
[engine recommendation](docs/RECOMMENDATION.md).

## Output

Each source is stored in a content-addressed directory:

~~~text
output/
└── report--1a2b3c4d5e6f/
    ├── analysis.json
    ├── canonical.md
    ├── events.jsonl
    ├── manifest.json
    ├── report.md
    ├── source.pdf
    ├── conversions/
    │   ├── pymupdf4llm/
    │   │   ├── document.md
    │   │   └── assets/
    │   └── granite-hybrid/
    │       ├── document.md
    │       └── assets/
    ├── quality/
    │   ├── pymupdf4llm.json
    │   └── granite-hybrid.json
    └── visual/
        ├── index.md
        └── page-0001.jpg
~~~

The manifest fingerprints the effective route and settings plus the canonical
file. A completed run is reused only when its source, configuration, schema,
and canonical SHA-256 all match. Interrupted and forced runs are atomically
moved under **output/.history/** before a clean run begins, so stale candidate
assets cannot leak into a retry and prior evidence is not destroyed.

**canonical.md** is a copied, link-adjusted candidate. It is not a synthetic
merge. This avoids creating untraceable text by combining disagreeing engines.
See [the output contract](docs/OUTPUT_CONTRACT.md) for details.

## Quality policy

A candidate fails by default when it is empty or tiny, contains a runaway
short-line repetition unsupported by a trusted source, has critically low recall against supported visible
text layer, still contains invisible image placeholders, or references an
image outside its local `assets/` bundle. Missing captions, collapsed table
widths, weaker-but-noncritical recall, and empty display math produce warnings
and lower the score.

Invisible OCR can be accurate or corrupt. Agreement with that layer does not
verify visible content, and disagreement does not by itself fail conversion.
Only pages with supported visible-text evidence supply agreement references.
Legitimate repeated values in those references are preserved. Unknown source
support produces warnings; image text and unsupported geometry remain unverified.

Passing means no issue covered by the configured checks was detected. Scores
are not accuracy percentages. Review the visible source pages for charts,
formulas, numeric values and reading order, even when extraction checks pass.

See [validation](docs/VALIDATION.md) for the complete policy.

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

## License

Copyright (C) 2026 itsmygithubacct. Kilix PDF Conversion is licensed under
AGPL-3.0-only and comes with no warranty. See [LICENSE](LICENSE) and
[third-party notices](THIRD-PARTY-NOTICES.md).
