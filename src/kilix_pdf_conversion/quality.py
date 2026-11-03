from __future__ import annotations

import html
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from .config import ValidationSettings
from .models import (
    DocumentAnalysis,
    EngineName,
    QualityReport,
    QualityStatus,
)
from .text_evidence import TextTrust, inspect_source_text

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:['.-][a-z0-9]+)*")
TABLE_CAPTION_LINE = re.compile(
    r"(?im)^[ \t|>#*_~-]*table\s+([0-9]{1,3})\b"
)
FIGURE_CAPTION_LINE = re.compile(
    r"(?im)^[ \t|>#*_~-]*(?:figure|fig\.)\s*([0-9]{1,3})\b"
)
TABLE_SEPARATOR = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$")
IMAGE_LINK = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
HTML_IMAGE = re.compile(
    r"(?i)<img\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"']"
)
EMPTY_MATH = re.compile(r"\$\$\s*\$\$", re.MULTILINE)


def normalize_tokens(text: str, *, markdown: bool = False) -> list[str]:
    text = html.unescape(text)
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    if markdown:
        text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
        text = re.sub(r"</?br\s*/?>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"!\[([^\]]*)]\([^)]+\)", r" \1 ", text)
        text = re.sub(r"\[([^\]]+)]\([^)]+\)", r" \1 ", text)
    return TOKEN_PATTERN.findall(text.casefold())


def extract_native_text(source: Path) -> str:
    import pymupdf

    document = pymupdf.open(source)
    try:
        return "\n".join(page.get_text("text", sort=True) for page in document)
    finally:
        document.close()


def markdown_table_metrics(markdown: str) -> tuple[int, int]:
    lines = markdown.splitlines()
    block_count = 0
    maximum_columns = 0
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        block: list[str] = []
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            block.append(lines[index].strip())
            index += 1
        if any(TABLE_SEPARATOR.match(line) for line in block):
            block_count += 1
            maximum_columns = max(
                maximum_columns,
                max((max(line.count("|") - 1, 0) for line in block), default=0),
            )
    block_count += len(re.findall(r"(?i)<table\b", markdown))
    return block_count, maximum_columns


def repeated_short_line(markdown: str) -> tuple[str | None, int]:
    short_lines = [
        line.strip()
        for line in markdown.splitlines()
        if line.strip() and len(line.strip()) <= 4
    ]
    if not short_lines:
        return None, 0
    value, count = Counter(short_lines).most_common(1)[0]
    return value, count


def image_reference_metrics(
    markdown: str,
    markdown_path: Path,
) -> tuple[int, int, int, int, int]:
    references = [*IMAGE_LINK.findall(markdown), *HTML_IMAGE.findall(markdown)]
    broken = 0
    absolute = 0
    external = 0
    escaping = 0
    markdown_dir = markdown_path.parent.resolve()
    asset_root = markdown_dir / "assets"
    for reference in references:
        destination = reference.strip()
        if destination.startswith("<") and destination.endswith(">"):
            destination = destination[1:-1]
        else:
            destination = destination.split(maxsplit=1)[0]
        parsed = urlsplit(destination)
        if parsed.netloc or (parsed.scheme and parsed.scheme != "file"):
            external += 1
            continue
        decoded_path = unquote(parsed.path)
        if parsed.scheme == "file" or Path(decoded_path).is_absolute():
            absolute += 1
            continue
        if not decoded_path or "\x00" in decoded_path or "\\" in decoded_path:
            escaping += 1
            continue
        relative = PurePosixPath(decoded_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or relative.parts[0] != "assets"
        ):
            escaping += 1
            continue
        candidate = markdown_dir.joinpath(*relative.parts)
        try:
            target = candidate.resolve(strict=False)
            target.relative_to(asset_root)
        except (OSError, ValueError):
            escaping += 1
            continue
        if candidate.is_symlink():
            escaping += 1
        elif not target.is_file():
            broken += 1
    return len(references), broken, absolute, external, escaping


