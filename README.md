# Kilix PDF Conversion

Kilix PDF Conversion is a validated, multi-engine PDF-to-Markdown workflow. It
uses fast native extraction when a PDF has trustworthy embedded text, adds
Granite-Docling when visual layout analysis is useful, and can escalate scans
to an independent Marker OCR pass.

The project does not assume that the most expensive output is the best output.
Every candidate is retained, measured, and quality-gated before one file is
selected as canonical.

## Why this workflow

PDF conversion has three different problems:

1. recover exact text and numeric values;
2. recover reading order, tables, formulas, and figure placement;
3. detect when an apparently valid conversion silently lost content.

No single engine is uniformly best at all three. The default balanced profile
therefore analyzes first and routes by document type:

| Document | Initial conversion |
|---|---|
| Reliable native text, simple layout | PyMuPDF4LLM |
| Reliable native text, complex layout | PyMuPDF4LLM + Granite hybrid |
| Mixed native and image-only pages | PyMuPDF4LLM + Granite pure-VLM |
| Image-only scan | Granite pure-VLM |

Marker is an optional fallback when the first-stage candidates do not pass the
quality gates. The forensic profile runs every installed engine.

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

Granite is an optional extra because GPU-enabled PyTorch installation depends
on the local accelerator and driver:

~~~sh
uv pip install --python .venv/bin/python -e '.[granite]'
~~~

Install the appropriate PyTorch build for the machine after consulting the
PyTorch compatibility matrix. An 8 GiB GPU should start with a one-page batch.

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
short-line repetition, has critically low recall against a trustworthy native
text layer, still contains invisible image placeholders, or references an
image outside its local `assets/` bundle. Missing captions, collapsed table
widths, weaker-but-noncritical recall, and empty display math produce warnings
and lower the score.

Validation is deliberately conservative. Passing means “suitable as the best
available candidate under these checks,” not “identical to the PDF.” The source
PDF remains authoritative for charts, formulas, and numeric verification.

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
