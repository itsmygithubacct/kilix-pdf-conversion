# Architecture

## Pipeline

~~~text
PDF intake
   |
   v
content hash + structural analysis
   |
   v
recommend primary, comparison, and fallback engines
   |
   +--> PyMuPDF4LLM native baseline
   +--> Granite hybrid visual structure + backend text
   +--> Granite pure-VLM visual OCR
   +--> Marker independent OCR fallback
   |
   v
candidate-specific assets and Markdown
   |
   v
quality gates and scoring
   |
   v
canonical selection + report + manifest
~~~

The workflow keeps analysis, recommendation, conversion, validation, and
selection separate.
This makes every decision inspectable and permits new engines without changing
the artifact contract.

## Analysis

The analyzer records:

- stable source SHA-256, size, and page count, with mutation detection;
- native characters and reliable-text page ratio;
- invalid/replacement character ratio;
- images and sampled vector drawings;
- numbered table and figure references;
- detected grid tables and maximum table width;
- multi-column page signals.

It classifies the document as native, mixed, or scan. A separate complexity
score labels layout as simple or complex. Table detection is capped and biased
toward caption pages so large books remain practical.

## Routing

The recommendation policy names one preferred engine, comparison candidates,
complete-coverage engines, and ordered fallbacks. Automatic conversion consumes
that object directly. For mixed documents, a native-only pass cannot suppress
the OCR fallback when the preferred visual engine is unavailable.

The CLI also evaluates installed packages. It reports the ideal engine and the
best suitable installed engine separately, rather than silently downgrading a
scan to native-only extraction.

Pure-VLM and hybrid are intentionally distinct engine names. They have
different transcription risks and must never share a cache key.

## Engines

Engine imports are lazy. The base package can inspect and convert native PDFs
without importing model stacks.

Each engine owns a candidate directory and returns a normalized result record:

- status and error;
- Markdown and asset paths;
- runtime and output size;
- engine version and mode settings.

Model instances are cached by a Workflow object and reused across batch
documents. Only one model-based engine is kept resident at a time; switching
between Granite modes or Marker releases the previous model before loading the
next one. This prevents the forensic profile from retaining multiple large
model stacks on a constrained GPU. Models are also released when the workflow
closes.

## Validation and selection

Validation is performed against the source analysis and, when appropriate, the
native PDF text layer. The candidate with the strongest status and adjusted
score is selected. Document-kind priors break close ties:

- native documents favor PyMuPDF4LLM, then Granite hybrid;
- scans favor Granite pure-VLM, then Marker;
- mixed documents favor Granite pure-VLM while retaining the native baseline.

The canonical file is copied from one candidate. Cross-engine synthesis is out
of scope because merging unaligned page structures can silently invent or
duplicate content.

## Failure and resume behavior

- Run identity is source slug plus a SHA-256 prefix.
- A per-run exclusive lock prevents concurrent writers.
- The advisory lock is released by the kernel after normal exit or a crash; its
  diagnostic file does not need to be deleted.
- Text and JSON files are written through a temporary file and atomically
  renamed.
- The manifest is written only after selection and reporting.
- A complete manifest is reused only after its schema, source, configuration,
  canonical path, and canonical digest are verified.
- Interrupted and forced runs are atomically archived under `.history` before
  a fresh run directory is created.
- Candidate failures remain in the manifest and do not erase successful peers.

## Extension points

Add an EngineName, implement ConversionEngine, register it in the factory, and
add routing/quality tests. Output consumers do not need to change.
