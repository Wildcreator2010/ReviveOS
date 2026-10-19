from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JobEvent(BaseModel):
    id: str
    job_id: str
    project_id: str
    ts: datetime
    type: str
    payload: dict[str, Any]
