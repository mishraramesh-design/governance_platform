from typing import Optional, List, Any
from pydantic import BaseModel, field_validator, model_validator


TRIAGE_DECISIONS = ("accept", "dismiss", "escalate", "defer")
ADJUDICATION_DECISIONS = ("agree_l1", "agree_l2", "override")


class EventSimulateRequest(BaseModel):
    project_id: str
    event_type: str  # requirements_submitted | commit_pushed | test_uploaded | release_candidate
    role: str
    source_ref: Optional[str] = None
    triggered_by: Optional[str] = "system"


class TriageDecisionRequest(BaseModel):
    decision: str  # accept | dismiss | escalate | defer
    role: str      # the role the signed-in user is acting as
    reason: Optional[str] = ""
    notes: Optional[str] = ""

    @field_validator("decision")
    @classmethod
    def _valid_decision(cls, v):
        if v not in TRIAGE_DECISIONS:
            raise ValueError(f"decision must be one of {'|'.join(TRIAGE_DECISIONS)}")
        return v

    @model_validator(mode="after")
    def _reason_required(self):
        if self.decision in ("dismiss", "defer") and not (self.reason or "").strip():
            raise ValueError(f"a non-empty reason is required to {self.decision} a finding")
        return self


class AdjudicationDecisionRequest(BaseModel):
    human_decision: str  # agree_l1 | agree_l2 | override
    role: str
    notes: Optional[str] = ""

    @field_validator("human_decision")
    @classmethod
    def _valid_decision(cls, v):
        if v not in ADJUDICATION_DECISIONS:
            raise ValueError(f"human_decision must be one of {'|'.join(ADJUDICATION_DECISIONS)}")
        return v


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
    role: Optional[str] = None
    note: Optional[str] = ""
    event_type: Optional[str] = None
    source_ref: Optional[str] = None


class EdgeClientBundleRequest(BaseModel):
    client_id: str      # EC-01 (Copilot) | EC-02 (Droid) — unverified client models only
    project_id: str
    role: str
    prompt_hash: str
    tool_calls: List[Any] = []
    input_hashes: List[str] = []
    output_text: str = ""


class ArtifactGenerateRequest(BaseModel):
    project_id: str
    artifact_type: str
