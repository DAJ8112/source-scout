from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SearchProfile


def get_or_create_profile(session: Session) -> SearchProfile:
    profile = session.scalar(select(SearchProfile).order_by(SearchProfile.created_at).limit(1))
    if profile:
        return profile
    profile = SearchProfile()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def update_profile(session: Session, profile: SearchProfile, changes: dict) -> bool:
    changed = False
    for field, value in changes.items():
        if getattr(profile, field) != value:
            setattr(profile, field, value)
            changed = True
    if changed:
        profile.version += 1
        session.commit()
        session.refresh(profile)
    return changed


def extract_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        pages = [page.extract_text() or "" for page in reader.pages]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The uploaded file could not be read as a PDF") from exc
    text = "\n\n".join(page.strip() for page in pages if page.strip())
    text = text.replace("\x00", "").strip()
    if not text:
        raise ValueError("No selectable text was found in the PDF")
    return text
