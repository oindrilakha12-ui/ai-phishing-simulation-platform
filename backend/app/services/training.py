"""Training/LMS logic: enrollment, lesson progress, quiz scoring, certificates."""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import Certificate, Enrollment, Quiz, QuizAttempt, SimulationEvent, Target, TrainingModule

# Which module category teaches which red-flag category (fallback: "basics").
FLAG_TO_MODULE_CATEGORY = {
    "link": "links", "sender": "sender", "reply_to": "sender", "branding": "sender",
    "urgency": "social_engineering", "request": "social_engineering", "too_good": "social_engineering",
    "attachment": "attachments", "qr_code": "qr_code", "greeting": "basics", "grammar": "basics",
}


def pick_module_for_flag(db: Session, org_id: str, flag_category: str | None) -> TrainingModule | None:
    wanted = FLAG_TO_MODULE_CATEGORY.get(flag_category or "", "basics")
    modules = db.scalars(select(TrainingModule).where(
        TrainingModule.org_id == org_id, TrainingModule.deleted_at.is_(None))).all()
    by_cat = {m.category: m for m in modules}
    return by_cat.get(wanted) or by_cat.get("basics") or (modules[0] if modules else None)


def enroll(db: Session, org_id: str, target_id: str, module_id: str, source: str = "manual") -> Enrollment:
    existing = db.scalar(select(Enrollment).where(Enrollment.org_id == org_id, Enrollment.target_id == target_id,
                                                  Enrollment.module_id == module_id))
    if existing:
        if existing.deleted_at:
            existing.deleted_at = None
        return existing
    e = Enrollment(org_id=org_id, target_id=target_id, module_id=module_id, source=source,
                   status="enrolled", completed_lessons=[])
    db.add(e)
    db.flush()
    return e


def auto_enroll_for_failure(db: Session, org_id: str, target_id: str, flag_category: str | None) -> Enrollment | None:
    """A learner who 'clicked' a simulated lure is automatically enrolled in the matching module."""
    module = pick_module_for_flag(db, org_id, flag_category)
    if module is None:
        return None
    return enroll(db, org_id, target_id, module.id, source="auto")


def complete_lesson(enrollment: Enrollment, lesson_id: str, module: TrainingModule) -> Enrollment:
    lesson_ids = {l.id for l in module.lessons}
    if lesson_id not in lesson_ids:
        raise ValueError("lesson does not belong to this module")
    done = set(enrollment.completed_lessons or [])
    done.add(lesson_id)
    enrollment.completed_lessons = sorted(done)  # reassign so SQLAlchemy sees the JSON change
    if enrollment.status == "enrolled":
        enrollment.status = "in_progress"
    return enrollment


def progress_pct(enrollment: Enrollment) -> int:
    total = len(enrollment.module.lessons) + 1  # +1 for the quiz
    done = len(enrollment.completed_lessons or []) + (1 if enrollment.status == "completed" else 0)
    return round(100 * done / total) if total else 0


def score_quiz(quiz: Quiz, answers: list[int]) -> tuple[int, bool, list[dict]]:
    """Return (score_pct, passed, per-question feedback)."""
    feedback, correct = [], 0
    for i, q in enumerate(quiz.questions):
        given = answers[i] if i < len(answers) else -1
        ok = given == q.correct_index
        correct += ok
        feedback.append({"question_id": q.id, "correct": ok, "correct_index": q.correct_index,
                         "explanation": q.explanation})
    total = len(quiz.questions) or 1
    score = round(100 * correct / total)
    return score, score >= quiz.pass_mark, feedback


def record_attempt(db: Session, org_id: str, target: Target, quiz: Quiz, answers: list[int],
                   enrollment: Enrollment) -> dict:
    score, passed, feedback = score_quiz(quiz, answers)
    db.add(QuizAttempt(org_id=org_id, quiz_id=quiz.id, target_id=target.id, score=score, passed=passed,
                       answers=answers))
    certificate = None
    if passed and enrollment.status != "completed":
        enrollment.status, enrollment.completed_at = "completed", utcnow()
        certificate = Certificate(org_id=org_id, target_id=target.id, module_id=quiz.module_id,
                                  serial=f"PG-{secrets.token_hex(5).upper()}")
        db.add(certificate)
        # Record completion as an event against the most recent campaign this target took part in.
        last = db.scalar(select(SimulationEvent).where(SimulationEvent.org_id == org_id,
                                                       SimulationEvent.target_id == target.id)
                         .order_by(SimulationEvent.occurred_at.desc()).limit(1))
        if last:
            db.add(SimulationEvent(org_id=org_id, campaign_id=last.campaign_id, target_id=target.id,
                                   department_id=target.department_id, event_type="completed_training",
                                   occurred_at=utcnow()))
    db.flush()
    return {"score": score, "passed": passed, "pass_mark": quiz.pass_mark, "feedback": feedback,
            "certificate_id": certificate.id if certificate else None}
