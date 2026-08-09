# Validation

## Hard failures

The default policy rejects a candidate when:

- Markdown is below the minimum byte size;
- it contains no searchable tokens;
- one short nonblank line repeats above the configured threshold;
- an invisible image placeholder remains;
- a local image reference is missing or uses a nonportable absolute path;
- native-token recall is below 65 percent for a non-scan PDF.

The repeated-short-line check catches generative decoding loops while ignoring
ordinary blank lines.

## Warnings

Warnings are emitted when:

- native-token recall is below the configured target;
- fewer than 70 percent of expected numbered tables are represented;
- fewer than 70 percent of expected numbered figures are represented;
- maximum Markdown table width is substantially below detected source width;
- an empty display-math block is present.

Warnings reduce the score and can trigger fallback engines when no initial
candidate passes cleanly.

## Native-text comparison

The metric is diagnostic:

1. extract sorted text from every PDF page;
2. normalize HTML entities, quote variants, dashes, and Markdown links;
3. tokenize case-insensitively;
4. compute multiset recall and precision.

It is not a human-corrected transcription score. PDF text can contain broken
encoding, repeated page furniture, and chart labels in unusual order. For
scans the metric is disabled.

## Table checks

Markdown pipe tables count only when they contain a separator row. HTML tables
also count. Maximum source and output column widths are compared as a coarse
loss detector.

Candidate caption counts use caption-like lines rather than prose references.
They detect broad omission but cannot prove that table cells or figures are
correct.

## Image checks

The application asks engines to write referenced image assets. Invisible
comment placeholders fail by default because they produce a misleadingly
complete-looking Markdown file with no viewable figure.

Independent source-page renders provide visual fallback for pages selected by
image, table, vector-drawing, or multi-column signals.

## Selection limits

The selected candidate remains subject to manual review for:

- chart values and plotted relationships;
- formulas and superscripts;
- merged or spanning table cells;
- unusual reading order;
- handwriting and low-resolution scans.
