# Changelog

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
