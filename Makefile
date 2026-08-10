PYTHON ?= python3
RUNTIME_DIR ?= .runtime
RUNTIME_PY := $(RUNTIME_DIR)/bin/python

.DEFAULT_GOAL := help

.PHONY: help test lint doctor verify build runtime runtime-check

help:
	@printf '%s\n' \
		'Kilix PDF Conversion' \
		'' \
		'  make test    Run the unit test suite' \
		'  make lint    Run Ruff checks' \
		'  make doctor  Inspect runtime capabilities' \
		'  make verify  Run lint, tests, and the base doctor check' \
		'  make build   Build wheel and source distribution' \
		'  make runtime Build the pinned Python runtime without uv' \
		'  make runtime-check  Verify the pinned runtime and launcher'

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

doctor:
	$(PYTHON) -m kilix_pdf_conversion doctor

verify: lint test doctor

build:
	$(PYTHON) -m build

runtime:
	$(PYTHON) -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
	$(PYTHON) -m venv "$(RUNTIME_DIR)"
	"$(RUNTIME_PY)" -m pip --disable-pip-version-check install \
		--require-hashes --only-binary=:all: \
		-r requirements/runtime-py311.lock
	"$(RUNTIME_PY)" -c 'import pymupdf; pymupdf.no_recommend_layout(); import pymupdf4llm'

runtime-check:
	@test -x "$(RUNTIME_PY)" || { echo 'runtime missing; run make runtime' >&2; exit 1; }
	./kilix-pdf doctor
