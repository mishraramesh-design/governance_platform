from typing import Optional, List, Any
import re
from pydantic import BaseModel, Field, field_validator, model_validator


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


class GovernanceStudioRunRequest(BaseModel):
    name: str
    github_url: Optional[str] = None
    target_url: Optional[str] = None
    authorization_confirmed: bool = False
    authorization_owner: Optional[str] = None
    authorization_reference: Optional[str] = None
    authorization_scope: Optional[str] = None
    duration_hours: int = 2
    frs_text: Optional[str] = None
    frs_filename: Optional[str] = None
    runtime_logs: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _name_required(cls, value):
        value = (value or "").strip()
        if not value or len(value) > 120:
            raise ValueError("name must be between 1 and 120 characters")
        return value

    @field_validator("github_url")
    @classmethod
    def _github_url(cls, value):
        if value is None or not value.strip():
            return None
        value = value.strip().rstrip("/")
        if not re.fullmatch(r"https://github\.com/[\w.\-]+/[\w.\-]+", value):
            raise ValueError("github_url must be an HTTPS GitHub repository URL")
        return value

    @field_validator("target_url")
    @classmethod
    def _target_url(cls, value):
        if value is None or not value.strip():
            return None
        from urllib.parse import urlsplit
        value = value.strip()
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("target_url must be an HTTP(S) URL without embedded credentials")
        if len(value) > 2048:
            raise ValueError("target_url is too long")
        return value

    @field_validator("duration_hours")
    @classmethod
    def _duration_bounds(cls, value):
        if value < 1 or value > 168:
            raise ValueError("duration_hours must be between 1 and 168")
        return value

    @field_validator("frs_text", "runtime_logs")
    @classmethod
    def _bounded_inputs(cls, value):
        if value is not None and len(value) > 2_000_000:
            raise ValueError("input is limited to 2 MB")
        return value

    @field_validator("authorization_owner", "authorization_reference", "authorization_scope", "frs_filename")
    @classmethod
    def _bounded_scope_fields(cls, value):
        if value is not None and len(value) > 2000:
            raise ValueError("authorization fields are limited to 2,000 characters")
        return value.strip() if value else value


class StudioWebScanRequest(BaseModel):
    mode: str = "passive"
    active_scan_staging_confirmed: bool = False
    excluded_paths: List[str] = Field(default_factory=list)

    @field_validator("mode")
    @classmethod
    def _valid_web_scan_mode(cls, value):
        if value not in ("passive", "active"):
            raise ValueError("mode must be passive or active")
        return value

    @field_validator("excluded_paths")
    @classmethod
    def _valid_scan_exclusions(cls, value):
        if len(value) > 50:
            raise ValueError("at most 50 excluded URL paths are allowed")
        normalized = []
        for path in value:
            path = (path or "").strip()
            if not path:
                continue
            if not path.startswith("/") or "?" in path or "#" in path or "\\" in path or ".." in path.split("/"):
                raise ValueError("excluded paths must be same-host URL paths without query strings, fragments, backslashes, or parent segments")
            normalized.append(path)
        return sorted(set(normalized))


class StudioFrameworkAssessmentRequest(BaseModel):
    """Explicitly bounded browser, API-contract or load smoke assessment."""
    framework: str
    staging_authorized: bool = False
    openapi_url: Optional[str] = None
    max_examples: int = Field(default=10, ge=1, le=25)
    virtual_users: int = Field(default=2, ge=1, le=3)
    duration_seconds: int = Field(default=15, ge=5, le=30)
    max_p95_ms: int = Field(default=1000, ge=100, le=10000)
    max_error_rate_percent: float = Field(default=1.0, ge=0, le=10)

    @field_validator("framework")
    @classmethod
    def _framework_allowed(cls, value):
        if value not in ("playwright", "schemathesis", "k6"):
            raise ValueError("framework must be playwright, schemathesis, or k6")
        return value

    @field_validator("openapi_url")
    @classmethod
    def _openapi_url_valid(cls, value):
        if value is not None:
            from urllib.parse import urlsplit
            parsed = urlsplit(value.strip())
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("openapi_url must be an HTTPS URL without credentials, query, or fragment")
            if len(value) > 2048:
                raise ValueError("openapi_url is too long")
            return value.strip()
        return value


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
