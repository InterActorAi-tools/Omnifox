"""A project's trends: how sentiment and its objectives move across uploads."""
from typing import Dict, List, Optional

from database import SessionLocal
from models import Project, ProjectSnapshot

SENTIMENTS = ("positive", "neutral", "negative")
STEADY_POINTS = 2  # a change smaller than this (in percentage points) is "steady"


def snapshot_stats(result: Dict) -> Dict:
    """The counts of one finished analysis that its project's trends need."""
    return {
        "total_comments": result.get("total_comments", 0),
        "sentiment_counts": {k.lower(): v for k, v in (result.get("sentiment_counts") or {}).items()},
        "objectives": [
            {k: o.get(k) for k in ("objective", "relevant_comments", "supports", "percent_met")}
            for o in result.get("objective_results") or []
        ],
    }


def record_snapshot(project: str, task_id: Optional[str], result: Dict) -> None:
    """Save the stats of a finished upload on its project (none for an unknown project)."""
    db = SessionLocal()
    try:
        row = db.query(Project).filter(Project.name == project).first()
        if row:
            db.add(ProjectSnapshot(project_id=row.id, task_id=task_id, stats=snapshot_stats(result)))
            db.commit()
    finally:
        db.close()


def _percent(part, whole) -> Optional[float]:
    return round(100 * part / whole, 1) if whole else None


def _trend(values: List[Optional[float]]) -> Optional[str]:
    """Rising, falling or steady from the first to the latest upload that has a value."""
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return None
    change = values[-1] - values[0]
    return "steady" if abs(change) < STEADY_POINTS else "rising" if change > 0 else "falling"


def project_trends(project: Project) -> Dict:
    snapshots = sorted((s for s in project.snapshots if s.stats), key=lambda s: (s.created_at, s.id))
    uploads = []
    for s in snapshots:
        counts, total = s.stats["sentiment_counts"], sum(s.stats["sentiment_counts"].values())
        met = {o["objective"]: o["percent_met"] for o in s.stats["objectives"]}
        uploads.append({
            "date": s.created_at,
            "total_comments": s.stats["total_comments"],
            **{f"{k}_percent": _percent(counts.get(k, 0), total) for k in SENTIMENTS},
            "objectives": [met.get(o) for o in project.objectives],
        })

    objectives = []
    for k, objective in enumerate(project.objectives):
        stats = [o for s in snapshots for o in s.stats["objectives"] if o["objective"] == objective]
        values = [u["objectives"][k] for u in uploads]
        objectives.append({
            "objective": objective,
            "percent_met": _percent(sum(o["supports"] for o in stats), sum(o["relevant_comments"] for o in stats)),
            "latest": next((v for v in reversed(values) if v is not None), None),
            "trend": _trend(values),
        })

    totals = {k: sum(s.stats["sentiment_counts"].get(k, 0) for s in snapshots) for k in SENTIMENTS}
    return {
        "uploads": uploads,
        "objectives": objectives,
        "overall": {
            "uploads": len(snapshots),
            "comments": sum(s.stats["total_comments"] for s in snapshots),
            **{f"{k}_percent": _percent(v, sum(totals.values())) for k, v in totals.items()},
            "sentiment_trend": _trend([u["positive_percent"] for u in uploads]),
        },
    }
