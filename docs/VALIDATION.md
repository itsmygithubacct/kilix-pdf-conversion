# Validation

Status and score describe automated checks. They do not independently verify
transcription, numeric cells, tables or reading order. Every quality report and
workflow manifest records `content_accuracy: unverified`; the score is labeled
as a heuristic. A selected canonical file can still require review.

## Source evidence

Text being extractable is insufficient to make it a trustworthy reference.
The native-only inspector uses rendering mode, opacity, character mapping and
geometry, painting order, raster presence and a low-resolution rendered ink
check. It never uses evaluation labels or silently runs neural OCR.

- **Trusted:** inspected text has supported visible rendering and geometry,
  with no unresolved invisible spans or possible occlusion. This describes
  reference usability, not semantic correctness or verified font mappings.
- **Suspect:** observable contradictions such as unmapped characters,
  off-page text or a text box without rendered ink require review.
- **Unknown:** invisible OCR, image-only content, unsupported geometry,
  possible occlusion or unavailable inspection cannot establish a reference.
  Accurate and corrupt invisible OCR can both be unknown.

Only trusted pages contribute to native-text agreement. Reports name those
pages; untrusted pages never contribute authoritative text or caption labels.
Image content remains unchecked even when the visible native text is supported.
Rotation/crop configurations without a supported mapping and inspection work
beyond the bounded raster/observation budget return unknown, preserving extraction.

The inspector does not prove that Unicode mappings match glyph meaning, that
an OCR layer is correct, or that a model interpreted a figure correctly. Review
is still required. No absence of a detected contradiction certifies accuracy.

## Output requirements

The existing configured requirements remain enforced: insufficient Markdown
size, no searchable tokens, unresolved image placeholders and missing, external,
absolute or escaping image references fail the checks. Granite truncation,
incomplete DocTags, timeouts and engine failures remain unsuccessful conversions.
Minimum bytes is an artifact requirement, not an accuracy measurement.

Critically low agreement with a supported visible-text reference remains a
failure signal. Native-token recall below the configured target, absent trusted
captions, collapsed table width and empty display math produce warnings. These
checks are incomplete and do not establish numeric or reading-order correctness.

Repeated short lines are checked against supported source multiplicity.
Legitimate repeated values are not decoding loops. Unsupported excess against
a complete trusted reference remains an error; with unknown source support,
repetition is advisory. Neither path permits a truncated generation to succeed.

## Guarded hybrid assembly

The model document is parsed intact. Each text item can be replaced only when
its source/region has supported evidence, the crop is valid and nonempty, and
its entire text agrees after whitespace normalization. Otherwise the model item
is retained. Numeric strings, repeat multiplicity and item order are preserved;
table cells are never substituted. Different words, partial crops and conflicting
numbers do not select a winner by a similarity threshold.

`hybrid-text.json` retains model text, proposed backend text, source evidence and
the decision. Original model text also remains in `orig` and generation traces.
This conservative policy can normalize wrapping; it does not repair model OCR.
Pure mode and chart enrichment lifecycle/gating remain separate.

## Selection and review

Unknown source evidence forces review status rather than a verified pass, and
it cannot create a content failure merely because neural text disagrees with a
hidden layer. The native preference bonus is not awarded from untrusted text.
A usable initial native result with uncertainty alone is retained for review
without automatically loading another model. Concrete errors, suspect rendering
or substantive warnings may still trigger planned fallback. Explicit engine,
quality and forensic selections retain their comparison behavior.

Scans and mixed documents still require appropriate coverage; missing required
engines are reported. Existing candidates remain available even when no canonical
candidate can be selected. Recommendation policy and manifest versions prevent
old circular-validation passes from being reused under this policy.

Local `assets/...` image confinement, symlink checks, staged-source identity and
canonical hash validation remain enforced. Compare all uncertain results with
visible source pages, particularly for charts, formulas, merged cells, repeated
values, handwriting and multi-column layout.
