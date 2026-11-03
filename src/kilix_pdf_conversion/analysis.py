from __future__ import annotations

import math
import re
import stat
import statistics
from pathlib import Path

from .models import Complexity, DocumentAnalysis, DocumentKind, PageSignal
from .text_evidence import SourceTextEvidence, TextTrust, inspect_page_text
from .util import sha256_file

TABLE_REFERENCE = re.compile(r"(?i)\btable\s+([0-9]{1,3})\b")
FIGURE_REFERENCE = re.compile(r"(?i)\b(?:figure|fig\.)\s*([0-9]{1,3})\b")


class AnalysisError(RuntimeError):
    pass


def evenly_spaced_pages(page_count: int, maximum: int = 12) -> tuple[int, ...]:
    if page_count <= 0:
        return ()
    count = min(page_count, maximum)
    if count == 1:
        return (0,)
    return tuple(
        sorted({round(index * (page_count - 1) / (count - 1)) for index in range(count)})
    )


def _looks_multi_column(blocks: list[tuple], page_width: float) -> bool:
    midpoint = page_width / 2
    left_characters = 0
    right_characters = 0
    for block in blocks:
        x0, _y0, x1, _y1, text = block[:5]
        character_count = sum(not character.isspace() for character in text)
        if x1 <= midpoint * 1.12:
            left_characters += character_count
        elif x0 >= midpoint * 0.88:
            right_characters += character_count
    return left_characters >= 180 and right_characters >= 180


def _replacement_ratio(text: str) -> float:
    if not text:
        return 0.0
    suspect = text.count("\ufffd") + text.count("\x00")
    return suspect / len(text)


