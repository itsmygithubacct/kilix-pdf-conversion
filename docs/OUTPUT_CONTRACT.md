# Output contract

## Run identity

A run directory is named:

~~~text
<portable-source-slug>--<first-12-source-sha256-characters>
~~~

Changing source bytes creates a new run. The manifest records a digest of the
effective settings and route. Reusing the same output root with different
settings is rejected unless **--force** replaces the complete run directory.

## Required files

| File | Purpose |
|---|---|
| analysis.json | Source classification and structural signals |
| events.jsonl | Append-only lifecycle and timing events |
| manifest.json | Final machine-readable run record |
| report.md | Human-readable decision report |
| canonical.md | Selected candidate with root-relative asset links |

**source.pdf** is included by default and can be disabled. The **visual**
directory is optional and contains selected source-page renders plus an index.

## Candidate layout

~~~text
conversions/<engine>/document.md
conversions/<engine>/assets/*
quality/<engine>.json
~~~

Candidate Markdown links are relative to their candidate directory. Links in
**canonical.md** are rewritten to include the candidate path.

## Manifest schema version 1

Top-level keys:

- schema_version
- configuration_sha256
- created_at
- status
- source
- route
- engine_results
- quality
- canonical_engine
- canonical_path

Paths inside engine results are operational metadata and may be absolute.
Consumers should use canonical_path and the documented directory structure
when moving a completed run.

## Status

- pass: no configured quality warning or failure;
- warn: usable best candidate with one or more review flags;
- fail: no candidate passed hard quality gates.

A failed run can still contain useful candidate files, but it does not publish
**canonical.md**. Consumers must check the manifest status instead of treating
candidate file existence as success.
