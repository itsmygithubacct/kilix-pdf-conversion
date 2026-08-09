PYTHON ?= python3

.DEFAULT_GOAL := help

.PHONY: help test lint doctor verify build

help:
	@printf '%s\n' \
		'Kilix PDF Conversion' \
		'' \
		'  make test    Run the unit test suite' \
		'  make lint    Run Ruff checks' \
		'  make doctor  Inspect runtime capabilities' \
		'  make verify  Run lint, tests, and the base doctor check' \
		'  make build   Build wheel and source distribution'

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

doctor:
	$(PYTHON) -m kilix_pdf_conversion doctor

verify: lint test doctor

build:
	$(PYTHON) -m build
