"""Load and update a finished analysis (its result file and stored summaries).

An analysis is identified by its result filename in the user's folder: the
same name the download link and History already use.
"""
import io
import os
from collections import Counter
from typing import Dict, Optional

import pandas as pd
from sqlalchemy.orm import Session

from config import UPLOAD_FOLDER
from models import ProjectSnapshot, Task, UrlCacheEntry
from services.trends import snapshot_stats
from utils.crypto import read_file
from utils.file_utils import create_excel_with_charts_enhanced
from utils.paths import safe_upload_path

SUMMARY_KEYS = {"overall": "overall_summary", "positive": "positive_context",
                "neutral": "neutral_context", "negative": "negative_context"}


class Analysis:
    def __init__(self, db: Session, email: str, filename: str):
        self.db, self.email, self.filename = db, email, filename
        self.path = safe_upload_path(UPLOAD_FOLDER, email, filename)
        data = read_file(self.path)
        # Chart data sits to the right of the comments after one empty header
        # cell (a blank original header is written as "Unnamed: n", never empty).
        header = pd.read_excel(io.BytesIO(data), sheet_name="Processed Data", header=None, nrows=1,
                               keep_default_na=False, na_values=[""]).iloc[0].tolist()
        width = next((i for i, h in enumerate(header) if pd.isna(h)), len(header))
        sheet = pd.read_excel(io.BytesIO(data), sheet_name="Processed Data", usecols=range(width),
                              keep_default_na=False, na_values=[""], dtype=object)
        # ...and its rows can run below the last comment: drop the empty ones.
        self.rows = sheet.dropna(how="all").reset_index(drop=True)
        self.task: Optional[Task] = next(
            (t for t in db.query(Task).filter(Task.client_id == email).all()
             if (t.result_data or {}).get("new_filename") == filename), None)
        result = (self.task.result_data if self.task else None) or {}
        self.summaries: Dict[str, str] = {k: result.get(v, "") for k, v in SUMMARY_KEYS.items()}
        meta = (self.task.metadata_json if self.task else None) or {}
        self.post_context: str = meta.get("post_context", "")
        self.project: str = meta.get("project", "")
        self.objective_results = result.get("objective_results") or []

    def records(self):
        """Rows as dicts for prompts: id, translation, sentiment, score, category."""
        return [
            {"id": i, "translation": str(r["Translation"]), "sentiment": str(r["Sentiment"]).lower(),
             "score": r["Sentiment Score"], "category": str(r["Category"])}
            for i, r in self.rows.iterrows()
        ]

    def counts(self):
        return dict(Counter(self.rows["Sentiment"].str.lower())), dict(Counter(self.rows["Category"]))

    def save(self) -> Dict:
        """Rewrite the result file and the stored results; return what the UI shows."""
        sentiment_counts, category_counts = self.counts()
        created = os.path.getmtime(self.path)
        if not create_excel_with_charts_enhanced(
            self.rows, self.path, sentiment_counts, category_counts,
            self.summaries["positive"], self.summaries["neutral"], self.summaries["negative"], self.summaries["overall"],
            self.objective_results,
        ):
            raise ValueError("Could not write the updated report")
        os.utime(self.path, (created, created))  # 30-day retention counts from creation, not the last edit

        update = {"sentiment_counts": sentiment_counts, "category_counts": category_counts}
        update.update({v: self.summaries[k] for k, v in SUMMARY_KEYS.items()})
        if self.task:
            self.task.result_data = {**(self.task.result_data or {}), **update}
            for snapshot in self.db.query(ProjectSnapshot).filter(ProjectSnapshot.task_id == self.task.task_id).all():
                snapshot.stats = snapshot_stats(self.task.result_data)
        for entry in self.db.query(UrlCacheEntry).filter(
            UrlCacheEntry.client_id == self.email,
            UrlCacheEntry.processed_filename == self.filename,
        ).all():
            entry.sentiment_data = {**(entry.sentiment_data or {}), **update}
        self.db.commit()
        return self.result()

    def result(self) -> Dict:
        """What the results view shows."""
        sentiment_counts, category_counts = self.counts()
        return {
            "filename": self.filename,
            "sentiment_counts": sentiment_counts,
            "category_counts": category_counts,
            "total_comments": len(self.rows),
            "skipped_rows": ((self.task.result_data if self.task else None) or {}).get("skipped_rows", 0),
            "objective_results": self.objective_results,
            **{v: self.summaries[k] for k, v in SUMMARY_KEYS.items()},
        }
