"""In-app notifications (the only 'messaging' channel the platform has)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Notification


def notify(db: Session, org_id: str, user_id: str, kind: str, title: str, body: str = "",
           link: str | None = None) -> None:
    db.add(Notification(org_id=org_id, user_id=user_id, kind=kind, title=title, body=body, link=link))
