from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

from .models import DocumentAnalysis, EngineName
from .util import atomic_write_bytes, atomic_write_text


def copy_source(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str | None = None,
) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    source_flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        source_descriptor = os.open(source, source_flags)
    except OSError as error:
        raise RuntimeError(f"cannot open source PDF safely: {source}") from error
    temporary_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".part",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    try:
        before = os.fstat(source_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f"source PDF is not a regular file: {source}")
        with (
            os.fdopen(source_descriptor, "rb") as input_file,
            os.fdopen(temporary_descriptor, "wb") as output_file,
        ):
            while chunk := input_file.read(1024 * 1024):
                digest.update(chunk)
                output_file.write(chunk)
            after = os.fstat(input_file.fileno())
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise RuntimeError("source PDF changed while it was being copied")
            output_file.flush()
            os.fsync(output_file.fileno())
        actual_sha256 = digest.hexdigest()
        if expected_sha256 is not None and actual_sha256 != expected_sha256:
            raise RuntimeError("source PDF changed after analysis; conversion aborted")
        temporary.replace(destination)
        return actual_sha256
    except Exception:
        try:
            os.close(source_descriptor)
        except OSError:
            pass
        try:
            os.close(temporary_descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def visual_page_numbers(analysis: DocumentAnalysis, maximum: int = 24) -> tuple[int, ...]:
    selected = [
        page.page_number
        for page in analysis.pages
        if page.image_count
        or page.table_count
        or page.drawing_count >= 8
        or page.multi_column
    ]
    selected = list(dict.fromkeys(selected))
    if maximum <= 0:
        return ()
    if len(selected) <= maximum:
        return tuple(selected)
    if maximum == 1:
        return (selected[0],)
    positions = {
        round(index * (len(selected) - 1) / (maximum - 1))
        for index in range(maximum)
    }
    return tuple(selected[index] for index in sorted(positions))


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
