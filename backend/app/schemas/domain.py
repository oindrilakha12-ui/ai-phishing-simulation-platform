"""Request/response schemas for the core domain (departments, targets, templates, campaigns)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORM

Difficulty = Literal["easy", "medium", "hard"]
CampaignStatus = Literal["draft", "scheduled", "active", "completed"]

RED_FLAG_CATEGORIES = (
    "sender", "urgency", "link", "attachment", "request", "greeting", "grammar", "branding", "reply_to",
    "too_good", "qr_code",
)


class DepartmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class DepartmentOut(ORM):
    id: str
    name: str
    created_at: datetime


class TargetOut(ORM):
    id: str
    full_name: str
    email: str
    department_id: str
    department_name: str | None = None
    user_id: str | None
    is_synthetic: bool
    created_at: datetime


class RedFlag(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    category: str = Field(max_length=40)
    description: str = Field(min_length=3, max_length=400)
    cue: str = Field(default="", max_length=200, description="Exact text in the body to highlight")

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        if v not in RED_FLAG_CATEGORIES:
            raise ValueError(f"category must be one of {RED_FLAG_CATEGORIES}")
        return v


class TemplateIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    brand: str = Field(min_length=2, max_length=60)
    category: str = Field(min_length=2, max_length=40)
    difficulty: Difficulty
    subject: str = Field(min_length=3, max_length=200)
    sender_name: str = Field(min_length=2, max_length=120)
    sender_email: str = Field(min_length=5, max_length=254)
    body_html: str = Field(min_length=10, max_length=20_000)
    red_flags: list[RedFlag] = Field(min_length=1, max_length=20)


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    brand: str | None = Field(default=None, min_length=2, max_length=60)
    category: str | None = Field(default=None, min_length=2, max_length=40)
    difficulty: Difficulty | None = None
    subject: str | None = Field(default=None, min_length=3, max_length=200)
    sender_name: str | None = Field(default=None, min_length=2, max_length=120)
    sender_email: str | None = Field(default=None, min_length=5, max_length=254)
    body_html: str | None = Field(default=None, min_length=10, max_length=20_000)
    red_flags: list[RedFlag] | None = Field(default=None, min_length=1, max_length=20)


class TemplateOut(ORM):
    id: str
    name: str
    brand: str
    category: str
    difficulty: str
    subject: str
    sender_name: str
    sender_email: str
    body_html: str
    red_flags: list[dict]
    version: int
    source: str
    created_at: datetime
    updated_at: datetime


class TemplateVersionOut(ORM):
    id: str
    version: int
    snapshot: dict
    changed_by: str | None
    created_at: datetime


class PreviewOut(BaseModel):
    template_id: str
    document: str  # full HTML for <iframe sandbox srcdoc>
    red_flags: list[dict]
    links: list[dict]
    landing_page: str
    watermark: str
    csp: str


class CampaignIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=2000)
    template_id: str | None = Field(default=None, max_length=32)
    department_ids: list[str] = Field(default_factory=list, max_length=100)
    scheduled_at: datetime | None = None


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    template_id: str | None = Field(default=None, max_length=32)
    department_ids: list[str] | None = Field(default=None, max_length=100)
    scheduled_at: datetime | None = None


class CampaignTransition(BaseModel):
    to: CampaignStatus


class CampaignOut(ORM):
    id: str
    name: str
    description: str
    status: str
    template_id: str | None
    template_name: str | None = None
    template_difficulty: str | None = None
    department_ids: list[str] = []
    department_names: list[str] = []
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    stats: dict | None = None
