from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from .analysis import AnalysisError, analyze_pdf
from .capabilities import base_is_ready, detect_capabilities
from .config import AppConfig, load_config, with_overrides
from .models import EngineName, Profile, QualityStatus
from .quality import validate_markdown
from .routing import plan_route
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
    plan = plan_route(analysis, config.workflow.profile)
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


def command_batch(args: argparse.Namespace) -> int:
    config = _configured(args)
    input_dir = args.input_dir.expanduser().resolve()
    sources = sorted(path for path in input_dir.glob(args.pattern) if path.is_file())
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kilix-pdf",
        description="Validated multi-engine PDF-to-Markdown conversion",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="inspect installed capabilities")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=command_doctor)

    inspect_parser = subparsers.add_parser("inspect", help="analyze a PDF")
    inspect_parser.add_argument("source", type=Path)
    inspect_parser.add_argument("--json", action="store_true")
    _add_config_argument(inspect_parser)
    inspect_parser.set_defaults(handler=command_inspect)

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
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (AnalysisError, FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
