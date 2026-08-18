from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from . import __version__
from .analysis import AnalysisError, analyze_pdf
from .capabilities import (
    available_engine_names,
    base_is_ready,
    detect_capabilities,
)
from .config import AppConfig, load_config, with_overrides
from .models import EngineName, Profile, QualityStatus
from .quality import validate_markdown
from .recommendation import recommend_conversion
from .workflow import Workflow


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        help="TOML configuration file; defaults are used when omitted",
    )


def _add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        choices=[profile.value for profile in Profile],
        help="conversion profile override",
    )


def _analysis(source: Path, config: AppConfig):
    return analyze_pdf(
        source,
        reliable_page_characters=config.analysis.reliable_page_characters,
        native_page_ratio=config.analysis.native_page_ratio,
        scan_page_ratio=config.analysis.scan_page_ratio,
        max_table_scan_pages=config.analysis.max_table_scan_pages,
    )


def _configured(args: argparse.Namespace) -> AppConfig:
    config = load_config(getattr(args, "config", None))
    profile = Profile(args.profile) if getattr(args, "profile", None) else None
    output_root = getattr(args, "output_root", None)
    force = True if getattr(args, "force", False) else None
    device = getattr(args, "device", None)
    config = with_overrides(
        config,
        profile=profile,
        output_root=output_root,
        force=force,
        device=device,
    )
    workflow = config.workflow
    if getattr(args, "no_source", False):
        workflow = replace(workflow, copy_source=False)
    if getattr(args, "no_visual_pages", False):
        workflow = replace(workflow, render_visual_pages=False)
    granite = config.granite
    if getattr(args, "chart_extraction", False):
        granite = replace(granite, chart_extraction=True)
    return replace(config, workflow=workflow, granite=granite)


def _print_analysis(analysis) -> None:
    print(f"source: {analysis.source}")
    print(f"pages: {analysis.page_count}")
    print(f"class: {analysis.document_kind.value}")
    print(f"complexity: {analysis.complexity.value} ({analysis.complexity_score:.2f})")
    print(f"reliable text pages: {analysis.reliable_text_page_ratio:.1%}")
    print(f"detected tables: {analysis.detected_table_count}")
    print(f"numbered table references: {len(analysis.table_caption_numbers)}")
    print(f"numbered figure references: {len(analysis.figure_caption_numbers)}")


def command_doctor(args: argparse.Namespace) -> int:
    capabilities = detect_capabilities()
    if args.json:
        print(json.dumps(capabilities, indent=2, sort_keys=True))
    else:
        print(f"Python: {capabilities['python']}")
        for group in ("base", "optional"):
            for name, item in capabilities[group].items():
                state = "available" if item["available"] else "missing"
                detail = f" {item['version']}" if item["version"] else ""
                print(f"{name}: {state}{detail}")
        accelerator = capabilities["accelerator"]
        print(
            "CUDA: "
            + (
                f"available ({', '.join(accelerator['cuda_devices'])})"
                if accelerator["cuda_available"]
                else "unavailable"
            )
        )
    return 0 if base_is_ready(capabilities) else 1


def command_inspect(args: argparse.Namespace) -> int:
    config = _configured(args)
    analysis = _analysis(args.source, config)
    if args.json:
        print(json.dumps(analysis.to_dict(), indent=2, sort_keys=True))
    else:
        _print_analysis(analysis)
    return 0


