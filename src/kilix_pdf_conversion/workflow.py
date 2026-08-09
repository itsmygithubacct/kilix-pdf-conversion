from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from .analysis import analyze_pdf
from .artifacts import canonical_markdown, copy_source, render_visual_pages
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
from .reporting import write_run_report
from .routing import plan_route
from .util import (
    append_json_line,
    atomic_write_json,
    exclusive_lock,
    safe_slug,
    utc_now,
)

MODEL_ENGINES = {
    EngineName.GRANITE_HYBRID,
    EngineName.GRANITE_PURE,
    EngineName.MARKER,
}


class Workflow:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._engines: dict[EngineName, ConversionEngine] = {}

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

    def _configuration_sha256(self, plan) -> str:
        settings = asdict(self.config)
        settings["workflow"].pop("output_root")
        settings["workflow"].pop("force")
        payload = {
            "schema_version": 1,
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
    ) -> WorkflowResult | None:
        if self.config.workflow.force or not manifest_path.is_file():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("configuration_sha256") != configuration_sha256:
            raise RuntimeError(
                "completed run uses different conversion settings; use --force "
                "or choose another output root"
            )
        canonical = manifest.get("canonical_engine")
        status = QualityStatus(manifest.get("status", QualityStatus.FAIL.value))
        return WorkflowResult(
            run_dir=manifest_path.parent,
            canonical_engine=EngineName(canonical) if canonical else None,
            status=status,
            manifest_path=manifest_path,
        )

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
    ) -> EngineName | None:
        eligible = {
            engine: report
            for engine, report in reports.items()
            if report.status is not QualityStatus.FAIL
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
                eligible[engine].score + self._selection_bonus(engine, kind),
            ),
        )

    def convert(
        self,
        source: Path,
        *,
        explicit_engines: tuple[EngineName, ...] | None = None,
    ) -> WorkflowResult:
        source = source.expanduser().resolve()
        analysis = analyze_pdf(
            source,
            reliable_page_characters=self.config.analysis.reliable_page_characters,
            native_page_ratio=self.config.analysis.native_page_ratio,
            scan_page_ratio=self.config.analysis.scan_page_ratio,
            max_table_scan_pages=self.config.analysis.max_table_scan_pages,
        )
        plan = plan_route(analysis, self.config.workflow.profile)
        if explicit_engines:
            from .models import RoutePlan

            plan = RoutePlan(
                profile=plan.profile,
                initial_engines=explicit_engines,
                fallback_engines=(),
                rationale=plan.rationale + ("engine list was explicitly selected",),
            )

        run_id = f"{safe_slug(source.stem)}--{analysis.source_sha256[:12]}"
        output_root = self.config.workflow.output_root.expanduser().resolve()
        run_dir = output_root / run_id
        manifest_path = run_dir / "manifest.json"
        configuration_sha256 = self._configuration_sha256(plan)
        cached = self._cached_result(manifest_path, configuration_sha256)
        if cached is not None:
            return cached

        lock_path = output_root / ".locks" / f"{run_id}.lock"
        with exclusive_lock(lock_path):
            if self.config.workflow.force and run_dir.exists():
                if run_dir.is_symlink() or not run_dir.is_dir():
                    raise RuntimeError(f"refusing to replace invalid run path: {run_dir}")
                shutil.rmtree(run_dir)
            run_dir.mkdir(parents=True, exist_ok=True)
            events_path = run_dir / "events.jsonl"
            append_json_line(
                events_path,
                {
                    "event": "analysis_complete",
                    "timestamp": utc_now(),
                    "document_kind": analysis.document_kind.value,
                    "complexity": analysis.complexity.value,
                },
            )
            atomic_write_json(run_dir / "analysis.json", analysis.to_dict())
            if self.config.workflow.copy_source:
                copy_source(source, run_dir / "source.pdf")
            if self.config.workflow.render_visual_pages:
                rendered = render_visual_pages(
                    source,
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

            def run_engine(name: EngineName) -> None:
                append_json_line(
                    events_path,
                    {"event": "engine_started", "timestamp": utc_now(), "engine": name.value},
                )
                try:
                    result = self._engine(name).convert(
                        source, run_dir / "conversions" / name.value
                    )
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
                engine_results[name] = result
                append_json_line(
                    events_path,
                    {
                        "event": "engine_finished",
                        "timestamp": utc_now(),
                        **result.to_dict(),
                    },
                )
                if result.status == "success" and result.markdown_path:
                    quality = validate_markdown(
                        source,
                        Path(result.markdown_path),
                        name,
                        analysis,
                        self.config.validation,
                    )
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

            if (
                not explicit_engines
                and not any(
                    report.status is QualityStatus.PASS
                    for report in quality_reports.values()
                )
            ):
                for engine_name in plan.fallback_engines:
                    run_engine(engine_name)
                    report = quality_reports.get(engine_name)
                    if report and report.status is QualityStatus.PASS:
                        break

            canonical_engine = self._choose(quality_reports, analysis.document_kind)
            if canonical_engine is None:
                status = QualityStatus.FAIL
            else:
                status = quality_reports[canonical_engine].status
                selected_result = engine_results[canonical_engine]
                if selected_result.markdown_path:
                    canonical_markdown(
                        Path(selected_result.markdown_path),
                        canonical_engine,
                        run_dir / "canonical.md",
                    )

            write_run_report(
                run_dir / "report.md",
                analysis,
                plan,
                engine_results,
                quality_reports,
                canonical_engine,
                status,
            )
            manifest = {
                "schema_version": 1,
                "configuration_sha256": configuration_sha256,
                "created_at": utc_now(),
                "status": status.value,
                "source": analysis.to_dict(),
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
