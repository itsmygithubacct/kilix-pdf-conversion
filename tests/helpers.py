from __future__ import annotations

from pathlib import Path

from kilix_pdf_conversion.models import (
    Complexity,
    DocumentAnalysis,
    DocumentKind,
)


def analysis_stub(
    source: Path,
    *,
    kind: DocumentKind = DocumentKind.NATIVE,
    complexity: Complexity = Complexity.SIMPLE,
    tables: tuple[int, ...] = (),
    figures: tuple[int, ...] = (),
    max_columns: int = 0,
) -> DocumentAnalysis:
    return DocumentAnalysis(
        source=str(source),
        source_sha256="a" * 64,
        source_bytes=1000,
        page_count=1,
        native_text_characters=1000,
        reliable_text_page_ratio=1.0 if kind is DocumentKind.NATIVE else 0.0,
        replacement_character_ratio=0.0,
        image_count=0,
        drawing_count_sampled=0,
        detected_table_count=len(tables),
        max_detected_table_columns=max_columns,
        table_caption_numbers=tables,
        figure_caption_numbers=figures,
        multi_column_page_count=0,
        sampled_page_numbers=(1,),
        table_scanned_page_numbers=(1,),
        document_kind=kind,
        complexity=complexity,
        complexity_score=8.0 if complexity is Complexity.COMPLEX else 0.0,
    )


def make_native_pdf(path: Path, text: str | None = None) -> Path:
    import pymupdf

    content = text or (
        "A deterministic source paragraph for conversion quality testing. "
        "It contains enough words to produce a useful Markdown document. "
    ) * 8
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(
        pymupdf.Rect(72, 72, 540, 720),
        content,
        fontsize=11,
    )
    document.save(path)
    document.close()
    return path


def make_scan_pdf(path: Path) -> Path:
    import pymupdf

    native_path = path.with_name("native-for-scan.pdf")
    make_native_pdf(native_path)
    native = pymupdf.open(native_path)
    pixmap = native[0].get_pixmap(dpi=120, alpha=False)
    native.close()
    scan = pymupdf.open()
    page = scan.new_page(width=pixmap.width, height=pixmap.height)
    page.insert_image(page.rect, stream=pixmap.tobytes("png"))
    scan.save(path)
    scan.close()
    return path