def validate_markdown(
    source: Path,
    markdown_path: Path,
    engine: EngineName,
    analysis: DocumentAnalysis,
    settings: ValidationSettings,
) -> QualityReport:
    markdown = markdown_path.read_text(encoding="utf-8")
    markdown_bytes = markdown_path.stat().st_size
    tokens = normalize_tokens(markdown, markdown=True)
    table_blocks, maximum_columns = markdown_table_metrics(markdown)
    # A prose reference such as "shown in Table 3" does not prove that the
    # corresponding table survived conversion. Count caption-like lines only.
    table_numbers = {int(value) for value in TABLE_CAPTION_LINE.findall(markdown)}
    figure_numbers = {int(value) for value in FIGURE_CAPTION_LINE.findall(markdown)}
    placeholder_count = markdown.count("<!-- image -->")
    (
        image_references,
        broken_images,
        absolute_images,
        external_images,
        escaping_images,
    ) = image_reference_metrics(markdown, markdown_path)
    repeated_line, repeated_count = repeated_short_line(markdown)
    empty_math_count = len(EMPTY_MATH.findall(markdown))
    heading_count = len(re.findall(r"(?m)^#{1,6}\s+", markdown))

    native_recall: float | None = None
    native_precision: float | None = None
    evidence = inspect_source_text(source)
    reference_tokens = normalize_tokens(evidence.reference_text)
    if reference_tokens:
        reference_counter = Counter(reference_tokens)
        output_counter = Counter(tokens)
        overlap = sum((reference_counter & output_counter).values())
        native_recall = overlap / len(reference_tokens)
        native_precision = overlap / len(tokens) if tokens else 0.0

    errors: list[str] = []
    warnings: list[str] = []
    evidence_warnings: list[str] = []
    if markdown_bytes < settings.minimum_markdown_bytes:
        errors.append(
            f"output is {markdown_bytes} bytes; minimum is "
            f"{settings.minimum_markdown_bytes}"
        )
    if not tokens:
        errors.append("output contains no searchable tokens")
    if (
        repeated_line is not None
        and repeated_count > settings.maximum_repeated_short_line_count
    ):
        fragment = normalize_tokens(repeated_line, markdown=True)
        supported_count = sum(
            reference_tokens[i:i + len(fragment)] == fragment
            for i in range(len(reference_tokens) - len(fragment) + 1)
        ) if fragment else 0
        if evidence.complete_reference and fragment and repeated_count > supported_count:
            errors.append(
                f"short line {repeated_line!r} repeats {repeated_count} times; "
                f"the supported source contains {supported_count} occurrences"
            )
        elif not evidence.complete_reference or not fragment:
            evidence_warnings.append(
                f"short line {repeated_line!r} repeats {repeated_count} times; "
                "source support for this repetition is unverified"
            )
    if placeholder_count and settings.fail_on_image_placeholders:
        errors.append(f"output contains {placeholder_count} unresolved image placeholders")
    if broken_images:
        errors.append(f"output references {broken_images} missing local image assets")
    if absolute_images:
        errors.append(f"output contains {absolute_images} nonportable absolute image paths")
    if external_images:
        errors.append(f"output contains {external_images} external image references")
    if escaping_images:
        errors.append(
            f"output contains {escaping_images} image paths outside the assets bundle"
        )
    if empty_math_count:
        warnings.append(f"output contains {empty_math_count} empty display-math blocks")
    if native_recall is not None:
        if native_recall < 0.65:
            errors.append(f"native-token recall is critically low ({native_recall:.1%})")
        elif native_recall < settings.minimum_native_token_recall:
            warnings.append(
                f"native-token recall {native_recall:.1%} is below "
                f"{settings.minimum_native_token_recall:.1%}"
            )

    # Captions inferred from a hidden layer are not authoritative either.
    expected_tables = len({int(v) for v in TABLE_CAPTION_LINE.findall(evidence.reference_text)})
    expected_figures = len({int(v) for v in FIGURE_CAPTION_LINE.findall(evidence.reference_text)})
    if expected_tables and len(table_numbers) < max(1, round(expected_tables * 0.70)):
        warnings.append(
            f"only {len(table_numbers)} of {expected_tables} numbered tables are represented"
        )
    if expected_figures and len(figure_numbers) < max(1, round(expected_figures * 0.70)):
        warnings.append(
            f"only {len(figure_numbers)} of {expected_figures} numbered figures are represented"
        )
    if (
        evidence.complete_reference
        and analysis.max_detected_table_columns >= 4
        and maximum_columns < analysis.max_detected_table_columns * 0.65
    ):
        warnings.append(
            "maximum Markdown table width is substantially below the source detector"
        )

    # Source uncertainty alone retains a useful native/OCR extraction for review;
    # it is not an automatic request to load another expensive model.
    fallback_recommended = bool(errors or warnings)
    warnings.extend(evidence_warnings)
    if evidence.trust is not TextTrust.TRUSTED:
        warnings.append(
            f"source text is {evidence.trust.value}; only render-supported pages "
            "are used for agreement checks; content accuracy is unverified"
        )
        fallback_recommended |= evidence.trust is TextTrust.SUSPECT
    if any(page.image_content_unchecked for page in evidence.pages):
        warnings.append("text inside source images has not been independently checked")

    score = 100.0
    score -= len(errors) * 30
    score -= len(warnings) * 7
    if native_recall is not None:
        score -= max(0.0, 0.98 - native_recall) * 40
    if expected_tables:
        score -= max(0, expected_tables - len(table_numbers)) * 1.5
    if expected_figures:
        score -= max(0, expected_figures - len(figure_numbers))
    score = max(0.0, min(100.0, score))
    status = (
        QualityStatus.FAIL
        if errors
        else QualityStatus.WARN
        if warnings
        else QualityStatus.PASS
    )
    return QualityReport(
        engine=engine,
        status=status,
        score=round(score, 3),
        markdown_bytes=markdown_bytes,
        token_count=len(tokens),
        heading_count=heading_count,
        table_block_count=table_blocks,
        max_markdown_table_columns=maximum_columns,
        image_reference_count=image_references,
        image_placeholder_count=placeholder_count,
        broken_image_reference_count=broken_images,
        absolute_image_reference_count=absolute_images,
        external_image_reference_count=external_images,
        escaping_image_reference_count=escaping_images,
        native_token_recall=(
            round(native_recall, 6) if native_recall is not None else None
        ),
        native_token_precision=(
            round(native_precision, 6) if native_precision is not None else None
        ),
        expected_table_captions=expected_tables,
        observed_table_captions=len(table_numbers),
        expected_figure_captions=expected_figures,
        observed_figure_captions=len(figure_numbers),
        repeated_short_line=repeated_line,
        repeated_short_line_count=repeated_count,
        empty_math_block_count=empty_math_count,
        errors=tuple(errors),
        warnings=tuple(warnings),
        source_text_evidence=evidence.summary(),
        fallback_recommended=fallback_recommended,
    )
