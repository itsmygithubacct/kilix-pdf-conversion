# Command examples

The `kilix-pdf` command line, by example. This text was moved from the
README; the [README](../README.md) is the short entry point.

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
