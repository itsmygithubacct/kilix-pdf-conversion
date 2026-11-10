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

### Page OCR packages

The base runtime also contains RapidOCR and ONNX Runtime for page OCR, with
their dependency closure. Each keeps its own licence:

| Package | Licence |
|---|---|
| RapidOCR | Apache-2.0 |
| ONNX Runtime | MIT |
| OpenCV (opencv-python-headless) | Apache-2.0; the wheel bundles FFmpeg under LGPL-2.1 and other libraries listed in its `LICENSE-3RD-PARTY.txt` |
| Shapely | BSD-3-Clause; the wheel bundles GEOS under LGPL-2.1 |
| NumPy | BSD-3-Clause, with bundled OpenBLAS and other components under their own permissive licences |
| Pillow | MIT-CMU |
| OmegaConf | BSD-3-Clause |
| PyYAML, pyclipper, colorlog, six, urllib3, charset-normalizer | MIT |
| Protocol Buffers | BSD-3-Clause |
| FlatBuffers, Requests | Apache-2.0 |
| packaging | Apache-2.0 or BSD-2-Clause |
| idna | BSD-3-Clause |
| tqdm | MPL-2.0 and MIT |
| certifi | MPL-2.0 |

The LGPL libraries are unmodified shared objects loaded at run time and can be
replaced. Each wheel's own licence files are installed with it.

The exact distributed versions and artifact hashes are recorded in
`runtime/uv.lock`.

### Page OCR models and programs

- **PP-OCRv6 small** detector and recogniser: PaddlePaddle's ONNX exports,
  offered under Apache-2.0 by their model cards. They are not part of this
  repository or its wheel. The pinned files and the Apache-2.0 notice that
  accompanies them are listed in `src/kilix_pdf_conversion/data/pp-ocrv6-small.json`.
- **Tesseract** is Apache-2.0. It is not bundled; the operating system's
  `tesseract-ocr` package is run as a separate program.

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
