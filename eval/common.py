"""Shared helpers for the evaluation scripts (run with the backend virtualenv)."""
from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results"
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CHROMA_PATH", str(ROOT / "eval" / ".chroma-eval"))


def mode_label() -> str:
    from app.core.config import get_settings

    s = get_settings()
    return "DEMO (no LLM key; deterministic)" if s.demo_mode else f"LIVE ({s.ai_provider})"


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 3)


def binary_metrics(y_true: list[int], y_pred: list[int]) -> dict:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "n": len(y_true), "accuracy": round((tp + tn) / len(y_true), 4), "precision": round(precision, 4),
        "recall": round(recall, 4), "f1": round(f1, 4),
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }


def save(name: str, payload: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(UTC).isoformat(), "mode": mode_label(), **payload}
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


_ = statistics
