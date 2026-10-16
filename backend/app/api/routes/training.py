"""Training / LMS: modules, lessons, quizzes, enrollments, certificates, gamification."""
from __future__ import annotations

from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB, Admin, Learner, Manager, Paging, UserOnly, repo_for
from app.core.cache import cache
from app.core.errors import AppError, Forbidden, NotFound
from app.db.models import (
    Certificate,
    Department,
    Enrollment,
    Lesson,
    Organization,
    Quiz,
    QuizAttempt,
    QuizQuestion,
    ReportedEmail,
    Target,
    TrainingModule,
    User,
)
from app.schemas.common import Message
from app.services.audit import audit_p
from app.services.exports import certificate_pdf
from app.services.training import complete_lesson, enroll, progress_pct, record_attempt

router = APIRouter(prefix="/training", tags=["training"])


def _target_for(db, principal) -> Target:
    t = db.scalar(select(Target).where(Target.user_id == principal.id, Target.org_id == principal.org_id,
                                       Target.deleted_at.is_(None)))
    if not t:
        raise NotFound("No learner profile linked to this account")
    return t


def module_out(m: TrainingModule, quiz: Quiz | None, with_content: bool = True) -> dict:
    return {
        "id": m.id, "title": m.title, "description": m.description, "category": m.category,
        "est_minutes": m.est_minutes,
        "lessons": [{"id": l.id, "position": l.position, "title": l.title,
                     **({"content_md": l.content_md} if with_content else {})} for l in m.lessons],
        "quiz": None if not quiz else {
            "id": quiz.id, "pass_mark": quiz.pass_mark,
            # Correct answers are never sent to the browser before an attempt.
            "questions": [{"id": q.id, "prompt": q.prompt, "options": q.options} for q in quiz.questions],
        },
    }


@router.get("/modules")
def list_modules(principal: Learner, db: DB, p: Paging):
    repo = repo_for(principal, db)
    page = repo.paginate(repo.query(TrainingModule), TrainingModule, page=p.page, page_size=p.page_size,
                         sort=p.sort or "title", order=p.order if p.sort else "asc", search=p.q,
                         search_fields=("title", "description"), sortable=("title", "created_at", "category"))
    page["items"] = [module_out(m, None, with_content=False) for m in page["items"]]
    return page


@router.get("/modules/{module_id}")
def get_module(module_id: str, principal: Learner, db: DB):
    repo = repo_for(principal, db)
    m = repo.get(TrainingModule, module_id)
    quiz = db.scalar(repo.query(Quiz).where(Quiz.module_id == m.id))
    return module_out(m, quiz)


class LessonIn(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    content_md: str = Field(min_length=10, max_length=20_000)


class QuestionIn(BaseModel):
    prompt: str = Field(min_length=5, max_length=1000)
    options: list[str] = Field(min_length=2, max_length=6)
    correct_index: int = Field(ge=0, le=5)
    explanation: str = Field(default="", max_length=1000)


class ModuleIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=2000)
    category: str = Field(min_length=2, max_length=40)
    est_minutes: int = Field(default=5, ge=1, le=240)
    lessons: list[LessonIn] = Field(min_length=1, max_length=30)
    pass_mark: int = Field(default=70, ge=1, le=100)
    questions: list[QuestionIn] = Field(min_length=1, max_length=50)


@router.post("/modules", status_code=201)
def create_module(body: ModuleIn, request: Request, principal: Admin, db: DB):
    for q in body.questions:
        if q.correct_index >= len(q.options):
            raise AppError("correct_index out of range", code="validation_error", status_code=422)
    repo = repo_for(principal, db)
    m = repo.add(TrainingModule, title=body.title, description=body.description, category=body.category,
                 est_minutes=body.est_minutes)
    for i, l in enumerate(body.lessons):
        repo.add(Lesson, module_id=m.id, position=i + 1, title=l.title, content_md=l.content_md)
    quiz = repo.add(Quiz, module_id=m.id, pass_mark=body.pass_mark)
    for i, q in enumerate(body.questions):
        repo.add(QuizQuestion, quiz_id=quiz.id, position=i + 1, **q.model_dump())
    audit_p(db, principal, request, "training.module_created", "training_module", m.id, title=m.title)
    db.commit()
    db.refresh(m)
    db.refresh(quiz)
    return module_out(m, quiz)


@router.delete("/modules/{module_id}", response_model=Message)
def delete_module(module_id: str, request: Request, principal: Admin, db: DB):
    repo = repo_for(principal, db)
    m = repo.get(TrainingModule, module_id)
    repo.soft_delete(m)
    audit_p(db, principal, request, "training.module_deleted", "training_module", m.id)
    db.commit()
    return {"message": "Module deleted"}


# ---------------------------------------------------------------- enrollments

