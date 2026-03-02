from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime

class ArtifactOut(BaseModel):
    id: UUID
    run_id: UUID
    symbol: Optional[str]
    artifact_type: str
    name: str
    object_key: str
    bucket: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime
    url: str
