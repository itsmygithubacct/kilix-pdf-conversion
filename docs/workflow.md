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

Marker is an optional fallback for concrete conversion/check failures. Page
OCR is the last fallback and, in the base runtime, the engine that gives scans
complete coverage when Granite is not installed.
Uncertain source evidence alone retains a usable native result for review and
does not start another OCR model. The forensic profile runs every installed engine.

## Profiles

| Profile | Behavior |
|---|---|
| fast | PyMuPDF4LLM only; useful for trusted native-text corpora |
| balanced | Route by text reliability and visual complexity; default |
| quality | Adds broader OCR comparison for mixed/scanned documents |
| forensic | Runs PyMuPDF4LLM, both Granite modes, Marker, and page OCR |

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

See [validation](VALIDATION.md) for the complete policy.

