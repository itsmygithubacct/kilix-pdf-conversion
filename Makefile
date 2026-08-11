PYTHON ?= python3
UV ?= uv
RUNTIME_DIR ?= .runtime
RUNTIME_PROJECT ?= runtime
RUNTIME_PY := $(RUNTIME_DIR)/bin/python
RUNTIME_ENV := $(abspath $(RUNTIME_DIR))
UV_DEV := "$(UV)" run --no-project --python "$(PYTHON)" --with-editable . --with pytest --with ruff --with build

.DEFAULT_GOAL := help

.PHONY: help uv-check test lint doctor verify build runtime runtime-check

help:
	@printf '%s\n' \
		'Kilix PDF Conversion' \
		'' \
		'  make test    Run the unit test suite' \
		'  make lint    Run Ruff checks' \
		'  make doctor  Inspect runtime capabilities' \
		'  make verify  Run lint, tests, and the base doctor check' \
		'  make build   Build wheel and source distribution' \
		'  make runtime Build the frozen uv-managed Python runtime' \
		'  make runtime-check  Verify the pinned runtime and launcher'

uv-check:
	command -v "$(UV)" >/dev/null 2>&1 || { \
		echo 'uv is required' >&2; exit 1; }

test: uv-check
	$(UV_DEV) python -m pytest

lint: uv-check
	$(UV_DEV) python -m ruff check .

doctor: uv-check
	$(UV_DEV) kilix-pdf doctor

verify: lint test doctor

build: uv-check
	$(UV_DEV) python -m build

runtime:
	$(PYTHON) -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
	command -v "$(UV)" >/dev/null 2>&1 || { \
		echo 'uv is required to build the managed runtime' >&2; exit 1; }
	UV_PROJECT_ENVIRONMENT="$(RUNTIME_ENV)" "$(UV)" sync \
		--project "$(RUNTIME_PROJECT)" --frozen --no-dev \
		--no-install-project --python "$(PYTHON)"
	"$(RUNTIME_PY)" -c 'import pymupdf; pymupdf.no_recommend_layout(); import pymupdf4llm'

runtime-check:
	@test -x "$(RUNTIME_PY)" || { echo 'runtime missing; run make runtime' >&2; exit 1; }
	./kilix-pdf doctor
