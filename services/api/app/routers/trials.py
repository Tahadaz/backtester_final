from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import sqlalchemy as sa

from services.api.app.db import get_db  

router = APIRouter(prefix="/trials", tags=["trials"])

@router.get("/{trial_id}")
def get_trial(trial_id: str, session: Session = Depends(get_db)):
    stmt = sa.text("SELECT * FROM trial WHERE trial_id = :trial_id")
    row = session.execute(stmt, {"trial_id": trial_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="trial_not_found")
    return row
