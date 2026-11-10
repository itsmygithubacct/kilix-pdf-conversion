# Page OCR

The **page-ocr** engine renders each PDF page and reads it with one of two
CPU OCR engines, chosen per page:

- **Tesseract 5**, the Debian `tesseract-ocr` program with
  `tesseract-ocr-eng`, run as a subprocess with page layout analysis
  (`--psm 3`);
- **RapidOCR 3.10.0** running PaddlePaddle's **PP-OCRv6 small** detector and
  recogniser on ONNX Runtime 1.31.1.

It needs no GPU and no network. It is the complete-coverage engine for scans
and mixed documents on a host without Granite or Marker, and the last
fallback when they are installed. The same reader is available for images as
**kilix-pdf ocr**.

## When the workflow uses it

| Document | Page OCR |
|---|---|
| Native text | Last fallback, after Granite hybrid, Granite pure-VLM and Marker |
| Mixed native and image-only pages | Fallback after Marker; initial candidate in the quality profile |
| Image-only scan | Fallback after Marker; initial candidate in the quality profile |
| Forensic profile | Always run |

Fallbacks run in order and stop at the first usable candidate, so a host with
only the base runtime converts a scan with page OCR. When candidates score
alike, page OCR ranks after Granite pure-VLM for scans and mixed documents and
after Marker for scans (see [engine recommendation](RECOMMENDATION.md)).

## Choosing the engine for a page

RapidOCR is the default. Tesseract is chosen only for a clean, upright page
that holds a figure-sized block, where its layout analysis keeps the figure's
contents out of the body text. The choice uses only cheap image measurements
(numpy and Pillow, no model), made on a copy at most 1600 px long:

| Measure | How |
|---|---|
| Background | Median brightness; a dark page is inverted for the other measures |
| Colour | Share of pixels with clear colour |
| Ink, contrast, ground | Otsu threshold; the ink and ground medians and the ground's 5–95% spread |
| Skew | Angle that makes the row ink profile sharpest, searched to 0.05° within ±12° |
| Lines | Runs of inked rows after levelling: count and median height |
| Sharpness | Strongest horizontal edges relative to contrast |
| Monospace | Amplitude of the repeat at character pitch in the column ink profile |
| Figure | Share of inked rows inside blocks over 3.5 line heights tall |
| Columns | Gutters with text on both sides in most six-line bands (recorded, not used) |

Any one of these sends the page to RapidOCR (policy version 1):

| Reason | Threshold |
|---|---|
| No text lines found | 0 lines |
| Dark background | median brightness below 128 |
| Coloured | over 20% of pixels |
| Uneven ground | 5–95% ground spread over 70 |
| Faint | contrast under 70 |
| Blurred | sharpness under 0.70 |
| Skewed | over 10° |
| Small text | lines under 12 px tall |
| Monospaced | grid strength over 0.38 |
| Few lines | under 8 |

Otherwise a page whose figure share is at least 33% goes to Tesseract and any
other page to RapidOCR. Every decision is recorded with its reasons and
measurements.

With `engine = "auto"`, an engine that is not installed, or that fails on a
page, is replaced by the other and the page record says why. A named engine
never falls back. A page that neither engine can read fails the candidate.

### Reading order

RapidOCR returns one box per run of text and no reading order. The boxes are
levelled by their median angle and cut recursively: first at the widest
vertical gutter at least one line height wide with a column on each side,
otherwise at the widest horizontal break of at least half a line height. A
column must be at least eight line heights wide and its median line at least
four line heights long; short cells side by side are a table and are read row
by row. Each leaf is read row by row.

Tesseract pages are levelled by the measured skew (from 0.3°) before reading
and keep Tesseract's own layout.

## Measurements

109 page images with reference text: 64 for development and 45 held out, made
after the first thresholds were fixed. They are synthetic pages and PDF
renders in English. They cover clean, blurred, skewed, small, dark, coloured,
scanned, photographed, two- and three-column, figure, table, terminal and
mathematics pages. One newspaper photograph is scored apart because its
reference holds only the headlines.

Mean character error rate, after normalising whitespace, quotes and dashes:

| Set | Tesseract only | RapidOCR, row order | RapidOCR, column order | Page OCR (auto) | Better engine per page |
|---|---|---|---|---|---|
| Development (64) | 5.77% | 7.47% | 3.17% | 2.61% | 2.61% |
| Held-out (45) | 13.75% | 19.62% | 8.38% | 8.39% | 8.38% |

- The page OCR column was measured through `OcrReader` with the pinned assets,
  Debian's Tesseract 5.5.0 and the network blocked. It sent 3 of 109 pages to
  Tesseract.
