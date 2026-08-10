# Third-party notices

Kilix PDF Conversion is distributed under AGPL-3.0-only. Copyright (C) 2026
itsmygithubacct. See `LICENSE` for the complete terms and warranty disclaimer.

## Base runtime

The pinned base runtime contains PyMuPDF, PyMuPDF4LLM, and Tabulate. Artifex
offers PyMuPDF and PyMuPDF4LLM under the GNU Affero General Public License and
under commercial licenses. This project and its public base runtime use the
AGPL option. Tabulate is MIT-licensed. Their copyrights remain with their
respective owners.

- PyMuPDF: <https://pymupdf.readthedocs.io/en/latest/about.html#license>
- PyMuPDF4LLM: <https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/>
- Tabulate: <https://github.com/astanin/python-tabulate>

PyMuPDF4LLM is held at 0.3.4 because its later default dependency closure adds
PyMuPDF Layout, which is offered under PolyForm Noncommercial or a commercial
license. PyMuPDF Layout is not part of this public base runtime.

The exact distributed versions and artifact hashes are recorded in
`runtime/uv.lock`.

## Optional model engines

Granite-Docling and Marker are optional integrations. They are not installed by
the base runtime lock and are mutually isolated because their model stacks
have incompatible dependency closures.

- Docling source code is offered under the MIT license. Models used through
  Docling can have separate licenses and acceptable-use terms.
- Marker source code is offered under GPL-3.0. Marker model weights have
  separate terms documented by its publisher.
- PyTorch, Transformers, model files, and other dependencies retain their own
  upstream licenses and notices.

Before installing an optional engine or downloading model weights, review the
notices shipped by that engine and the selected model. Nothing in this project
relicenses third-party code or model artifacts.
