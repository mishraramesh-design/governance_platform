from typing import Optional
from pydantic import BaseModel


class EventSimulateRequest(BaseModel):
    project_id: str
    event_type: str  # requirements_submitted | commit_pushed | test_uploaded | release_candidate
    source_ref: Optional[str] = None
    triggered_by: Optional[str] = "system"


class TriageDecisionRequest(BaseModel):
    decision: str  # accept | dismiss | escalate
    decided_by_role: str
    notes: Optional[str] = ""


class AdjudicationDecisionRequest(BaseModel):
    human_decision: str  # agree_l1 | agree_l2 | override
    decided_by_role: str
    notes: Optional[str] = ""


class RepoAuditRequest(BaseModel):
    project_id: Optional[str] = None
    github_url: str
    name: Optional[str] = None
    git_token: Optional[str] = None


class RuntimeAnalyzeRequest(BaseModel):
    project_id: str
    log_text: str


class EdgeClientSimulateRequest(BaseModel):
    client_id: str
    project_id: str
    note: Optional[str] = ""
    event_type: Optional[str] = None
    source_ref: Optional[str] = None


class ArtifactGenerateRequest(BaseModel):
    project_id: str
    artifact_type: str