- Column ordering is most of the gain. Column pages fell from about 70% to
  under 1% with RapidOCR.
- The held-out set is not fully blind: its first run exposed misses that were
  then fixed.
- About 2.4 s per page at four threads on the development machine's CPU,
  including 0.1–0.5 s of measuring.

## Limits

- Output is plain paragraphs. There are no headings, tables, lists or
  formulas; each page starts with `<!-- page N · engine -->`.
- Mathematics pages are read badly by both engines. Use Granite pure-VLM.
- Terminal screenshots score 0.1–1.3% on the development set but 14–18% on
  the held-out set, whose terminal text has long rule lines and wide gaps that
  neither engine reproduces.
- Pages must be upright. RapidOCR's text-angle classifier is disabled: it
  turned some upright lines upside down, raising RapidOCR's mean error on 52
  development images from 2.24% to 3.69%, and by up to 11 points on terminal
  pages. A page turned 90° or 180° is not corrected.
- The thresholds were set on 64 images and checked on 45. There are no real
  phone photographs, handwriting or non-English pages in the measurements.
- `ocr.language` applies to Tesseract only. The PP-OCRv6 recogniser has a
  fixed 18,708-character table covering Chinese, Japanese, Latin and other
  scripts.

## Model assets

The two PP-OCRv6 small assets are PaddlePaddle's own ONNX exports on Hugging
Face, pinned in `src/kilix_pdf_conversion/data/pp-ocrv6-small.json`:

| Asset | Repository | Revision | Files |
|---|---|---|---|
| `pp-ocrv6-small-det` | PaddlePaddle/PP-OCRv6_small_det_onnx | 28fe5895c24fd108c19eb3e8479f4ab385fbfc62 | `inference.onnx` (9,880,512 bytes) |
| `pp-ocrv6-small-rec` | PaddlePaddle/PP-OCRv6_small_rec_onnx | b8f84f0b80c529de40b4fbb3544b84fa7233a513 | `inference.onnx` (21,159,378 bytes), `inference.yml` (150,579 bytes) |

Both carry `notices/LICENSE-apache-2.0.txt`. Both model cards state Apache-2.0.
The application never downloads them. They are found, in order, at
`ocr.model_directory`, `$KILIX_OCR_MODEL_DIR`, or
`$KILIX_CONTENT_ROOT/assets`, each holding one directory per asset id.

Every file is checked for type, confinement, size and SHA-256 and then read
into memory, and the ONNX sessions are built from those bytes, so a file
replaced after the check is never loaded. The recogniser's character table
comes from `inference.yml`; its model name, decoder, length and hash are
checked too. RapidOCR's download helper is replaced by one that refuses.

In the measurements above, the official exports gave text identical to
RapidOCR's own converted models on all 110 images.

## Configuration

~~~toml
[ocr]
engine = "auto"      # auto, tesseract or rapidocr
dpi = 200            # page render resolution, 72-600
language = "eng"     # Tesseract language codes joined by +
threads = 4          # Tesseract OMP threads and ONNX Runtime intra-op threads
page_timeout = 120   # seconds per Tesseract page
# model_directory = "/path/to/assets"
~~~

Pages over 36 megapixels at the configured DPI are rendered at a lower DPI.
`KILIX_OCR_TESSERACT` names a Tesseract binary other than the one on `PATH`.

## Command line

~~~sh
kilix-pdf ocr page.png                    # text from the routed engine
kilix-pdf ocr --route-only page.png       # which engine, and why
kilix-pdf ocr --engine tesseract page.png
kilix-pdf ocr --json scans/*.png          # text, engine, reasons, measurements
kilix-pdf doctor                          # Tesseract and RapidOCR status
~~~

**kilix-pdf ocr** reads images; PDFs go through **kilix-pdf convert**. A
declared image DPI between 70 and 1200 is passed to Tesseract.

## Output

The candidate directory `conversions/page-ocr/` holds `document.md` and
`ocr-pages.json`. The page record lists, for each page: the DPI, the engine
that produced the text, the router's choice and reasons, any fallback, the
time, the character count and the measurements. The engine result's metadata
gives pages per engine, fallback pages, the model revisions and the router
policy version.

## Tests

Unit tests use fake engines. To run both real engines:

~~~sh
KILIX_OCR_INTEGRATION=1 KILIX_OCR_MODEL_DIR=/path/to/assets make test
# add KILIX_OCR_TESSERACT=/path/to/tesseract when it is not on PATH
~~~
