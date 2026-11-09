# Installation and development

How to build the managed runtime, the optional model engines and the
development tools. This text was moved from the README; the
[README](../README.md) is the short entry point.

## Installation

Python 3.11 or newer and `uv` are required.

### Plebian OS and Kilix runtime

The managed runtime is created from the checked-in `runtime/uv.lock`.
That lock contains only the small AGPL-compatible base runtime; optional model
engines cannot leak into it. `--frozen` prevents installation from silently
changing that dependency closure:

~~~sh
make runtime
./kilix-pdf doctor
./kilix-pdf
~~~

The no-argument launcher starts a guided terminal session. A PDF may also be
opened directly, which is the path used by desktop launchers and file
associations:

~~~sh
./kilix-pdf report.pdf
~~~

### Base and development tools

The Make targets provision their development tools through `uv`; they do not
depend on pytest, Ruff, or build being installed in the system interpreter:

~~~sh
make test
make lint
make build
~~~

### Granite-Docling

Granite is an optional extra because GPU-enabled PyTorch installation depends
on the local accelerator and driver:

~~~sh
uv pip install --python .venv/bin/python -e '.[granite]'
~~~

Install the appropriate PyTorch build for the machine after consulting the
PyTorch compatibility matrix. An 8 GiB GPU should start with a one-page batch.

### Marker

~~~sh
uv pip install --python .venv/bin/python -e '.[marker]'
~~~

Marker and Granite have large, mutually incompatible model/runtime dependency
closures and must use separate virtual environments. Neither is installed by
the base runtime. The CLI can be invoked with the interpreter that owns
the desired engine. The **--device** override applies to both model adapters,
so **--device cpu** provides a low-memory Marker fallback. Review the model and
code licenses in [the third-party notices](../THIRD-PARTY-NOTICES.md) first.

## Development

~~~sh
make test
make lint
make verify
make build
~~~

The unit tests create PDFs in temporary directories and do not require bundled
document fixtures. Granite and Marker integration tests are intentionally
separate from the fast unit suite.
