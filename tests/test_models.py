"""Tests for eagleeye.models — Pydantic schema validation."""

import json
from eagleeye.models import (
    BugScanResult,
    DiagramResult,
    PRReviewResult,
    RepoSummaryResult,
)


def test_pr_review_result_valid():
    data = {
        "summary": "Looks good overall.",
        "overall_verdict": "approve",
        "risk_level": "low",
        "file_comments": [
            {
                "file": "src/app.py",
                "line_range": "42-45",
                "severity": "medium",
                "category": "logic",
                "comment": "Consider handling None case.",
                "suggestion": "Add an early return if value is None.",
            }
        ],
        "positive_highlights": ["Clean separation of concerns"],
        "blocking_issues": [],
        "estimated_review_time_minutes": 10,
    }
    result = PRReviewResult.model_validate(data)
    assert result.overall_verdict == "approve"
    assert len(result.file_comments) == 1
    assert result.file_comments[0].severity == "medium"


def test_pr_review_result_defaults():
    data = {
        "summary": "Short diff.",
        "overall_verdict": "comment",
        "risk_level": "low",
    }
    result = PRReviewResult.model_validate(data)
    assert result.file_comments == []
    assert result.blocking_issues == []
    assert result.estimated_review_time_minutes == 5


def test_pr_review_result_from_json():
    raw = json.dumps({
        "summary": "OK",
        "overall_verdict": "request_changes",
        "risk_level": "high",
        "file_comments": [],
        "positive_highlights": [],
        "blocking_issues": ["Missing error handling in auth.py"],
        "estimated_review_time_minutes": 20,
    })
    result = PRReviewResult.model_validate_json(raw)
    assert result.overall_verdict == "request_changes"
    assert "auth.py" in result.blocking_issues[0]


def test_repo_summary_result_valid():
    data = {
        "project_name": "MyPipeline",
        "purpose": "ETL pipeline for analytics",
        "tech_stack": ["Python", "dbt", "Airflow"],
        "architecture_layers": [
            {
                "name": "Ingestion",
                "description": "Pulls data from sources",
                "key_files": ["dags/ingest.py"],
            }
        ],
        "entry_points": ["dags/ingest.py"],
        "key_patterns": ["DAG per data source"],
        "onboarding_steps": ["Install deps", "Set up Airflow"],
        "external_dependencies": ["Snowflake", "S3"],
        "open_questions": ["Why is the DAG timeout set to 2h?"],
    }
    result = RepoSummaryResult.model_validate(data)
    assert result.project_name == "MyPipeline"
    assert "dbt" in result.tech_stack


def test_bug_scan_result_valid():
    data = {
        "scan_target": "owner/repo PR #1",
        "findings": [
            {
                "file": "src/db.py",
                "line_range": "88",
                "severity": "critical",
                "category": "injection",
                "title": "SQL Injection via user input",
                "description": "User-supplied name is concatenated directly into the query.",
                "fix_suggestion": "Use parameterized queries.",
                "cwe_id": "CWE-89",
            }
        ],
        "critical_count": 1,
        "high_count": 0,
        "executive_summary": "One critical SQL injection found.",
        "most_urgent_fix": "Parameterize the query in src/db.py:88",
    }
    result = BugScanResult.model_validate(data)
    assert result.critical_count == 1
    assert result.findings[0].cwe_id == "CWE-89"


def test_diagram_result_valid():
    data = {
        "diagram_type": "architecture",
        "mermaid_source": "flowchart TD\n  A[API] --> B[DB]",
        "title": "System Architecture",
        "description": "Shows API to DB connection",
    }
    result = DiagramResult.model_validate(data)
    assert result.diagram_type == "architecture"
    assert "flowchart" in result.mermaid_source