def command_plan(args: argparse.Namespace) -> int:
    config = _configured(args)
    analysis = _analysis(args.source, config)
    plan = recommend_conversion(analysis, config.workflow.profile).route
    if args.json:
        print(
            json.dumps(
                {"analysis": analysis.to_dict(), "route": plan.to_dict()},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_analysis(analysis)
        print(f"profile: {plan.profile.value}")
        print("initial: " + ", ".join(engine.value for engine in plan.initial_engines))
        print(
            "fallback: "
            + (
                ", ".join(engine.value for engine in plan.fallback_engines)
                if plan.fallback_engines
                else "none"
            )
        )
        for reason in plan.rationale:
            print(f"- {reason}")
    return 0


def command_recommend(args: argparse.Namespace) -> int:
    config = _configured(args)
    analysis = _analysis(args.source, config)
    capabilities = detect_capabilities()
    recommendation = recommend_conversion(
        analysis,
        config.workflow.profile,
        available_engines=available_engine_names(capabilities),
    )
    if args.json:
        print(
            json.dumps(
                {
                    "analysis": analysis.to_dict(),
                    "recommendation": recommendation.to_dict(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    _print_analysis(analysis)
    print(f"profile: {recommendation.profile.value}")
    print(f"confidence: {recommendation.confidence.value}")
    print(f"recommended: {recommendation.recommended_engine.value}")
    if recommendation.best_available_engine is None:
        print("best installed with complete coverage: none")
        if recommendation.best_partial_engine is not None:
            print(f"partial baseline: {recommendation.best_partial_engine.value}")
    else:
        print(
            "best installed with complete coverage: "
            f"{recommendation.best_available_engine.value}"
        )
    print(
        "compare: "
        + (
            ", ".join(engine.value for engine in recommendation.comparison_engines)
            if recommendation.comparison_engines
            else "none"
        )
    )
    print(
        "fallback: "
        + (
            ", ".join(engine.value for engine in recommendation.fallback_engines)
            if recommendation.fallback_engines
            else "none"
        )
    )
    for reason in recommendation.rationale:
        print(f"- {reason}")
    for reason in recommendation.review_reasons:
        print(f"- review: {reason}")
    return 0


def _explicit_engines(args: argparse.Namespace) -> tuple[EngineName, ...] | None:
    values = getattr(args, "engine", None)
    if not values:
        return None
    return tuple(dict.fromkeys(EngineName(value) for value in values))


def command_convert(args: argparse.Namespace) -> int:
    config = _configured(args)
    with Workflow(config) as workflow:
        result = workflow.convert(
            args.source,
            explicit_engines=_explicit_engines(args),
        )
    payload = {
        "status": result.status.value,
        "run_dir": str(result.run_dir),
        "canonical_engine": (
            result.canonical_engine.value if result.canonical_engine else None
        ),
        "manifest": str(result.manifest_path),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"status: {payload['status']}")
        print(f"run: {payload['run_dir']}")
        print(f"canonical: {payload['canonical_engine'] or 'none'}")
        print(f"manifest: {payload['manifest']}")
    return 1 if result.status is QualityStatus.FAIL else 0


def _batch_sources(input_dir: Path, pattern: str) -> tuple[Path, ...]:
    input_root = input_dir.expanduser().resolve()
    if not input_root.is_dir():
        raise ValueError(f"batch input is not a directory: {input_root}")
    sources: list[Path] = []
    for candidate in sorted(input_root.glob(pattern)):
        if candidate.is_symlink():
            raise ValueError(f"refusing symlinked batch input: {candidate}")
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        try:
            resolved.relative_to(input_root)
        except ValueError as error:
            raise ValueError(
                f"batch pattern escapes the input directory: {pattern!r}"
            ) from error
        sources.append(resolved)
    return tuple(sources)


def command_batch(args: argparse.Namespace) -> int:
    config = _configured(args)
    input_dir = args.input_dir.expanduser().resolve()
    sources = _batch_sources(input_dir, args.pattern)
    if not sources:
        print(f"no PDFs matched {args.pattern!r} in {input_dir}", file=sys.stderr)
        return 2
    failures = 0
    results = []
    with Workflow(config) as workflow:
        for source in sources:
            try:
                result = workflow.convert(
                    source,
                    explicit_engines=_explicit_engines(args),
                )
            except Exception as error:
                failures += 1
                item = {
                    "source": str(source),
                    "status": "failed",
                    "error": f"{type(error).__name__}: {error}",
                }
            else:
                failures += result.status is QualityStatus.FAIL
                item = {
                    "source": str(source),
                    "status": result.status.value,
                    "run_dir": str(result.run_dir),
                    "canonical_engine": (
                        result.canonical_engine.value
                        if result.canonical_engine
                        else None
                    ),
                }
            results.append(item)
            if not args.json:
                print(f"{source.name}: {item['status']}")
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    return 1 if failures else 0


def command_validate(args: argparse.Namespace) -> int:
    config = _configured(args)
    analysis = _analysis(args.source, config)
    report = validate_markdown(
        args.source.expanduser().resolve(),
        args.markdown.expanduser().resolve(),
        EngineName(args.engine),
        analysis,
        config.validation,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"status: {report.status.value}")
        print(f"score: {report.score:.1f}")
        print(f"tables: {report.table_block_count}")
        print(f"images: {report.image_reference_count}")
        if report.native_token_recall is not None:
            print(f"native-token recall: {report.native_token_recall:.1%}")
        for message in report.errors:
            print(f"error: {message}")
        for message in report.warnings:
            print(f"warning: {message}")
    return 1 if report.status is QualityStatus.FAIL else 0


def command_interactive(args: argparse.Namespace) -> int:
    config = _configured(args)
    if args.config is None and args.output_root is None:
        config = replace(
            config,
            workflow=replace(
                config.workflow,
                output_root=Path.home() / "Documents" / "Kilix PDF Conversions",
            ),
        )
    print(f"Kilix PDF Conversion {__version__}")
    print("Copyright (C) 2026 itsmygithubacct")
    print("AGPL-3.0-only; NO WARRANTY.")
    print("License and source: https://github.com/itsmygithubacct/kilix-pdf-conversion")
    print("Validated PDF-to-Markdown conversion. Press Enter at the path prompt to quit.")
    print(f"Output root: {config.workflow.output_root}")
    while True:
        try:
            value = input("\nPDF path: ").strip()
        except EOFError:
            print()
            return 0
        if not value:
            return 0
        source = Path(value.strip("'\"")).expanduser().resolve()
        try:
            analysis = _analysis(source, config)
            recommendation = recommend_conversion(
                analysis,
                config.workflow.profile,
                available_engines=available_engine_names(detect_capabilities()),
            )
        except (AnalysisError, OSError, ValueError, RuntimeError) as error:
            print(f"error: {error}", file=sys.stderr)
            continue
        _print_analysis(analysis)
        print(f"recommended: {recommendation.recommended_engine.value}")
        if recommendation.best_available_engine is None:
            print("installed complete-coverage engine: none")
        else:
            print(
                "installed complete-coverage engine: "
                f"{recommendation.best_available_engine.value}"
            )
        try:
            answer = input("Convert now? [Y/n]: ").strip().casefold()
        except EOFError:
            print()
            return 0
        if answer not in {"", "y", "yes"}:
            continue
        try:
            with Workflow(config) as workflow:
                result = workflow.convert(source)
        except (AnalysisError, OSError, ValueError, RuntimeError) as error:
            print(f"error: {error}", file=sys.stderr)
            continue
        print(f"status: {result.status.value}")
        print(f"run: {result.run_dir}")
        print(f"manifest: {result.manifest_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kilix-pdf",
        description="Validated multi-engine PDF-to-Markdown conversion",
    )
    subparsers = parser.add_subparsers(dest="command")

    interactive = subparsers.add_parser(
        "interactive",
        help="start a guided conversion session",
    )
    _add_config_argument(interactive)
    _add_profile_argument(interactive)
    interactive.add_argument("--output-root", type=Path)
    interactive.set_defaults(handler=command_interactive)

    doctor = subparsers.add_parser("doctor", help="inspect installed capabilities")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=command_doctor)

    inspect_parser = subparsers.add_parser("inspect", help="analyze a PDF")
    inspect_parser.add_argument("source", type=Path)
    inspect_parser.add_argument("--json", action="store_true")
    _add_config_argument(inspect_parser)
    inspect_parser.set_defaults(handler=command_inspect)

    recommend = subparsers.add_parser(
        "recommend",
        help="recommend the best conversion engine for a PDF",
    )
    recommend.add_argument("source", type=Path)
    recommend.add_argument("--json", action="store_true")
    _add_config_argument(recommend)
    _add_profile_argument(recommend)
    recommend.set_defaults(handler=command_recommend)

    plan = subparsers.add_parser("plan", help="show automatic engine routing")
    plan.add_argument("source", type=Path)
    plan.add_argument("--json", action="store_true")
    _add_config_argument(plan)
    _add_profile_argument(plan)
    plan.set_defaults(handler=command_plan)

    def add_conversion_options(command: argparse.ArgumentParser) -> None:
        _add_config_argument(command)
        _add_profile_argument(command)
        command.add_argument("--output-root", type=Path)
        command.add_argument(
            "--engine",
            action="append",
            choices=[engine.value for engine in EngineName],
            help="explicit engine; repeat to run multiple engines",
        )
        command.add_argument("--device", choices=["auto", "cpu", "cuda"])
        command.add_argument("--force", action="store_true")
        command.add_argument("--no-source", action="store_true")
        command.add_argument("--no-visual-pages", action="store_true")
        command.add_argument("--chart-extraction", action="store_true")
        command.add_argument("--json", action="store_true")

    convert = subparsers.add_parser("convert", help="convert one PDF")
    convert.add_argument("source", type=Path)
    add_conversion_options(convert)
    convert.set_defaults(handler=command_convert)

    batch = subparsers.add_parser("batch", help="convert a directory of PDFs")
    batch.add_argument("input_dir", type=Path)
    batch.add_argument("--pattern", default="*.pdf")
    add_conversion_options(batch)
    batch.set_defaults(handler=command_batch)

    validate = subparsers.add_parser("validate", help="audit one Markdown conversion")
    validate.add_argument("source", type=Path)
    validate.add_argument("markdown", type=Path)
    validate.add_argument(
        "--engine",
        default=EngineName.PYMUPDF.value,
        choices=[engine.value for engine in EngineName],
    )
    validate.add_argument("--json", action="store_true")
    _add_config_argument(validate)
    validate.set_defaults(handler=command_validate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        if sys.stdin.isatty() and sys.stdout.isatty():
            arguments = ["interactive"]
        else:
            parser.print_help(sys.stderr)
            return 2
    commands = {
        "interactive",
        "doctor",
        "inspect",
        "recommend",
        "plan",
        "convert",
        "batch",
        "validate",
    }
    if arguments[0] not in commands and not arguments[0].startswith("-"):
        # A desktop file association and ``kilix pdf report.pdf`` should both
        # be able to hand us a document directly. Keep the explicit subcommand
        # grammar for scripts while treating one leading path as ``convert``.
        arguments.insert(0, "convert")
    args = parser.parse_args(arguments)
    try:
        return int(args.handler(args))
    except (AnalysisError, OSError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
