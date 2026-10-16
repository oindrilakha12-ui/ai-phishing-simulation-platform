"""SQLAlchemy ORM models.

Multi-tenancy rule: every business table uses TenantMixin (org_id + soft-delete column).
Tenant filtering is enforced centrally in app/db/repository.py — route handlers never
write raw `select(Model)` against tenant tables without going through it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Column, Float, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TenantMixin, UTCDateTime, utcnow

ROLES = ("super_admin", "org_admin", "manager", "learner")
CAMPAIGN_STATUSES = ("draft", "scheduled", "active", "completed")
EVENT_TYPES = ("delivered_preview", "previewed", "clicked_sim", "reported", "completed_training")
REPORT_STATUSES = ("new", "triaged", "confirmed_sim", "benign")
DIFFICULTIES = ("easy", "medium", "hard")


class Organization(IdMixin, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    # Org-level settings (leaderboard defaults, risk thresholds, etc.)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class User(IdMixin, TenantMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), index=True, nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    leaderboard_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RefreshToken(IdMixin, Base):
    """Issued refresh tokens. Rotation: each use revokes the old one and issues a new one in
    the same family. Re-using a revoked token revokes the whole family (theft detection)."""
    __tablename__ = "refresh_tokens"
    jti: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    family: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RevokedToken(IdMixin, Base):
    """Access-token revocation list (logout before expiry)."""
    __tablename__ = "revoked_tokens"
    jti: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Invite(IdMixin, TenantMixin, Base):
    """In-app invite codes (no email is ever sent)."""
    __tablename__ = "invites"
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(254))
    role: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Department(IdMixin, TenantMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_department_org_name"),)
    name: Mapped[str] = mapped_column(String(80))


class Target(IdMixin, TenantMixin, Base):
    """A SYNTHETIC person who receives in-app simulation previews. Learner users are linked."""
    __tablename__ = "targets"
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254))  # always @example.* (RFC 2606 reserved)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    department: Mapped[Department] = relationship(lazy="joined")


class Template(IdMixin, TenantMixin, Base):
    __tablename__ = "templates"
    name: Mapped[str] = mapped_column(String(120))
    brand: Mapped[str] = mapped_column(String(60))  # must be a FICTIONAL brand
    category: Mapped[str] = mapped_column(String(40), index=True)
    difficulty: Mapped[str] = mapped_column(String(10), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    sender_name: Mapped[str] = mapped_column(String(120))
    sender_email: Mapped[str] = mapped_column(String(254))
    body_html: Mapped[str] = mapped_column(Text)
    red_flags: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | ai_demo | ai


class TemplateVersion(IdMixin, TenantMixin, Base):
    __tablename__ = "template_versions"
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    changed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


campaign_departments = Table(
    "campaign_departments", Base.metadata,
    Column("campaign_id", ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("department_id", ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True),
)


class Campaign(IdMixin, TenantMixin, Base):
    __tablename__ = "campaigns"
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="draft", index=True)
    template_id: Mapped[str | None] = mapped_column(ForeignKey("templates.id"), index=True, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    template: Mapped[Template | None] = relationship(lazy="joined")
    departments: Mapped[list[Department]] = relationship(secondary=campaign_departments, lazy="selectin")


class SimulationEvent(IdMixin, TenantMixin, Base):
    """Synthetic outcome of an in-app preview. Nothing is ever emailed."""
    __tablename__ = "simulation_events"
    __table_args__ = (
        Index("ix_events_org_type_time", "org_id", "event_type", "occurred_at"),
        Index("ix_events_campaign_target", "campaign_id", "target_id"),
    )
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(24))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    red_flag_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class TrainingModule(IdMixin, TenantMixin, Base):
    __tablename__ = "training_modules"
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(40), index=True)
    est_minutes: Mapped[int] = mapped_column(Integer, default=5)
    lessons: Mapped[list[Lesson]] = relationship(order_by="Lesson.position", lazy="selectin",
                                                   cascade="all, delete-orphan")


class Lesson(IdMixin, TenantMixin, Base):
    __tablename__ = "lessons"
    module_id: Mapped[str] = mapped_column(ForeignKey("training_modules.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(160))
    content_md: Mapped[str] = mapped_column(Text)


class Quiz(IdMixin, TenantMixin, Base):
    __tablename__ = "quizzes"
    module_id: Mapped[str] = mapped_column(ForeignKey("training_modules.id", ondelete="CASCADE"),
                                           index=True, unique=True)
    pass_mark: Mapped[int] = mapped_column(Integer, default=70)  # percentage
    questions: Mapped[list[QuizQuestion]] = relationship(order_by="QuizQuestion.position",
                                                           lazy="selectin", cascade="all, delete-orphan")


class QuizQuestion(IdMixin, TenantMixin, Base):
    __tablename__ = "quiz_questions"
    quiz_id: Mapped[str] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSON)
    correct_index: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str] = mapped_column(Text, default="")


class QuizAttempt(IdMixin, TenantMixin, Base):
    __tablename__ = "quiz_attempts"
    quiz_id: Mapped[str] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    answers: Mapped[list[int]] = mapped_column(JSON)


class Enrollment(IdMixin, TenantMixin, Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("target_id", "module_id", name="uq_enrollment_target_module"),)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), index=True)
    module_id: Mapped[str] = mapped_column(ForeignKey("training_modules.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="enrolled", index=True)  # enrolled|in_progress|completed
    source: Mapped[str] = mapped_column(String(12), default="manual")  # manual | auto
    completed_lessons: Mapped[list[str]] = mapped_column(JSON, default=list)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    module: Mapped[TrainingModule] = relationship(lazy="joined")


class Certificate(IdMixin, TenantMixin, Base):
    __tablename__ = "certificates"
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), index=True)
    module_id: Mapped[str] = mapped_column(ForeignKey("training_modules.id", ondelete="CASCADE"), index=True)
    serial: Mapped[str] = mapped_column(String(40), unique=True)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ReportedEmail(IdMixin, TenantMixin, Base):
    __tablename__ = "reported_emails"
    reporter_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(300))
    raw_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    heuristic_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    matched_campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    triaged_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    triaged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RiskScore(IdMixin, TenantMixin, Base):
    """History of risk scores (one row per computation). scope = target | department."""
    __tablename__ = "risk_scores"
    __table_args__ = (Index("ix_risk_scope_subject_time", "org_id", "scope", "subject_id", "computed_at"),)
    scope: Mapped[str] = mapped_column(String(12))
    subject_id: Mapped[str] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float)
    factors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditLog(IdMixin, TenantMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_org_time", "org_id", "created_at"),)
    actor_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ApiKey(IdMixin, TenantMixin, Base):
    __tablename__ = "api_keys"
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(12), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(32))
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Webhook(IdMixin, TenantMixin, Base):
    """Outbound JSON webhooks to registered URLs only (HMAC-SHA256 signed). Never email."""
    __tablename__ = "webhooks"
    url: Mapped[str] = mapped_column(String(500))
    secret: Mapped[str] = mapped_column(String(80))
    events: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class WebhookDelivery(IdMixin, TenantMixin, Base):
    __tablename__ = "webhook_deliveries"
    webhook_id: Mapped[str] = mapped_column(ForeignKey("webhooks.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|success|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeDoc(IdMixin, TenantMixin, Base):
    __tablename__ = "knowledge_docs"
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(160))
    content_md: Mapped[str] = mapped_column(Text)


class Notification(IdMixin, TenantMixin, Base):
    __tablename__ = "notifications"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
