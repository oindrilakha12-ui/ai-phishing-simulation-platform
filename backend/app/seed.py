"""Idempotent demo seed.  Usage:  python -m app.seed            (skip if already seeded)
                                  python -m app.seed --reset    (wipe all rows, then seed)

Everything created here is SYNTHETIC: fictional organizations, Faker people with
@*.example addresses, fictional-brand lures and simulated outcomes.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import timedelta

from faker import Faker
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import heuristics
from app.ai.rag import load_documents
from app.core.cache import cache
from app.core.security import hash_password
from app.db.base import Base, utcnow
from app.db.models import (
    Campaign,
    Department,
    KnowledgeDoc,
    Lesson,
    Notification,
    Organization,
    Quiz,
    QuizQuestion,
    ReportedEmail,
    Target,
    Template,
    TemplateVersion,
    TrainingModule,
    User,
)
from app.db.session import SessionLocal
from app.seed_data import DEPARTMENTS, MODULES, TEMPLATES
from app.services import risk
from app.services.safety import validate_lure
from app.services.simulation import simulate_campaign

DEMO_PASSWORD = "PhishGuard!2026"  # development-only demo credential (documented in README)

ORGS = [
    {"name": "Globex Corporation", "slug": "globex", "domain": "globex.example.com", "people_per_dept": 9},
    {"name": "Initech", "slug": "initech", "domain": "initech.example.com", "people_per_dept": 7},
]


def wipe(db: Session) -> None:
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()


def seed_org(db: Session, spec: dict, rng: random.Random, fake: Faker, with_super_admin: bool) -> Organization:
    org = Organization(name=spec["name"], slug=spec["slug"],
                       settings={"leaderboard_individuals_enabled": True, "risk_high_threshold": 60})
    db.add(org)
    db.flush()
    oid, dom = org.id, spec["domain"]

    depts = [Department(org_id=oid, name=n) for n in DEPARTMENTS]
    db.add_all(depts)
    db.flush()

    pw = hash_password(DEMO_PASSWORD)
    users = []
    roles = [("org_admin", "admin", "Avery Admin"), ("manager", "manager", "Morgan Manager"),
             ("learner", "learner", "Lee Learner"), ("learner", "learner2", "Riley Learner")]
    if with_super_admin:
        roles.insert(0, ("super_admin", "superadmin", "Sam Superadmin"))
    for role, handle, name in roles:
        u = User(org_id=oid, email=f"{handle}@{dom}", full_name=name, password_hash=pw, role=role,
                 department_id=depts[1].id if role == "learner" else depts[5].id,
                 leaderboard_opt_in=handle == "learner")
        db.add(u)
        users.append(u)
    db.flush()

    # Synthetic people; learner accounts get their own linked target.
    for d in depts:
        for _ in range(spec["people_per_dept"]):
            name = fake.name()
            db.add(Target(org_id=oid, full_name=name, department_id=d.id, is_synthetic=True,
                          email=f"{name.lower().replace(' ', '.').replace(chr(39), '')}@people.example"))
    for u in users:
        if u.role == "learner":
            db.add(Target(org_id=oid, full_name=u.full_name, email=u.email, department_id=u.department_id,
                          user_id=u.id, is_synthetic=True))
    db.flush()

    templates = []
    for spec_t in TEMPLATES:
        problems = validate_lure(spec_t)
        assert not problems, f"seed template unsafe: {spec_t['name']}: {problems}"
        t = Template(org_id=oid, **spec_t, version=1, source="manual")
        db.add(t)
        db.flush()
        db.add(TemplateVersion(org_id=oid, template_id=t.id, version=1, snapshot=spec_t, changed_by=users[0].id))
        templates.append(t)

    for m in MODULES:
        mod = TrainingModule(org_id=oid, title=m["title"], description=m["description"], category=m["category"],
                             est_minutes=m["est_minutes"])
        db.add(mod)
        db.flush()
        for i, (title, content) in enumerate(m["lessons"]):
            db.add(Lesson(org_id=oid, module_id=mod.id, position=i + 1, title=title, content_md=content))
        quiz = Quiz(org_id=oid, module_id=mod.id, pass_mark=70)
        db.add(quiz)
        db.flush()
        for i, (prompt, options, correct, why) in enumerate(m["questions"]):
            db.add(QuizQuestion(org_id=oid, quiz_id=quiz.id, position=i + 1, prompt=prompt, options=options,
                                correct_index=correct, explanation=why))
    db.flush()

    for doc in load_documents():
        db.add(KnowledgeDoc(org_id=oid, slug=doc["slug"], title=doc["title"], content_md=doc["content_md"]))

    # Campaigns over the last 90 days: one every ~8 days, gradually improving outcomes.
    now = utcnow()
    manager = next(u for u in users if u.role == "manager")
    n_campaigns = 11
    for i in range(n_campaigns):
        start = now - timedelta(days=88 - i * 8)
        tmpl = templates[i % len(templates)]
        c = Campaign(org_id=oid, name=f"Q{(start.month - 1) // 3 + 1} {tmpl.name}", template_id=tmpl.id,
                     description=f"Synthetic {tmpl.difficulty} simulation", status="completed",
                     scheduled_at=start, started_at=start, completed_at=start + timedelta(days=7),
                     created_by=manager.id)
        c.departments = rng.sample(depts, k=rng.randint(3, 6))
        db.add(c)
        db.flush()
        simulate_campaign(db, c, start, rng=rng, improvement=1.25 - 0.05 * i)
    # Current-state campaigns for the lifecycle demo.
    active = Campaign(org_id=oid, name="Live: QR Wi-Fi awareness", template_id=templates[5].id, status="active",
                      description="Currently running (synthetic)", started_at=now - timedelta(days=2),
                      scheduled_at=now - timedelta(days=2), created_by=manager.id)
    active.departments = depts[:4]
    db.add(active)
    db.flush()
    simulate_campaign(db, active, now - timedelta(days=2), rng=rng, improvement=0.8)
    sched = Campaign(org_id=oid, name="Next: payroll BEC drill", template_id=templates[3].id, status="scheduled",
                     description="Scheduled synthetic drill", scheduled_at=now + timedelta(days=5),
                     created_by=manager.id)
    sched.departments = [depts[0], depts[2]]
    draft = Campaign(org_id=oid, name="Draft: attachment awareness", template_id=templates[1].id, status="draft",
                     description="Work in progress", created_by=manager.id)
    draft.departments = [depts[3]]
    db.add_all([sched, draft])
    db.flush()

    # Weekly risk history over 90 days.
    for weeks_ago in range(12, -1, -1):
        risk.snapshot(db, oid, as_of=now - timedelta(weeks=weeks_ago))

    # A few phish reports from learners.
    learners = [u for u in users if u.role == "learner"]
    samples = [
        (templates[2].subject, f"From: Umbrella IT <it-servicedesk@umbre11a-corp.example>\nReply-To: "
                               f"help@quota-desk.example\nSubject: {templates[2].subject}\n\nYour mailbox is at 98% "
                               "capacity. Verify your account immediately: http://umbre11a-corp.example/quota"),
        ("Lunch menu this week", "From: Canteen <canteen@globex.example.com>\nSubject: Lunch menu\n\nHi all, this "
                                 "week's menu is attached to the intranet page. Enjoy!"),
        ("Invoice overdue", "From: Billing <billing@fabrikam-pay.example>\nSubject: Invoice overdue\n\nDear customer, "
                            "payment failed. Please update banking details within 24 hours at http://bit.ly/x"),
    ]
    for i, (subj, raw) in enumerate(samples):
        analysis = heuristics.analyze(raw)
        r = ReportedEmail(org_id=oid, reporter_user_id=learners[i % len(learners)].id, subject=subj, raw_text=raw,
                          status=["confirmed_sim", "benign", "new"][i], heuristic_score=analysis["score"],
                          analysis=analysis, feedback=["Well spotted — this was a simulation.", "Safe, thanks!",
                                                       None][i],
                          triaged_by=manager.id if i < 2 else None, triaged_at=now if i < 2 else None)
        db.add(r)
    for u in users:
        db.add(Notification(org_id=oid, user_id=u.id, kind="welcome", title="Welcome to PhishGuard",
                            body="All data in this demo is synthetic. Explore safely!", link="/"))
    db.flush()
    return org


def run(reset: bool = False) -> None:
    db = SessionLocal()
    try:
        if reset:
            wipe(db)
        if db.scalar(select(Organization.id).where(Organization.slug == ORGS[0]["slug"])):
            print("Seed data already present - nothing to do (use --reset to rebuild).")
            return
        rng = random.Random(42)
        fake = Faker()
        Faker.seed(42)
        for i, spec in enumerate(ORGS):
            org = seed_org(db, spec, rng, fake, with_super_admin=i == 0)
            print(f"Seeded {org.name}")
        db.commit()
        cache.clear()
        print(f"Done. Log in as admin@globex.example.com / {DEMO_PASSWORD} (demo only).")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="delete all rows before seeding")
    run(parser.parse_args().reset)
    sys.exit(0)
