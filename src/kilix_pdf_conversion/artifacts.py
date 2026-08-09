from __future__ import annotations

import re
import shutil
from pathlib import Path

from .models import DocumentAnalysis, EngineName
from .util import atomic_write_bytes, atomic_write_text


def copy_source(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    shutil.copy2(source, temporary)
    temporary.replace(destination)


def visual_page_numbers(analysis: DocumentAnalysis, maximum: int = 24) -> tuple[int, ...]:
    selected = [
        page.page_number
        for page in analysis.pages
        if page.image_count
        or page.table_count
        or page.drawing_count >= 8
        or page.multi_column
    ]
    return tuple(dict.fromkeys(selected))[:maximum]


def render_visual_pages(
    source: Path,
    analysis: DocumentAnalysis,
    output_dir: Path,
    *,
    dpi: int = 120,
) -> tuple[Path, ...]:
    import pymupdf

    pages = visual_page_numbers(analysis)
    if not pages:
        return ()
    output_dir.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open(source)
    rendered: list[Path] = []
    try:
        for page_number in pages:
            page = document[page_number - 1]
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            destination = output_dir / f"page-{page_number:04d}.jpg"
            atomic_write_bytes(
                destination,
                pixmap.tobytes("jpeg", jpg_quality=82),
            )
            rendered.append(destination)
    finally:
        document.close()

    lines = [
        "# Visual source pages",
        "",
        "These renders preserve visual context independently of conversion-engine output.",
        "",
    ]
    for path in rendered:
        lines.extend([f"## Page {int(path.stem.rsplit('-', 1)[1])}", "", f"![]({path.name})", ""])
    atomic_write_text(output_dir / "index.md", "\n".join(lines).rstrip() + "\n")
    return tuple(rendered)


def canonical_markdown(
    candidate_path: Path,
    engine: EngineName,
    destination: Path,
) -> None:
    markdown = candidate_path.read_text(encoding="utf-8")
    prefix = f"conversions/{engine.value}/assets/"
    markdown = re.sub(r"\]\(assets/", f"]({prefix}", markdown)
    markdown = re.sub(r'(?i)(src=["\'])assets/', rf"\1{prefix}", markdown)
    atomic_write_text(destination, markdown)
