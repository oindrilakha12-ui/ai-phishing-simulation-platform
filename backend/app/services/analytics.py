"""Analytics aggregates over synthetic simulation events.

Definitions (also documented in docs/VIVA_GUIDE.md):
  recipients        = distinct (campaign, target) pairs with a delivered_preview event
  click_rate        = distinct clicked pairs / recipients
  report_rate       = distinct reported pairs / recipients
  report_to_click   = reported / clicked  (>1 means people report more than they click: good)
  completion_rate   = completed enrollments / all enrollments
  time_to_report    = minutes from 'previewed' to 'reported' for the same pair (median, p90)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, cast

from sqlalchemy import and_, distinct, func, select
from sqlalchemy.orm import Session

from app.core.cache import cache
from app.db.models import Campaign, Department, Enrollment, ReportedEmail, SimulationEvent, Target, Template, User


def _rate(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo), 1)


class Filters:
    def __init__(self, campaign_id: str | None = None, department_id: str | None = None,
                 date_from: datetime | None = None, date_to: datetime | None = None, real_only: bool = False):
        self.campaign_id, self.department_id = campaign_id, department_id
        self.date_from, self.date_to = date_from, date_to
        self.real_only = real_only  # only events from real logged-in users (is_synthetic=False)

    def key(self) -> str:
        return f"{self.campaign_id}|{self.department_id}|{self.date_from}|{self.date_to}|{self.real_only}"

    def apply(self, stmt, org_id: str):
        conds = [SimulationEvent.org_id == org_id, SimulationEvent.deleted_at.is_(None)]
        if self.real_only:
            conds.append(SimulationEvent.is_synthetic.is_(False))
        if self.campaign_id:
            conds.append(SimulationEvent.campaign_id == self.campaign_id)
        if self.department_id:
            conds.append(SimulationEvent.department_id == self.department_id)
        if self.date_from:
            conds.append(SimulationEvent.occurred_at >= self.date_from)
        if self.date_to:
            conds.append(SimulationEvent.occurred_at <= self.date_to)
        return stmt.where(and_(*conds))


def _pair_counts(db: Session, org_id: str, f: Filters, group_cols: list) -> dict[tuple, dict[str, int]]:
    """Count distinct (campaign,target) pairs per event type, grouped by `group_cols`."""
    pair = func.count(distinct(SimulationEvent.campaign_id + ":" + SimulationEvent.target_id))
    stmt = f.apply(select(*group_cols, SimulationEvent.event_type, pair), org_id)
    stmt = stmt.group_by(*group_cols, SimulationEvent.event_type)
    out: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in db.execute(stmt).all():
        *keys, etype, count = row
        out[tuple(keys)][etype] = count
    return out


def _kpis(counts: dict[str, int]) -> dict[str, Any]:
    recipients = counts.get("delivered_preview", 0)
    clicked, reported = counts.get("clicked_sim", 0), counts.get("reported", 0)
    return {
        "recipients": recipients,
        "previewed": counts.get("previewed", 0),
        "clicked": clicked,
        "reported": reported,
        "completed_training": counts.get("completed_training", 0),
        "click_rate": _rate(clicked, recipients),
        "report_rate": _rate(reported, recipients),
        "report_to_click_ratio": round(reported / clicked, 2) if clicked else None,
    }


def campaign_stats(db: Session, org_id: str, campaign_ids: list[str]) -> dict[str, dict[str, Any]]:
    """KPIs for many campaigns in ONE grouped query (avoids N+1 on the campaign list page)."""
    if not campaign_ids:
        return {}
    counts = _pair_counts(db, org_id, Filters(), [SimulationEvent.campaign_id])
    return {cid: _kpis(counts.get((cid,), {})) for cid in campaign_ids}


def time_to_report_minutes(db: Session, org_id: str, f: Filters) -> list[float]:
    stmt = f.apply(select(SimulationEvent.campaign_id, SimulationEvent.target_id, SimulationEvent.event_type,
                          func.min(SimulationEvent.occurred_at)), org_id)
    stmt = stmt.where(SimulationEvent.event_type.in_(("previewed", "reported"))).group_by(
        SimulationEvent.campaign_id, SimulationEvent.target_id, SimulationEvent.event_type)
    seen: dict[tuple[str, str], dict[str, datetime]] = defaultdict(dict)
    for cid, tid, etype, at in db.execute(stmt).all():
        seen[(cid, tid)][etype] = at
    out = []
    for times in seen.values():
        if "previewed" in times and "reported" in times:
            p, r = times["previewed"], times["reported"]
            if p.tzinfo is None and r.tzinfo is not None:
                r = r.replace(tzinfo=None)
            out.append(max(0.0, (r - p).total_seconds() / 60))
    return out


def overview(db: Session, org_id: str, f: Filters) -> dict[str, Any]:
    return cache.get_or_set(f"org:{org_id}:overview:{f.key()}", lambda: _overview(db, org_id, f))


def _overview(db: Session, org_id: str, f: Filters) -> dict[str, Any]:
    totals = _pair_counts(db, org_id, f, []).get((), {})
    kpis = _kpis(totals)

    enroll_q = select(Enrollment.status, func.count()).where(Enrollment.org_id == org_id,
                                                             Enrollment.deleted_at.is_(None))
    if f.real_only:
        enroll_q = enroll_q.join(Target, Target.id == Enrollment.target_id).where(Target.user_id.is_not(None))
    enroll_counts = dict(db.execute(enroll_q.group_by(Enrollment.status)).all())
    total_enrolled = sum(enroll_counts.values())
    kpis["completion_rate"] = _rate(enroll_counts.get("completed", 0), total_enrolled)
    kpis["enrollments"] = total_enrolled

    ttr = time_to_report_minutes(db, org_id, f)
    kpis["time_to_report_median_min"] = _percentile(ttr, 0.5)
    kpis["time_to_report_p90_min"] = _percentile(ttr, 0.9)

    # --- department heatmap: dept x month click rate
    month = func.strftime("%Y-%m", SimulationEvent.occurred_at) if db.bind.dialect.name == "sqlite" else \
        func.to_char(SimulationEvent.occurred_at, "YYYY-MM")
    by_dept_month = _pair_counts(db, org_id, f, [SimulationEvent.department_id, month])
    dept_names = dict(db.execute(select(Department.id, Department.name).where(
        Department.org_id == org_id, Department.deleted_at.is_(None))).all())
    heatmap = [
        {"department_id": d, "department": dept_names.get(d, "?"), "month": m,
         "click_rate": _rate(c.get("clicked_sim", 0), c.get("delivered_preview", 0)),
         "recipients": c.get("delivered_preview", 0)}
        for (d, m), c in sorted(by_dept_month.items(), key=lambda kv: (dept_names.get(kv[0][0], ""), kv[0][1]))
        if c.get("delivered_preview")
    ]

    # --- department summary
    by_dept = _pair_counts(db, org_id, f, [SimulationEvent.department_id])
    departments = sorted(
        ({"department_id": d, "department": dept_names.get(d, "?"), **_kpis(c)} for (d,), c in by_dept.items()),
        key=lambda r: r["click_rate"], reverse=True)

    # --- weekly trend
    week = func.strftime("%Y-W%W", SimulationEvent.occurred_at) if db.bind.dialect.name == "sqlite" else \
        func.to_char(SimulationEvent.occurred_at, 'IYYY-"W"IW')
    by_week = _pair_counts(db, org_id, f, [week])
    trend = [{"week": w, **{k: v for k, v in _kpis(c).items() if k in ("recipients", "click_rate", "report_rate")}}
             for (w,), c in sorted(by_week.items()) if c.get("delivered_preview")]

    # --- top failed red-flag categories
    cat_q = f.apply(select(SimulationEvent.red_flag_category, func.count()), org_id).where(
        SimulationEvent.event_type == "clicked_sim").group_by(SimulationEvent.red_flag_category)
    top_flags = sorted(({"category": c or "unknown", "count": n} for c, n in db.execute(cat_q).all()),
                       key=lambda r: r["count"], reverse=True)

    # --- cohort comparison by template difficulty
    diff_q = f.apply(select(Template.difficulty, SimulationEvent.event_type,
                            func.count(distinct(SimulationEvent.campaign_id + ":" + SimulationEvent.target_id)))
                     .join(Campaign, Campaign.id == SimulationEvent.campaign_id)
                     .join(Template, Template.id == Campaign.template_id), org_id)
    diff_counts: dict[str, dict[str, int]] = defaultdict(dict)
    for diff, etype, n in db.execute(diff_q.group_by(Template.difficulty, SimulationEvent.event_type)).all():
        diff_counts[diff][etype] = n
    order = {"easy": 0, "medium": 1, "hard": 2}
    cohorts = [{"cohort": d, **_kpis(c)} for d, c in sorted(diff_counts.items(), key=lambda kv: order.get(kv[0], 9))]

    return {"kpis": kpis, "heatmap": heatmap, "departments": departments, "trend": trend,
            "top_failed_flags": top_flags, "cohorts": cohorts, "synthetic_data": not f.real_only}


LIVE_EVENT_LABELS = {
    "previewed": "Opened a simulation",
    "clicked_sim": "Clicked the simulated link",
    "reported": "Reported the simulation as phishing",
    "completed_training": "Completed assigned training",
}


def live_activity(db: Session, org_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Most recent actions by REAL logged-in users (never synthetic), newest first. Not cached."""
    ev_rows = db.execute(
        select(SimulationEvent.occurred_at, SimulationEvent.event_type, Target.full_name, Campaign.name,
               Department.name)
        .join(Target, Target.id == SimulationEvent.target_id)
        .join(Campaign, Campaign.id == SimulationEvent.campaign_id)
        .join(Department, Department.id == SimulationEvent.department_id)
        .where(SimulationEvent.org_id == org_id, SimulationEvent.deleted_at.is_(None),
               SimulationEvent.is_synthetic.is_(False), SimulationEvent.event_type.in_(LIVE_EVENT_LABELS))
        .order_by(SimulationEvent.occurred_at.desc()).limit(limit)).all()
    items: list[dict[str, Any]] = [
             {"at": at, "kind": kind, "label": LIVE_EVENT_LABELS[kind], "actor": person, "detail": camp,
              "department": dept, "link": "/campaigns"} for at, kind, person, camp, dept in ev_rows]

    rep_rows = db.execute(
        select(ReportedEmail.created_at, ReportedEmail.subject, ReportedEmail.status, User.full_name)
        .join(User, User.id == ReportedEmail.reporter_user_id)
        .where(ReportedEmail.org_id == org_id, ReportedEmail.deleted_at.is_(None))
        .order_by(ReportedEmail.created_at.desc()).limit(limit)).all()
    items += [{"at": at, "kind": "report_submitted", "label": "Submitted a suspicious-email report",
               "actor": name, "detail": f"{subject} ({status.replace('_', ' ')})", "department": None,
               "link": "/reports/triage"} for at, subject, status, name in rep_rows]
    items.sort(key=lambda i: cast(datetime, i["at"]), reverse=True)
    return items[:limit]
