# Changelog

## Unreleased

- Name Colorama 0.4.6 (BSD-3-Clause) in `THIRD-PARTY-NOTICES.md`. colorlog
  and tqdm require it only on Windows, so a Linux runtime does not install it.
  A test now checks that every package in `runtime/uv.lock` is named there.

## 0.4.0 - 2026-11-10

- Add the **page-ocr** engine: each page is rendered and read with Tesseract 5
  or RapidOCR 3.10.0 running PaddlePaddle's PP-OCRv6 small ONNX models, chosen
  per page from image measurements. RapidOCR is the default; Tesseract takes
  clean upright pages that hold a figure-sized block. Every decision is
  recorded with its reasons in `ocr-pages.json`.
- Order RapidOCR's text boxes by recursive gutter and break cuts, so
  multi-column pages read column by column.
- Verify the two PP-OCRv6 assets by pinned size and SHA-256 and build the
  models from the verified bytes. Nothing is downloaded.
- Route scans and mixed documents to page OCR after Marker, and native
  documents last; the quality and forensic profiles run it as a candidate.
  Recommendation policy version 3.
- Add `kilix-pdf ocr` for images, Tesseract and RapidOCR status to
  `kilix-pdf doctor`, and an `[ocr]` configuration section.
- Add `rapidocr==3.10.0` and `onnxruntime==1.31.1` to the frozen base runtime
  and an `ocr` extra for development installs.

## 0.3.1 - 2026-08-10

- Build the managed application runtime from the frozen, base-only
  `runtime/uv.lock` with `uv`.
- Treat a directly supplied PDF path as the normal single-file conversion
  command so desktop file associations and `kilix pdf FILE` work.

## 0.3.0 - 2026-08-10

- Support the Python 3.11 baseline shipped by Plebian OS.
- Add a standard `venv` runtime installer with an exact hash-verified base lock;
  `uv` is no longer required on release images.
- Pin the last AGPL-only PyMuPDF4LLM base closure and exclude the noncommercial
  PyMuPDF Layout dependency from the public runtime.
- Relicense the application under AGPL-3.0-only and document third-party code
  and model terms.
- Add a guided no-argument terminal interface and repository launcher.
- Replace stale-prone lock files with kernel-released advisory locks.
- Archive interrupted and forced runs before clean retries instead of reusing
  or deleting their directories.
- Verify source staging, engine output confinement, cached manifest schema, and
  canonical output SHA-256.
- Reject external, absolute, escaping, symlinked, missing, and non-asset image
  references.
- Keep page signals for the full document and spread capped visual renders
  across all relevant pages.
- Validate configuration types, ranges, keys, and mutually exclusive model
  dependency sets.
- Add Python 3.11 through 3.13 CI, build verification, and expanded regression
  tests.

## 0.2.0 - 2026-08-10

- Add a first-class source-to-engine recommendation routine and CLI command.
- Report the ideal engine separately from the best installed engine.
- Record recommendation confidence, rationale, review flags, and policy version.
- Make automatic conversion consume the same recommendation object.
- Require a full-page OCR candidate for mixed documents before skipping fallbacks.

## 0.1.0 - 2026-08-09

- Add native, mixed, and scan classification.
- Add fast, balanced, quality, and forensic routing profiles.
- Add PyMuPDF4LLM, Granite hybrid, Granite pure-VLM, and Marker adapters.
- Export referenced engine assets and independent visual page renders.
- Add transactional content-addressed run bundles.
- Fingerprint effective settings to prevent incompatible cache reuse.
- Add token, table, figure, math, placeholder, and repetition validation.
- Reject missing and nonportable image references.
- Apply device selection to Granite and Marker model adapters.
- Add canonical candidate selection, manifests, events, and reports.
- Add unit and fast integration tests.
