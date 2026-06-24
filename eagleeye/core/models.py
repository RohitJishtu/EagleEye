"""Pydantic models defining the structured output contract between Claude and EagleEye."""

from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, computed_field



class FileComment(BaseModel):
    file: str
    line_range: Optional[str] = None
    severity: Literal["critical", "high", "medium", "low", "info"]
    category: str  # bug | security | style | performance | logic | test
    comment: str
    suggestion: Optional[str] = None


class AffectedFeature(BaseModel):
    name: str
    change_type: str  # added | modified | removed | schema_changed
    downstream_models: list[str] = Field(default_factory=list)
    details: str


class FeatureStoreImpact(BaseModel):
    affected_features: list[AffectedFeature] = Field(default_factory=list)
    summary: str = ""


class AffectedPipeline(BaseModel):
    name: str
    pipeline_type: str  # databricks_job | dbt_model | snowflake_pipeline | other
    change_type: str  # added | modified | removed | config_changed | schema_changed
    details: str


class EDPImpact(BaseModel):
    affected_pipelines: list[AffectedPipeline] = Field(default_factory=list)
    summary: str = ""


class PRReviewResult(BaseModel):
    summary: str
    overall_verdict: Literal["approve", "request_changes", "comment"]
    risk_level: Literal["low", "medium", "high", "critical"]
    requested_by: str = ""  # PR author GitHub login
    file_comments: list[FileComment] = Field(default_factory=list)
    positive_highlights: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    estimated_review_time_minutes: int = 5
    feature_store_impact: Optional[FeatureStoreImpact] = None
    edp_impact: Optional[EDPImpact] = None



class ArchitecturalLayer(BaseModel):
    name: str
    description: str
    key_files: list[str] = Field(default_factory=list)


class RepoSummaryResult(BaseModel):
    project_name: str
    purpose: str
    tech_stack: list[str] = Field(default_factory=list)
    architecture_layers: list[ArchitecturalLayer] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    key_patterns: list[str] = Field(default_factory=list)
    onboarding_steps: list[str] = Field(default_factory=list)
    external_dependencies: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)



class BugFinding(BaseModel):
    file: str
    line_range: Optional[str] = None
    severity: Literal["critical", "high", "medium", "low"]
    category: str  # security | null_deref | race_condition | injection | edge_case | logic_error | memory | auth
    title: str
    description: str
    reproduction_scenario: Optional[str] = None
    fix_suggestion: str
    cwe_id: Optional[str] = None  # e.g. "CWE-89"


class BugScanResult(BaseModel):
    scan_target: str
    findings: list[BugFinding] = Field(default_factory=list)
    executive_summary: str
    most_urgent_fix: Optional[str] = None

    @computed_field
    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    @computed_field
    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "high")

    @computed_field
    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "medium")

    @computed_field
    @property
    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "low")



class DiagramResult(BaseModel):
    diagram_type: str  # architecture | change_impact
    mermaid_source: str
    title: str
    description: str  # one-line explanation of what the diagram shows



class AgentFinding(BaseModel):
    """A single finding from one specialized review agent."""

    agent: str  # pr | schema | feature | lineage | arch_drift
    file: str
    line_range: Optional[str] = None
    severity: Literal["critical", "high", "medium", "low", "info"]
    category: str
    title: str
    description: str
    fix_suggestion: Optional[str] = None


class AgentResult(BaseModel):
    """Structured output from one specialized review agent."""

    agent: str
    findings: list[AgentFinding] = Field(default_factory=list)
    summary: str = ""
    error: Optional[str] = None  # non-fatal: one agent failing doesn't abort the review


class MultiAgentReviewInput(BaseModel):
    """Shared read-only input bundle passed to all 5 agents."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    diff: str
    pr_metadata: dict
    file_list: list[str]
    full_file_contents: dict[str, str]
    blast_radius_md: str
    schema_impact_md: str
    test_coverage_md: str
    security_scan_md: str
    feature_store_md: str = ""       # pre-computed feature store extract
    edp_impact_md: str = ""          # pre-computed EDP pipeline extract
    snowflake_lineage_md: str = ""   # Snowflake object usages (READ/WRITE/ALTER) per changed file
    schema_impact_result: Optional[Any] = None  # SchemaImpactResult from analysis.schema_impact
    max_file_bytes: int = 10_000
