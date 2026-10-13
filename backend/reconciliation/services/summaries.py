"""Shaping the import summary for the API response (assessment Section 5)."""

from dataclasses import asdict

from .importer import ImportSummary


def summary_to_dict(summary: ImportSummary) -> dict:
    return {
        "imported": summary.imported,
        "duplicates": summary.duplicates,
        "rows_read": summary.rows_read,
        "errors": [asdict(error) for error in summary.errors],
        "duplicate_rows": [asdict(row) for row in summary.duplicate_rows],
        "status_counts": summary.status_counts,
    }
