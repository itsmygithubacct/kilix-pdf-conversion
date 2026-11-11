# Kilix PDF Conversion

Kilix PDF Conversion is a multi-engine PDF-to-Markdown workflow. It
uses fast native extraction when a PDF has trustworthy embedded text, adds
Granite-Docling when visual layout analysis is useful, and can escalate scans
to an independent Marker OCR pass or CPU page OCR using Tesseract or RapidOCR.

Installable on demand from the Kilix content catalog as `kilix-pdf-conversion`
(`kilix install kilix-pdf-conversion`). `kilix pdf [PDF]` installs it on first
use and runs it in the current pane; the catalog pins the exact commit and
builds only the base runtime (`make runtime`).

The project does not assume that the most expensive output is the best output.
Every candidate is retained and checked before one file is selected as canonical.
Scores are heuristics; passing does not independently verify content accuracy.

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

## Quick start

Python 3.11 or newer and `uv` are required. The base runtime is built from the
checked-in `runtime/uv.lock` and contains PyMuPDF4LLM only; the layout-model and
OCR engines are optional extras installed separately (see
[installation](docs/installation.md)).

~~~sh
make runtime
./kilix-pdf doctor
./kilix-pdf
./kilix-pdf report.pdf
~~~

With no argument on a terminal, `kilix-pdf` starts a guided session. A leading
path that is not a command is treated as `convert`, which is what desktop file
associations and `kilix pdf FILE` use.

## Usage

| Command | What it does |
|---|---|
| `kilix-pdf` / `interactive` | guided terminal session |
| `doctor` | report the installed engines and runtime capabilities |
| `inspect PDF` | analyze the text layer and layout without converting |
| `recommend PDF` | name the best engine and the best installed engine, without loading a model |
| `plan PDF` | show the automatic route for the selected profile |
| `convert PDF` | run the route, validate every candidate and select `canonical.md` |
| `ocr IMAGE` | read an image with Tesseract or RapidOCR; `--route-only` previews the choice |
| `batch DIR [--pattern GLOB]` | convert a directory, reusing loaded model instances |
| `validate PDF MARKDOWN [--engine E]` | audit an existing conversion |

Conversion options: `--profile fast|balanced|quality|forensic`, repeated
`--engine pymupdf4llm|granite-hybrid|granite-pure-vlm|marker|page-ocr`, `--device
auto|cpu|cuda`, `--output-root DIR`, `--force`, `--no-source`,
`--no-visual-pages` and `--chart-extraction`. Every command except
`interactive` accepts `--json`.
Worked examples are in [docs/usage.md](docs/usage.md).

## How it works

```
PDF --> content hash + analysis --> route (profile) --> engine candidates
                                                         |
          canonical.md <-- select <-- quality gates <----+
```

The balanced profile analyzes first and routes by document type:

| Document | Initial conversion |
|---|---|
| Reliable native text, simple layout | PyMuPDF4LLM |
| Reliable native text, complex layout | PyMuPDF4LLM + Granite hybrid |
| Mixed native and image-only pages | PyMuPDF4LLM + Granite pure-VLM |
| Image-only scan | Granite pure-VLM |

Marker is an optional fallback for concrete conversion/check failures. Page
OCR is the last fallback and, in the base runtime, the engine that gives scans
complete coverage when Granite is not installed.
Uncertain source evidence alone retains a usable native result for review and
does not start another OCR model. The forensic profile runs every installed engine.

Each source gets a content-addressed run directory holding the staged source,
every candidate with its assets, per-candidate quality reports, a manifest and
an event log. `canonical.md` is a copied, link-adjusted candidate, never a
merge of engines. A completed run is reused only when source, configuration,
schema and canonical SHA-256 all match; interrupted and forced runs are moved
under `output/.history/` first. The full routing, profile, output and quality
rules are in [docs/workflow.md](docs/workflow.md).

See [page OCR](docs/OCR.md) for the base runtime’s OCR engines and model requirements.

## Documentation

- [docs/installation.md](docs/installation.md): the managed runtime, the
  optional engine extras, and the development targets.
- [docs/usage.md](docs/usage.md): command examples.
- [docs/workflow.md](docs/workflow.md): why the workflow routes, profiles,
  output layout and quality policy.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): the pipeline, analysis, routing,
  engines, selection, resume behaviour and extension points.
- [docs/RECOMMENDATION.md](docs/RECOMMENDATION.md): engine recommendation.
- [docs/OUTPUT_CONTRACT.md](docs/OUTPUT_CONTRACT.md): run identity, files and
  reuse rules.
- [docs/VALIDATION.md](docs/VALIDATION.md): hard failures, warnings and scoring.
- [CHANGELOG.md](CHANGELOG.md): release history.
- [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md): code and model licences.

## Related repositories

- [kilix-content](https://github.com/itsmygithubacct/kilix-content#readme):
  the catalog entry that pins and builds this repository.
- [kilix](https://github.com/itsmygithubacct/kilix#readme): the `kilix pdf`
  and `kilix install` verbs.
- [kilix-pdf](https://github.com/itsmygithubacct/kilix-pdf#readme): the
  separate terminal PDF viewer (`kilix-pdf-viewer`, `kilix pdf-view`).

## Part of Plebian-OS

Kilix PDF Conversion is one of the repositories behind
[Plebian-OS](https://github.com/itsmygithubacct/plebian-os#readme), a Debian
install whose desktop is [Kilix](https://github.com/itsmygithubacct/kilix#readme)
running the [Kilix 95](https://github.com/itsmygithubacct/kilix-95#readme)
desktop through [Pleb](https://github.com/itsmygithubacct/pleb#readme).
It is installed on demand from the Kilix content catalog, not shipped in the
installer image. The map of every repository and how it ships is on the
[components page](https://github.com/itsmygithubacct/plebian-os/blob/main/docs/components.md).

## License

Copyright (C) 2026 itsmygithubacct. Kilix PDF Conversion is licensed under
AGPL-3.0-only and comes with no warranty. See [LICENSE](LICENSE) and
[third-party notices](THIRD-PARTY-NOTICES.md).
