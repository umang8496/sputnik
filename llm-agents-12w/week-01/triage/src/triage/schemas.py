from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

class Evidence(BaseModel):
    line: int = Field(ge=1, description="1-based line number in app.log")
    text: str = Field(description="Exact text of that log line, copied verbatim")

class IncidentSummary(BaseModel):
    service: str = Field(description="Affected service name, as it appears in the alert or logs")
    symptom: str = Field(description="User-visible effect in one sentence")
    first_error_ts: datetime = Field(description="Timestamp of the first ERROR line related to the incident")
    error_signature: str = Field(description="Stable error identifier, e.g. exception class + message template")
    suspected_component: str = Field(description="Component most likely at fault, e.g. db-pool, cache, config")
    severity: Literal["sev1", "sev2", "sev3", "sev4"]
    evidence: list[Evidence] = Field(min_length=1, max_length=8)
    confidence: float = Field(ge=0, le=1, description="0-1; lower it when evidence is weak")
