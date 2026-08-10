# Engine recommendation

The recommendation routine answers two separate questions:

1. Which conversion program best matches the source document?
2. Which suitable program is installed on this machine?

Keeping these answers separate prevents an unavailable model from making an
inferior method appear appropriate.

## Decision policy

| Source classification | Recommended engine | Comparison | Complete-coverage fallback |
|---|---|---|---|
| Reliable native text, simple layout | PyMuPDF4LLM | none initially | Granite hybrid, then broader OCR |
| Reliable native text, complex layout | PyMuPDF4LLM | Granite hybrid | Granite pure-VLM or Marker |
| Mixed text and image-only pages | Granite pure-VLM | PyMuPDF4LLM baseline | Marker, then Granite hybrid |
| Image-only scan | Granite pure-VLM | none in balanced mode | Marker |

The fast profile intentionally constrains the choice to PyMuPDF4LLM. The
quality profile adds an independent OCR candidate for mixed documents and
scans. The forensic profile runs every engine while retaining the same
document-specific recommendation.

## Inputs

The policy uses source evidence rather than filename or file size alone:

- reliable embedded-text page ratio;
- invalid or replacement character ratio;
- native, mixed, or scan classification;
- table grids and numbered table references;
- figures, images, and sampled vector drawings;
- multi-column signals and overall layout complexity;
- analyzer warnings.

It returns the recommended engine, candidate priority, comparisons, fallbacks,
engines capable of complete page coverage, decision confidence, rationale, and
manual-review reasons.

## CLI

~~~sh
kilix-pdf recommend document.pdf
kilix-pdf recommend document.pdf --profile quality --json
~~~

The command inspects package availability but does not initialize any model.
For a scan with neither Granite nor Marker installed, **best_available_engine**
is null; PyMuPDF4LLM is not presented as an adequate substitute. For a mixed
document, a native extractor may be reported as **best_partial_engine**, but it
does not satisfy the complete-page coverage requirement.

## Python API

~~~python
from pathlib import Path

from kilix_pdf_conversion.analysis import analyze_pdf
from kilix_pdf_conversion.recommendation import recommend_conversion

analysis = analyze_pdf(Path("document.pdf"))
recommendation = recommend_conversion(analysis)

print(recommendation.recommended_engine)
print(recommendation.candidate_priority)
print(recommendation.review_reasons)
~~~

Automatic **convert** calls this same function. The manifest preserves the
recommendation and notes whether explicit **--engine** arguments overrode it.
Under the balanced, quality, and forensic profiles, mixed documents and scans
publish no canonical file unless Granite pure-VLM or Marker produces a
non-failing complete-coverage candidate. Native-only partial output is retained
for inspection. The explicitly constrained fast profile may still emit its
native-only result.