def analyze_pdf(
    source: Path,
    *,
    reliable_page_characters: int = 80,
    native_page_ratio: float = 0.80,
    scan_page_ratio: float = 0.20,
    max_table_scan_pages: int = 24,
) -> DocumentAnalysis:
    try:
        import pymupdf
    except ImportError as error:
        raise AnalysisError("PyMuPDF is required for PDF analysis") from error

    source = source.expanduser().resolve()
    if not source.is_file():
        raise AnalysisError(f"PDF does not exist: {source}")
    if source.suffix.casefold() != ".pdf":
        raise AnalysisError(f"input is not a PDF: {source}")

    initial_stat = source.stat()
    if not stat.S_ISREG(initial_stat.st_mode):
        raise AnalysisError(f"PDF is not a regular file: {source}")
    source_sha256 = sha256_file(source)
    hashed_stat = source.stat()
    initial_identity = (
        initial_stat.st_dev,
        initial_stat.st_ino,
        initial_stat.st_size,
        initial_stat.st_mtime_ns,
    )
    hashed_identity = (
        hashed_stat.st_dev,
        hashed_stat.st_ino,
        hashed_stat.st_size,
        hashed_stat.st_mtime_ns,
    )
    if initial_identity != hashed_identity:
        raise AnalysisError("PDF changed while its content hash was being computed")

    try:
        document = pymupdf.open(source)
    except Exception as error:
        raise AnalysisError(f"cannot open PDF: {error}") from error

    try:
        if document.needs_pass:
            raise AnalysisError("encrypted PDF requires a password")
        page_count = len(document)
        if page_count == 0:
            raise AnalysisError("PDF contains no pages")

        sampled_pages = evenly_spaced_pages(page_count)
        sampled_set = set(sampled_pages)
        page_texts: list[str] = []
        page_images: list[int] = []
        multi_column_pages: set[int] = set()
        table_caption_numbers: set[int] = set()
        figure_caption_numbers: set[int] = set()
        replacement_characters = 0
        native_characters = 0
        text_evidence = []

        for index, page in enumerate(document):
            text = page.get_text("text", sort=True)
            blocks = page.get_text("blocks", sort=True)
            page_texts.append(text)
            native_characters += len(text)
            replacement_characters += text.count("\ufffd") + text.count("\x00")
            table_caption_numbers.update(int(value) for value in TABLE_REFERENCE.findall(text))
            figure_caption_numbers.update(int(value) for value in FIGURE_REFERENCE.findall(text))
            page_images.append(len(page.get_images(full=True)))
            text_evidence.append(inspect_page_text(page))
            if _looks_multi_column(blocks, page.rect.width):
                multi_column_pages.add(index)

        reliable_pages = {
            index
            for index, text in enumerate(page_texts)
            if sum(not character.isspace() for character in text)
            >= reliable_page_characters
            and _replacement_ratio(text) <= 0.005
        }
        reliable_ratio = len(reliable_pages) / page_count
        replacement_ratio = (
            replacement_characters / native_characters if native_characters else 0.0
        )

        if reliable_ratio >= native_page_ratio and replacement_ratio <= 0.005:
            document_kind = DocumentKind.NATIVE
        elif reliable_ratio <= scan_page_ratio:
            document_kind = DocumentKind.SCAN
        else:
            document_kind = DocumentKind.MIXED

        caption_pages = {
            index
            for index, text in enumerate(page_texts)
            if TABLE_REFERENCE.search(text)
        }
        table_scan_pages = sorted(caption_pages | sampled_set)[:max_table_scan_pages]
        table_counts: dict[int, int] = {}
        max_table_columns: dict[int, int] = {}
        drawing_counts: dict[int, int] = {}
        warnings: list[str] = []
        source_evidence = SourceTextEvidence(tuple(text_evidence))
        if source_evidence.trust is not TextTrust.TRUSTED:
            warnings.append(
                "the extracted text has uncertain rendering support; agreement with it "
                "does not verify visible content"
            )

        for index in table_scan_pages:
            page = document[index]
            try:
                drawing_counts[index] = len(page.get_drawings())
            except Exception as error:
                drawing_counts[index] = 0
                warnings.append(f"page {index + 1}: drawing inspection failed: {error}")
            try:
                tables = page.find_tables().tables
            except Exception as error:
                tables = []
                warnings.append(f"page {index + 1}: table inspection failed: {error}")
            table_counts[index] = len(tables)
            widths = []
            for table in tables:
                data = table.extract()
                widths.extend(len(row) for row in data if row)
            max_table_columns[index] = max(widths, default=0)

        page_signals: list[PageSignal] = []
        for index in range(page_count):
            text = page_texts[index]
            page_signals.append(
                PageSignal(
                    page_number=index + 1,
                    native_characters=len(text),
                    nonspace_characters=sum(
                        not character.isspace() for character in text
                    ),
                    image_count=page_images[index],
                    drawing_count=drawing_counts.get(index, 0),
                    table_count=table_counts.get(index, 0),
                    max_table_columns=max_table_columns.get(index, 0),
                    multi_column=index in multi_column_pages,
                    reliable_text=index in reliable_pages,
                    source_text_trust=text_evidence[index].trust.value,
                )
            )

        detected_tables = sum(table_counts.values())
        sampled_drawings = sum(drawing_counts.values())
        complexity_score = (
            detected_tables * 3.0
            + len(table_caption_numbers) * 0.8
            + len(figure_caption_numbers) * 0.8
            + min(sum(page_images), 30) * 0.25
            + (len(multi_column_pages) / page_count) * 8.0
            + math.log2(max(sampled_drawings, 1)) * 0.5
        )
        complexity = (
            Complexity.COMPLEX if complexity_score >= 5.0 else Complexity.SIMPLE
        )

        sampled_nonspace = [
            sum(not character.isspace() for character in page_texts[index])
            for index in sampled_pages
        ]
        if document_kind is DocumentKind.NATIVE and sampled_nonspace:
            median = statistics.median(sampled_nonspace)
            if median < reliable_page_characters * 2:
                warnings.append("native text is present but sparse on sampled pages")
        if len(table_scan_pages) == max_table_scan_pages and len(caption_pages) > len(
            table_scan_pages
        ):
            warnings.append("table scan was capped before every caption page was inspected")

        final_sha256 = sha256_file(source)
        final_stat = source.stat()
        final_identity = (
            final_stat.st_dev,
            final_stat.st_ino,
            final_stat.st_size,
            final_stat.st_mtime_ns,
        )
        if final_identity != initial_identity or final_sha256 != source_sha256:
            raise AnalysisError("PDF changed while it was being analyzed")

        return DocumentAnalysis(
            source=str(source),
            source_sha256=source_sha256,
            source_bytes=initial_stat.st_size,
            page_count=page_count,
            native_text_characters=native_characters,
            reliable_text_page_ratio=round(reliable_ratio, 6),
            replacement_character_ratio=round(replacement_ratio, 8),
            image_count=sum(page_images),
            drawing_count_sampled=sampled_drawings,
            detected_table_count=detected_tables,
            max_detected_table_columns=max(max_table_columns.values(), default=0),
            table_caption_numbers=tuple(sorted(table_caption_numbers)),
            figure_caption_numbers=tuple(sorted(figure_caption_numbers)),
            multi_column_page_count=len(multi_column_pages),
            sampled_page_numbers=tuple(index + 1 for index in sampled_pages),
            table_scanned_page_numbers=tuple(index + 1 for index in table_scan_pages),
            document_kind=document_kind,
            complexity=complexity,
            complexity_score=round(complexity_score, 3),
            pages=tuple(page_signals),
            warnings=tuple(warnings),
            source_text_evidence=source_evidence.summary(),
        )
    finally:
        document.close()
