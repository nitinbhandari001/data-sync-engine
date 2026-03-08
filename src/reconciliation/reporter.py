from __future__ import annotations
import json
from pathlib import Path
from ..models import ReconciliationReport


def format_report(report: ReconciliationReport) -> str:
    lines = [
        f"# Reconciliation Report",
        f"**Generated:** {report.generated_at}",
        f"**Systems:** {' <-> '.join(report.systems_compared)}",
        f"**Entity Type:** {report.entity_type}",
        "",
        f"## Summary",
        f"- Total checked: {report.total_records_checked}",
        f"- Matches: {report.matches}",
        f"- Mismatches: {len(report.mismatches)}",
        f"- Missing in target: {len(report.missing_in_target)}",
        f"- Missing in source: {len(report.missing_in_source)}",
        f"- **Accuracy: {report.accuracy_pct:.1f}%**",
    ]
    if report.mismatches:
        lines += ["", "## Field Mismatches"]
        for m in report.mismatches[:20]:  # cap for readability
            lines.append(f"- `{m.record_id}`.{m.field}: `{m.source_value}` vs `{m.target_value}`")
    return "\n".join(lines)


def save_report(report: ReconciliationReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{report.report_id}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path
