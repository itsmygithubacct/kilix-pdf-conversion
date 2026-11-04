from __future__ import annotations

import json
from contextlib import ExitStack
from dataclasses import asdict, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from .analysis import analyze_pdf
from .artifacts import canonical_markdown, copy_source, render_visual_pages
from .capabilities import available_engine_names, detect_capabilities
from .config import AppConfig
from .engines import ConversionEngine, EngineUnavailable, create_engine
from .models import (
    DocumentKind,
    EngineName,
    EngineResult,
    QualityReport,
    QualityStatus,
    WorkflowResult,
)
from .quality import validate_markdown
from .recommendation import recommend_conversion
from .reporting import write_run_report
from .text_evidence import TEXT_EVIDENCE_POLICY_VERSION
from .util import (
    append_json_line,
    atomic_write_json,
    exclusive_lock,
    safe_slug,
    sha256_file,
    utc_now,
)

MODEL_ENGINES = {
    EngineName.GRANITE_HYBRID,
    EngineName.GRANITE_PURE,
    EngineName.MARKER,
}
MANIFEST_SCHEMA_VERSION = 4


class Workflow:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._engines: dict[EngineName, ConversionEngine] = {}
        self._available_engines: frozenset[EngineName] | None = None

    def _installed_engines(self) -> frozenset[EngineName]:
        if self._available_engines is None:
            self._available_engines = available_engine_names(
                detect_capabilities(model_directory=self.config.granite.model_directory)
            )
        return self._available_engines

    def _engine(self, name: EngineName) -> ConversionEngine:
        if name in MODEL_ENGINES:
            for loaded_name in list(self._engines):
                if loaded_name in MODEL_ENGINES and loaded_name is not name:
                    self._engines.pop(loaded_name).close()
        if name not in self._engines:
            self._engines[name] = create_engine(name, self.config)
        return self._engines[name]

    def close(self) -> None:
        for engine in self._engines.values():
            engine.close()
        self._engines.clear()

    def __enter__(self) -> Workflow:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _configuration_sha256(self, plan, policy_version: int) -> str:
        settings = asdict(self.config)
        settings["workflow"].pop("output_root")
        settings["workflow"].pop("force")
        payload = {
            "schema_version": 1,
            "recommendation_policy_version": policy_version,
            "text_evidence_policy_version": TEXT_EVIDENCE_POLICY_VERSION,
            "settings": settings,
            "route": {
                "profile": plan.profile.value,
                "initial_engines": [engine.value for engine in plan.initial_engines],
                "fallback_engines": [engine.value for engine in plan.fallback_engines],
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()

    def _cached_result(
        self,
        manifest_path: Path,
        configuration_sha256: str,
        source_sha256: str,
    ) -> WorkflowResult | None:
        if self.config.workflow.force:
            return None
        if not manifest_path.exists() and not manifest_path.is_symlink():
            return None
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise RuntimeError(
                "completed run has an unsafe manifest; use --force to archive it"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeError(
                "completed run has an unreadable manifest; use --force to archive it"
            ) from error
        if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise RuntimeError(
                "completed run has an unsupported manifest; use --force to archive it"
            )
        if manifest.get("configuration_sha256") != configuration_sha256:
            raise RuntimeError(
                "completed run uses different conversion settings; use --force "
                "or choose another output root"
            )
        source = manifest.get("source")
        if not isinstance(source, dict) or source.get("source_sha256") != source_sha256:
            raise RuntimeError(
                "completed run does not match the source PDF; use --force to archive it"
            )
        try:
            status = QualityStatus(manifest["status"])
            canonical_value = manifest.get("canonical_engine")
            canonical = EngineName(canonical_value) if canonical_value else None
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(
                "completed run has invalid result metadata; use --force to archive it"
            ) from error
        canonical_path = manifest.get("canonical_path")
        canonical_sha256 = manifest.get("canonical_sha256")
        if canonical is None:
            if (
                status is not QualityStatus.FAIL
                or canonical_path is not None
                or canonical_sha256 is not None
            ):
                raise RuntimeError(
                    "completed run has inconsistent canonical metadata; use --force"
                )
        else:
            candidate = manifest_path.parent / "canonical.md"
            if (
                status is QualityStatus.FAIL
                or canonical_path != "canonical.md"
                or not isinstance(canonical_sha256, str)
                or len(canonical_sha256) != 64
                or candidate.is_symlink()
                or not candidate.is_file()
                or sha256_file(candidate) != canonical_sha256
            ):
                raise RuntimeError(
                    "completed run canonical output is missing or corrupt; use --force"
                )
        return WorkflowResult(
            run_dir=manifest_path.parent,
            canonical_engine=canonical,
            status=status,
            manifest_path=manifest_path,
        )

    @staticmethod
    def _archive_run(run_dir: Path, output_root: Path) -> Path:
        if run_dir.is_symlink() or not run_dir.is_dir():
            raise RuntimeError(f"refusing to archive invalid run path: {run_dir}")
        history_dir = output_root / ".history"
        history_dir.mkdir(parents=True, exist_ok=True)
        if history_dir.is_symlink() or not history_dir.is_dir():
            raise RuntimeError(f"refusing to use invalid history path: {history_dir}")
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        archived = history_dir / f"{run_dir.name}--{timestamp}"
        if archived.exists() or archived.is_symlink():
            raise RuntimeError(f"refusing to overwrite archived run: {archived}")
        run_dir.replace(archived)
        return archived

    @staticmethod
    def _validated_engine_paths(
        result: EngineResult,
        output_dir: Path,
    ) -> Path:
        if not result.markdown_path:
            raise RuntimeError("engine reported success without a Markdown path")
        root = output_dir.resolve()
        markdown_path = Path(result.markdown_path)
        if not markdown_path.is_absolute() or markdown_path.is_symlink():
            raise RuntimeError("engine returned an unsafe Markdown path")
        resolved_markdown = markdown_path.resolve()
        try:
            resolved_markdown.relative_to(root)
        except ValueError as error:
            raise RuntimeError("engine Markdown path escapes its output directory") from error
        if not resolved_markdown.is_file():
            raise RuntimeError("engine Markdown output does not exist")
        if result.assets_path:
            assets_path = Path(result.assets_path)
            if not assets_path.is_absolute() or assets_path.is_symlink():
                raise RuntimeError("engine returned an unsafe assets path")
            resolved_assets = assets_path.resolve()
            try:
                resolved_assets.relative_to(root)
            except ValueError as error:
                raise RuntimeError("engine assets path escapes its output directory") from error
            if not resolved_assets.is_dir():
                raise RuntimeError("engine assets output does not exist")
        return resolved_markdown

    @staticmethod
    def _selection_bonus(engine: EngineName, kind: DocumentKind) -> float:
        if kind is DocumentKind.NATIVE:
            return {
                EngineName.PYMUPDF: 4.0,
                EngineName.GRANITE_HYBRID: 2.0,
            }.get(engine, 0.0)
        if kind is DocumentKind.SCAN:
            return {
                EngineName.GRANITE_PURE: 4.0,
                EngineName.MARKER: 3.0,
            }.get(engine, 0.0)
        return {
            EngineName.GRANITE_PURE: 3.0,
            EngineName.PYMUPDF: 1.0,
            EngineName.MARKER: 1.0,
        }.get(engine, 0.0)

    def _choose(
        self,
        reports: dict[EngineName, QualityReport],
        kind: DocumentKind,
        required_coverage_engines: tuple[EngineName, ...] = (),
    ) -> EngineName | None:
        eligible = {
            engine: report
            for engine, report in reports.items()
            if report.status is not QualityStatus.FAIL
        }
        if not eligible:
            return None
        if required_coverage_engines:
            eligible = {
                engine: report
                for engine, report in eligible.items()
                if engine in required_coverage_engines
            }
            if not eligible:
                return None
        status_rank = {
            QualityStatus.FAIL: 0,
            QualityStatus.WARN: 1,
            QualityStatus.PASS: 2,
        }
        return max(
            eligible,
            key=lambda engine: (
                status_rank[eligible[engine].status],
                eligible[engine].score + (
                    self._selection_bonus(engine, kind)
                    if eligible[engine].source_text_evidence.get("trust") == "trusted"
                    or kind is not DocumentKind.NATIVE else 0.0
                ),
            ),
        )

    def convert(
        self,
        source: Path,
        *,
        explicit_engines: tuple[EngineName, ...] | None = None,
    ) -> WorkflowResult:
        if self.config.granite.chart_extraction:
            # A native route or cached native result cannot satisfy this request.
            # If the asset gate later opens, chart-capable selection must also be
            # implemented before a workflow can safely accept the request.
            from .engines.granite_engine import _require_chart_assets

            _require_chart_assets()
            raise EngineUnavailable("Chart-enabled workflow routing is not yet available")
        source = source.expanduser().resolve()
        analysis = analyze_pdf(
            source,
            reliable_page_characters=self.config.analysis.reliable_page_characters,
            native_page_ratio=self.config.analysis.native_page_ratio,
            scan_page_ratio=self.config.analysis.scan_page_ratio,
            max_table_scan_pages=self.config.analysis.max_table_scan_pages,
        )
        recommendation = recommend_conversion(
            analysis,
            self.config.workflow.profile,
            available_engines=self._installed_engines(),
        )
        plan = recommendation.route
        execution_recommended_engine = recommendation.recommended_engine
        if explicit_engines:
            from .models import RoutePlan

            plan = RoutePlan(
                profile=plan.profile,
                initial_engines=explicit_engines,
                fallback_engines=(),
                rationale=plan.rationale + ("engine list was explicitly selected",),
            )
            execution_recommended_engine = explicit_engines[0]

        run_id = f"{safe_slug(source.stem)}--{analysis.source_sha256[:12]}"
        output_root = self.config.workflow.output_root.expanduser().resolve()
        run_dir = output_root / run_id
        manifest_path = run_dir / "manifest.json"
        configuration_sha256 = self._configuration_sha256(
            plan,
            recommendation.policy_version,
        )

        lock_path = output_root / ".locks" / f"{run_id}.lock"
        with exclusive_lock(lock_path), ExitStack() as cleanup:
            cached = self._cached_result(
                manifest_path,
                configuration_sha256,
                analysis.source_sha256,
            )
            if cached is not None:
                return cached

            archived_run = None
            if run_dir.exists() or run_dir.is_symlink():
                archived_run = self._archive_run(run_dir, output_root)
            run_dir.mkdir(parents=True, exist_ok=True)
            events_path = run_dir / "events.jsonl"
            if archived_run is not None:
                append_json_line(
                    events_path,
                    {
                        "event": "previous_run_archived",
                        "timestamp": utc_now(),
                        "archive": str(archived_run),
                    },
                )
            append_json_line(
                events_path,
                {
                    "event": "analysis_complete",
                    "timestamp": utc_now(),
                    "document_kind": analysis.document_kind.value,
                    "complexity": analysis.complexity.value,
                },
            )
            append_json_line(
                events_path,
                {
                    "event": "recommendation_complete",
                    "timestamp": utc_now(),
                    "recommended_engine": recommendation.recommended_engine.value,
                    "confidence": recommendation.confidence.value,
                    "overridden": bool(explicit_engines),
                },
            )
            atomic_write_json(run_dir / "analysis.json", analysis.to_dict())
            if self.config.workflow.copy_source:
                conversion_source = run_dir / "source.pdf"
            else:
                temporary_directory = cleanup.enter_context(
                    TemporaryDirectory(prefix="kilix-pdf-input-")
                )
                conversion_source = Path(temporary_directory) / "source.pdf"
            copy_source(
                source,
                conversion_source,
                expected_sha256=analysis.source_sha256,
            )
            if self.config.workflow.render_visual_pages:
                rendered = render_visual_pages(
                    conversion_source,
                    analysis,
                    run_dir / "visual",
                )
                append_json_line(
                    events_path,
                    {
                        "event": "visual_pages_rendered",
                        "timestamp": utc_now(),
                        "count": len(rendered),
                    },
                )

            engine_results: dict[EngineName, EngineResult] = {}
            quality_reports: dict[EngineName, QualityReport] = {}
            validated_markdown_paths: dict[EngineName, Path] = {}

            def run_engine(name: EngineName) -> None:
                append_json_line(
                    events_path,
                    {"event": "engine_started", "timestamp": utc_now(), "engine": name.value},
                )
                output_dir = run_dir / "conversions" / name.value
                try:
                    result = self._engine(name).convert(conversion_source, output_dir)
                except EngineUnavailable as error:
                    result = EngineResult(
                        engine=name,
                        status="unavailable",
                        markdown_path=None,
                        assets_path=None,
                        elapsed_seconds=0.0,
                        output_bytes=0,
                        error=str(error),
                    )
                except Exception as error:
                    result = EngineResult(
                        engine=name,
                        status="failed",
                        markdown_path=None,
                        assets_path=None,
                        elapsed_seconds=0.0,
                        output_bytes=0,
                        error=f"{type(error).__name__}: {error}",
                    )

                quality = None
                if result.status == "success":
                    try:
                        markdown_path = self._validated_engine_paths(result, output_dir)
                        quality = validate_markdown(
                            conversion_source,
                            markdown_path,
                            name,
                            analysis,
                            self.config.validation,
                        )
                    except Exception as error:
                        result = replace(
                            result,
                            status="failed",
                            markdown_path=None,
                            assets_path=None,
                            error=f"validation failed: {type(error).__name__}: {error}",
                        )
                    else:
                        validated_markdown_paths[name] = markdown_path
                engine_results[name] = result
                append_json_line(
                    events_path,
                    {
                        "event": "engine_finished",
                        "timestamp": utc_now(),
                        **result.to_dict(),
                    },
                )
                if quality is not None:
                    quality_reports[name] = quality
                    atomic_write_json(
                        run_dir / "quality" / f"{name.value}.json",
                        quality.to_dict(),
                    )
                    append_json_line(
                        events_path,
                        {
                            "event": "quality_complete",
                            "timestamp": utc_now(),
                            "engine": name.value,
                            "status": quality.status.value,
                            "score": quality.score,
                        },
                    )

            for engine_name in plan.initial_engines:
                run_engine(engine_name)

            usable_initial = any(
                quality_reports.get(engine) is not None
                and quality_reports[engine].status is not QualityStatus.FAIL
                and (quality_reports[engine].status is QualityStatus.PASS
                     or not quality_reports[engine].fallback_recommended)
                for engine in recommendation.complete_coverage_engines
            )
            if not explicit_engines and not usable_initial:
                for engine_name in plan.fallback_engines:
                    run_engine(engine_name)
                    report = quality_reports.get(engine_name)
                    if report and report.status is not QualityStatus.FAIL and (
                        report.status is QualityStatus.PASS or not report.fallback_recommended
                    ):
                        break

            canonical_engine = self._choose(
                quality_reports,
                analysis.document_kind,
                ()
                if explicit_engines
                else recommendation.complete_coverage_engines,
            )
            if canonical_engine is None:
                status = QualityStatus.FAIL
            else:
                status = quality_reports[canonical_engine].status
                canonical_markdown(
                    validated_markdown_paths[canonical_engine],
                    canonical_engine,
                    run_dir / "canonical.md",
                )

            if sha256_file(conversion_source) != analysis.source_sha256:
                raise RuntimeError("staged source PDF changed during conversion")

            write_run_report(
                run_dir / "report.md",
                analysis,
                plan,
                execution_recommended_engine,
                ()
                if explicit_engines
                else recommendation.complete_coverage_engines,
                engine_results,
                quality_reports,
                canonical_engine,
                status,
            )
            manifest = {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "configuration_sha256": configuration_sha256,
                "created_at": utc_now(),
                "status": status.value,
                "validation_scope": "heuristic_checks",
                "content_accuracy": "unverified",
                "source": analysis.to_dict(),
                "recommendation": recommendation.to_dict(),
                "recommendation_overridden": bool(explicit_engines),
                "route": plan.to_dict(),
                "engine_results": {
                    name.value: result.to_dict()
                    for name, result in engine_results.items()
                },
                "quality": {
                    name.value: report.to_dict()
                    for name, report in quality_reports.items()
                },
                "canonical_engine": (
                    canonical_engine.value if canonical_engine is not None else None
                ),
                "canonical_path": "canonical.md" if canonical_engine else None,
                "canonical_sha256": (
                    sha256_file(run_dir / "canonical.md") if canonical_engine else None
                ),
            }
            atomic_write_json(manifest_path, manifest)
            append_json_line(
                events_path,
                {
                    "event": "run_complete",
                    "timestamp": utc_now(),
                    "status": status.value,
                    "canonical_engine": (
                        canonical_engine.value if canonical_engine else None
                    ),
                },
            )
            return WorkflowResult(
                run_dir=run_dir,
                canonical_engine=canonical_engine,
                status=status,
                manifest_path=manifest_path,
            )