def enrollment_out(e: Enrollment) -> dict:
    return {"id": e.id, "target_id": e.target_id, "module_id": e.module_id, "module_title": e.module.title,
            "category": e.module.category, "status": e.status, "source": e.source,
            "completed_lessons": e.completed_lessons or [], "progress_pct": progress_pct(e),
            "completed_at": e.completed_at, "created_at": e.created_at}


@router.get("/my")
def my_training(principal: Learner, db: DB, _u: UserOnly):
    t = _target_for(db, principal)
    repo = repo_for(principal, db)
    items = db.scalars(repo.query(Enrollment).where(Enrollment.target_id == t.id)
                       .order_by(Enrollment.created_at.desc())).all()
    return [enrollment_out(e) for e in items]


class AssignIn(BaseModel):
    module_id: str = Field(max_length=32)
    target_ids: list[str] = Field(default_factory=list, max_length=500)
    department_id: str | None = Field(default=None, max_length=32)


@router.post("/enrollments", response_model=Message, status_code=201)
def assign(body: AssignIn, request: Request, principal: Manager, db: DB):
    repo = repo_for(principal, db)
    m = repo.get(TrainingModule, body.module_id)
    ids = list(body.target_ids)
    if body.department_id:
        repo.get(Department, body.department_id)
        ids += db.scalars(repo.query(Target).where(Target.department_id == body.department_id)
                          .with_only_columns(Target.id)).all()
    count = 0
    for tid in dict.fromkeys(ids):
        repo.get(Target, tid)  # cross-tenant ids -> 404
        enroll(db, principal.org_id, tid, m.id, source="manual")
        count += 1
    audit_p(db, principal, request, "training.assigned", "training_module", m.id, targets=count)
    db.commit()
    cache.invalidate_org(principal.org_id)
    return {"message": f"Assigned '{m.title}' to {count} people"}


@router.get("/enrollments")
def list_enrollments(principal: Manager, db: DB, p: Paging,
                     status: Annotated[str | None, Query(pattern="^(enrolled|in_progress|completed)$")] = None,
                     source: Annotated[str | None, Query(pattern="^(manual|auto)$")] = None):
    repo = repo_for(principal, db)
    stmt = repo.query(Enrollment)
    if status:
        stmt = stmt.where(Enrollment.status == status)
    if source:
        stmt = stmt.where(Enrollment.source == source)
    page = repo.paginate(stmt, Enrollment, page=p.page, page_size=p.page_size, sort=p.sort, order=p.order,
                         sortable=("created_at", "status", "completed_at"))
    names = dict(db.execute(select(Target.id, Target.full_name).where(
        Target.id.in_([e.target_id for e in page["items"]]))).all())
    page["items"] = [{**enrollment_out(e), "target_name": names.get(e.target_id)} for e in page["items"]]
    return page


def _my_enrollment(db, principal, enrollment_id: str) -> Enrollment:
    e = repo_for(principal, db).get(Enrollment, enrollment_id)
    if e.target_id != _target_for(db, principal).id:
        raise NotFound("Enrollment not found")
    return e


@router.post("/enrollments/{enrollment_id}/lessons/{lesson_id}/complete")
def complete_lesson_ep(enrollment_id: str, lesson_id: str, request: Request, principal: Learner, db: DB,
                       _u: UserOnly):
    e = _my_enrollment(db, principal, enrollment_id)
    try:
        complete_lesson(e, lesson_id, e.module)
    except ValueError as exc:
        raise AppError(str(exc), code="invalid_lesson")
    audit_p(db, principal, request, "training.lesson_completed", "enrollment", e.id, lesson_id=lesson_id)
    db.commit()
    return enrollment_out(e)


class AttemptIn(BaseModel):
    answers: list[int] = Field(min_length=1, max_length=50)


@router.post("/enrollments/{enrollment_id}/quiz")
def submit_quiz(enrollment_id: str, body: AttemptIn, request: Request, principal: Learner, db: DB,
                _u: UserOnly):
    e = _my_enrollment(db, principal, enrollment_id)
    quiz = db.scalar(repo_for(principal, db).query(Quiz).where(Quiz.module_id == e.module_id))
    if not quiz:
        raise NotFound("This module has no quiz")
    if len(e.completed_lessons or []) < len(e.module.lessons):
        raise AppError("Finish all lessons before taking the quiz", code="lessons_incomplete", status_code=409)
    result = record_attempt(db, principal.org_id, _target_for(db, principal), quiz, body.answers, e)
    audit_p(db, principal, request, "training.quiz_attempted", "enrollment", e.id, score=result["score"],
            passed=result["passed"])
    db.commit()
    cache.invalidate_org(principal.org_id)
    return result


# ---------------------------------------------------------------- certificates

@router.get("/certificates")
def my_certificates(principal: Learner, db: DB, _u: UserOnly):
    t = _target_for(db, principal)
    rows = db.execute(select(Certificate, TrainingModule.title).join(
        TrainingModule, TrainingModule.id == Certificate.module_id).where(
        Certificate.org_id == principal.org_id, Certificate.target_id == t.id)).all()
    return [{"id": c.id, "serial": c.serial, "module_title": title, "issued_at": c.issued_at} for c, title in rows]


