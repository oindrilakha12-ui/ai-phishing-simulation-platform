"""Synthetic outcome generator.

When a campaign goes ACTIVE we do not send anything. Instead every targeted (synthetic)
person gets an in-app preview, and we simulate plausible outcomes with a seeded RNG so
analytics have realistic-looking data. Those rows are flagged is_synthetic=True.

People linked to a real login (Target.user_id) only get the delivery, flagged is_synthetic=False;
what they then do in the inbox is recorded as real activity.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Campaign, Enrollment, SimulationEvent, Target
from app.services.training import auto_enroll_for_failure

BASE_CLICK = {"easy": 0.10, "medium": 0.20, "hard": 0.34}


def _susceptibility(target_id: str) -> float:
    """Stable per-person multiplier in [0.5, 1.6] derived from the id (some people click more)."""
    h = int(hashlib.sha256(target_id.encode()).hexdigest()[:8], 16)
    return 0.5 + (h % 1000) / 1000 * 1.1


def simulate_campaign(db: Session, campaign: Campaign, start: datetime, rng: random.Random | None = None,
                      improvement: float = 1.0) -> int:
    """Create synthetic events for every target in the campaign's departments. Returns #events.

    improvement < 1 lowers click probability (used by the seed to show training working over time).
    """
    rng = rng or random.Random(int(hashlib.sha256(campaign.id.encode()).hexdigest()[:8], 16))
    dept_ids = [d.id for d in campaign.departments]
    if not dept_ids or campaign.template is None:
        return 0
    targets = db.scalars(select(Target).where(Target.org_id == campaign.org_id, Target.deleted_at.is_(None),
                                              Target.department_id.in_(dept_ids))).all()
    trained = set(db.scalars(select(Enrollment.target_id).where(
        Enrollment.org_id == campaign.org_id, Enrollment.status == "completed")).all())
    difficulty = campaign.template.difficulty
    flag_cats = [f.get("category", "link") for f in campaign.template.red_flags] or ["link"]
    n = 0

    def ev(t: Target, kind: str, when: datetime, cat: str | None = None, synthetic: bool = True):
        nonlocal n
        db.add(SimulationEvent(org_id=campaign.org_id, campaign_id=campaign.id, target_id=t.id,
                               department_id=t.department_id, event_type=kind, occurred_at=when,
                               red_flag_category=cat, is_synthetic=synthetic))
        n += 1

    for t in targets:
        delivered = start + timedelta(minutes=rng.randint(0, 120))
        if t.user_id:
            # A real account decides for itself in the inbox: deliver only, never invent its outcome.
            ev(t, "delivered_preview", delivered, synthetic=False)
            continue
        ev(t, "delivered_preview", delivered)
        if rng.random() > 0.92:
            continue  # never opened
        previewed = delivered + timedelta(minutes=rng.randint(1, 600))
        ev(t, "previewed", previewed)
        p_click = BASE_CLICK.get(difficulty, 0.2) * _susceptibility(t.id) * improvement
        if t.id in trained:
            p_click *= 0.6
        clicked = rng.random() < p_click
        if clicked:
            cat = rng.choice(flag_cats)
            ev(t, "clicked_sim", previewed + timedelta(minutes=rng.randint(0, 30)), cat)
            enrollment = auto_enroll_for_failure(db, campaign.org_id, t.id, cat)
            if enrollment is not None and enrollment.status != "completed" and rng.random() < 0.55:
                done_at = previewed + timedelta(days=rng.randint(1, 10))
                enrollment.status, enrollment.completed_at = "completed", done_at
                enrollment.completed_lessons = [lsn.id for lsn in enrollment.module.lessons]
                ev(t, "completed_training", done_at)
        p_report = (0.12 if clicked else 0.38) * (1.3 if t.id in trained else 1.0) / max(improvement, 0.5)
        if rng.random() < min(p_report, 0.9):
            ev(t, "reported", previewed + timedelta(minutes=int(rng.expovariate(1 / 90)) + 2))
    db.flush()
    return n
