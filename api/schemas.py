# api/schemas.py
from pydantic import BaseModel
from typing import Optional

class UploadResponse(BaseModel):
    job_id: str
    status: str
    count: int

class JobMeta(BaseModel):
    job_id: str
    status: str
    count: Optional[int] = None
    error: Optional[str] = None