@router.get("/certificates/{cert_id}/pdf")
def certificate_download(cert_id: str, principal: Learner, db: DB):
    repo = repo_for(principal, db)
    c = repo.get(Certificate, cert_id)
    target = repo.get(Target, c.target_id)
    if principal.role == "learner" and target.user_id != principal.id:
        raise Forbidden("Not your certificate")
    module = repo.get(TrainingModule, c.module_id)
    org = db.get(Organization, principal.org_id)
    pdf = certificate_pdf(target.full_name, module.title, c.serial, c.issued_at, org.name)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="certificate-{c.serial}.pdf"'})


# ---------------------------------------------------------------- gamification (privacy-aware)

def _points_by_target(db, org_id: str) -> dict[str, int]:
    """10 points per completed module, 2 per passed quiz, 5 per phish report."""
    pts: dict[str, int] = defaultdict(int)
    for tid, n in db.execute(select(Enrollment.target_id, func.count()).where(
            Enrollment.org_id == org_id, Enrollment.status == "completed").group_by(Enrollment.target_id)):
        pts[tid] += 10 * n
    for tid, n in db.execute(select(QuizAttempt.target_id, func.count()).where(
            QuizAttempt.org_id == org_id, QuizAttempt.passed.is_(True)).group_by(QuizAttempt.target_id)):
        pts[tid] += 2 * n
    for uid, n in db.execute(select(ReportedEmail.reporter_user_id, func.count()).where(
            ReportedEmail.org_id == org_id).group_by(ReportedEmail.reporter_user_id)):
        tid = db.scalar(select(Target.id).where(Target.user_id == uid))
        if tid:
            pts[tid] += 5 * n
    return pts


@router.get("/leaderboard")
def leaderboard(principal: Learner, db: DB):
    """Department-level by default. Individuals only appear if they opted in."""
    pts = _points_by_target(db, principal.org_id)
    targets = db.execute(select(Target.id, Target.full_name, Target.department_id, Target.user_id).where(
        Target.org_id == principal.org_id, Target.deleted_at.is_(None))).all()
    dept_names = dict(db.execute(select(Department.id, Department.name).where(
        Department.org_id == principal.org_id)).all())
    dept_pts: dict[str, list[int]] = defaultdict(list)
    for tid, _, did, _ in targets:
        dept_pts[did].append(pts.get(tid, 0))
    departments = sorted(({"department": dept_names.get(d, "?"), "avg_points": round(sum(v) / len(v), 1),
                           "people": len(v)} for d, v in dept_pts.items()), key=lambda r: -r["avg_points"])
    opted = set(db.scalars(select(User.id).where(User.org_id == principal.org_id,
                                                 User.leaderboard_opt_in.is_(True))).all())
    individuals = sorted(({"name": name, "points": pts.get(tid, 0)} for tid, name, _, uid in targets
                          if uid and uid in opted), key=lambda r: -r["points"])[:20]
    return {"departments": departments, "individuals": individuals,
            "privacy_note": "Individuals are listed only if they opted in from their profile."}


@router.get("/badges/me")
def my_badges(principal: Learner, db: DB, _u: UserOnly):
    t = _target_for(db, principal)
    completed = db.scalar(select(func.count()).select_from(Enrollment).where(
        Enrollment.target_id == t.id, Enrollment.status == "completed")) or 0
    perfect = db.scalar(select(func.count()).select_from(QuizAttempt).where(
        QuizAttempt.target_id == t.id, QuizAttempt.score == 100)) or 0
    reports = db.scalar(select(func.count()).select_from(ReportedEmail).where(
        ReportedEmail.reporter_user_id == principal.id)) or 0
    # Streak = consecutive distinct days (ending today or yesterday) with a quiz attempt.
    days = sorted({a.date() for a in db.scalars(select(QuizAttempt.created_at).where(
        QuizAttempt.target_id == t.id)).all()}, reverse=True)
    streak = 0
    if days:
        from datetime import date, timedelta
        cursor = date.today()
        if days[0] < cursor - timedelta(days=1):
            days = []
        elif days[0] == cursor - timedelta(days=1):
            cursor -= timedelta(days=1)
        for d in days:
            if d == cursor:
                streak += 1
                cursor -= timedelta(days=1)
            else:
                break
    badges = [
        {"id": "first_module", "label": "First module complete", "earned": completed >= 1},
        {"id": "three_modules", "label": "Three modules complete", "earned": completed >= 3},
        {"id": "perfect_quiz", "label": "Perfect quiz score", "earned": perfect >= 1},
        {"id": "reporter", "label": "Vigilant reporter (3+ reports)", "earned": reports >= 3},
    ]
    return {"points": _points_by_target(db, principal.org_id).get(t.id, 0), "streak_days": streak,
            "badges": badges}
