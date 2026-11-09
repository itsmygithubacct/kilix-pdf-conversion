# Conversion workflow

The routing, profiles, output layout and quality policy of Kilix PDF
Conversion. This text was moved from the README; the
[README](../README.md) is the short entry point.

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
[engine recommendation](RECOMMENDATION.md).

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
See [the output contract](OUTPUT_CONTRACT.md) for details.

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

See [validation](VALIDATION.md) for the complete policy.
