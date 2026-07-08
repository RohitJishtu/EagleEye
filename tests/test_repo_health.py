"""Tests for repo_auditor.py — each checker tested with fixture files.

Every test FAILS if the checker stops catching its target pattern.
Add a new fixture + test whenever a new anti-pattern is found in production.
"""

from __future__ import annotations

from pathlib import Path


from eagleeye.features.repo_auditor import (
    CicdDependencyChecker,
    HardcodedEmailChecker,
    HardcodedSecretChecker,
    IntOverflowChecker,
    MissingErrorHandlerChecker,
    SchemaDriftChecker,
    SqlInjectionChecker,
    run_audit,
)

VULNERABLE_FILES = Path(__file__).parent / "fixtures" / "vulnerable_files"


def _load(filename: str) -> str:
    return (VULNERABLE_FILES / filename).read_text()


# ---------------------------------------------------------------------------
# IntOverflowChecker
# ---------------------------------------------------------------------------

class TestIntOverflowChecker:
    checker = IntOverflowChecker()

    def test_catches_int_cast_near_rowid(self):
        content = _load("snowflake_input_to_bronze.py")
        findings = self.checker.check("snowflake_input_to_bronze.py", content)
        assert findings, "IntOverflowChecker missed .cast('int') near ROWID"
        assert findings[0].severity == "high"
        assert "overflow" in findings[0].description.lower()

    def test_no_false_positive_on_safe_cast(self):
        content = 'df.withColumn("status_code", F.col("code").cast("int"))'
        findings = self.checker.check("app.py", content)
        assert not findings, "False positive: cast('int') on status_code should not trigger"

    def test_no_false_positive_on_long_cast(self):
        content = 'df.withColumn("MaxRowID", F.col("ROWID").cast("long"))'
        findings = self.checker.check("pipeline.py", content)
        assert not findings, "False positive: .cast('long') is correct and should not trigger"

    def test_skips_non_python_files(self):
        content = '.cast("int") ROWID NUMBER(38,0)'
        findings = self.checker.check("schema.sql", content)
        assert not findings, "IntOverflowChecker should only scan .py files"


# ---------------------------------------------------------------------------
# SqlInjectionChecker
# ---------------------------------------------------------------------------

class TestSqlInjectionChecker:
    checker = SqlInjectionChecker()

    def test_catches_fstring_sql(self):
        content = _load("instantiate_snowflake_tables.py")
        findings = self.checker.check("instantiate_snowflake_tables.py", content)
        assert findings, "SqlInjectionChecker missed f-string SQL construction"
        assert findings[0].severity == "critical"
        assert "injection" in findings[0].title.lower()

    def test_catches_format_sql(self):
        content = 'query = "SELECT * FROM %s WHERE id = %d" % (table, user_id)'
        findings = self.checker.check("db.py", content)
        assert findings, "SqlInjectionChecker missed %-format SQL"

    def test_no_false_positive_on_static_sql(self):
        content = 'query = "SELECT * FROM users WHERE id = :id"'
        findings = self.checker.check("db.py", content)
        assert not findings, "False positive on static parameterized SQL"

    def test_skips_non_sql_files(self):
        content = 'f"SELECT * FROM {table}"'
        findings = self.checker.check("notes.md", content)
        assert not findings, "SqlInjectionChecker should skip .md files"


# ---------------------------------------------------------------------------
# CicdDependencyChecker
# ---------------------------------------------------------------------------

class TestCicdDependencyChecker:
    checker = CicdDependencyChecker()

    def test_catches_fail_on_run_failure_false(self):
        content = _load("create_snowflake_tables.yml")
        findings = self.checker.check("cicd/create_snowflake_tables.yml", content)
        # Note: fixture may not have fail_on_run_failure: false — check by injecting
        content_with_flag = content + "\nfail_on_run_failure: false\n"
        findings = self.checker.check("cicd/create_snowflake_tables.yml", content_with_flag)
        assert findings, "CicdDependencyChecker missed fail_on_run_failure: false"
        assert findings[0].severity == "high"

    def test_no_false_positive_when_true(self):
        content = "fail_on_run_failure: true\n"
        findings = self.checker.check("job.yml", content)
        assert not findings, "False positive: fail_on_run_failure: true should not trigger"

    def test_skips_python_files(self):
        content = "fail_on_run_failure: false"
        findings = self.checker.check("config.py", content)
        assert not findings, "CicdDependencyChecker should only scan yml/yaml/json"


# ---------------------------------------------------------------------------
# HardcodedEmailChecker
# ---------------------------------------------------------------------------

class TestHardcodedEmailChecker:
    checker = HardcodedEmailChecker()

    def test_catches_personal_email_in_cicd(self):
        content = _load("create_snowflake_tables.yml")
        findings = self.checker.check("create_snowflake_tables.yml", content)
        assert findings, "HardcodedEmailChecker missed personal email in on_failure"
        assert findings[0].severity == "medium"
        assert "example.com" in findings[0].title

    def test_no_false_positive_on_destination_id(self):
        content = "email_notifications:\n  on_failure:\n    destination_id: edna-ss-pbgroup\n"
        findings = self.checker.check("job.yml", content)
        assert not findings, "False positive: destination_id pattern should not trigger"


# ---------------------------------------------------------------------------
# SchemaDriftChecker
# ---------------------------------------------------------------------------

class TestSchemaDriftChecker:
    checker = SchemaDriftChecker()

    def test_catches_merge_schema_true(self):
        content = '.option("mergeSchema", "true").load()'
        findings = self.checker.check("pipeline.py", content)
        assert findings, "SchemaDriftChecker missed mergeSchema: true"
        assert findings[0].severity == "medium"
        assert "drift" in findings[0].title.lower() or "schema" in findings[0].title.lower()

    def test_no_false_positive_on_merge_schema_false(self):
        content = '.option("mergeSchema", "false").load()'
        findings = self.checker.check("pipeline.py", content)
        assert not findings


# ---------------------------------------------------------------------------
# HardcodedSecretChecker
# ---------------------------------------------------------------------------

class TestHardcodedSecretChecker:
    checker = HardcodedSecretChecker()

    def test_catches_hardcoded_password(self):
        content = 'password = "SuperSecret123"'
        findings = self.checker.check("config.py", content)
        assert findings, "HardcodedSecretChecker missed hardcoded password"
        assert findings[0].severity == "critical"

    def test_catches_github_token(self):
        content = "token = 'ghp_" + "A" * 36 + "'"
        findings = self.checker.check("deploy.py", content)
        assert findings, "HardcodedSecretChecker missed GitHub PAT"

    def test_catches_aws_key(self):
        content = "aws_access_key = 'AKIAIOSFODNN7EXAMPLE'"
        findings = self.checker.check("infra.py", content)
        assert findings, "HardcodedSecretChecker missed AWS access key"

    def test_no_false_positive_on_env_var(self):
        content = 'password = os.environ.get("DB_PASSWORD")'
        findings = self.checker.check("config.py", content)
        assert not findings, "False positive: env var lookup should not trigger"

    def test_skips_markdown(self):
        content = 'password = "example_password_here"'
        findings = self.checker.check("README.md", content)
        assert not findings, "HardcodedSecretChecker should skip .md files"


# ---------------------------------------------------------------------------
# MissingErrorHandlerChecker
# ---------------------------------------------------------------------------

class TestMissingErrorHandlerChecker:
    checker = MissingErrorHandlerChecker()

    def test_catches_bare_except(self):
        content = "try:\n    run_pipeline()\nexcept:\n    print('failed')\n"
        findings = self.checker.check("pipeline.py", content)
        assert findings, "MissingErrorHandlerChecker missed bare except"
        assert findings[0].severity == "medium"

    def test_catches_swallowed_exception(self):
        content = "try:\n    run_pipeline()\nexcept Exception:\n    pass\n"
        findings = self.checker.check("pipeline.py", content)
        assert findings, "MissingErrorHandlerChecker missed except: pass"

    def test_no_false_positive_on_specific_exception(self):
        content = "try:\n    connect()\nexcept ConnectionError as e:\n    logger.error(e)\n    raise\n"
        findings = self.checker.check("pipeline.py", content)
        assert not findings, "False positive: specific exception with re-raise is fine"


# ---------------------------------------------------------------------------
# Full audit run — integration of all checkers
# ---------------------------------------------------------------------------

class TestRunAudit:

    def test_audit_finds_all_issues_in_vulnerable_fixtures(self):
        """Full audit across all vulnerable fixtures must find critical and high issues."""
        file_contents = {
            "snowflake_input_to_bronze.py": _load("snowflake_input_to_bronze.py"),
            "instantiate_snowflake_tables.py": _load("instantiate_snowflake_tables.py"),
            "cicd/create_snowflake_tables.yml": _load("create_snowflake_tables.yml"),
        }
        # Inject fail_on_run_failure: false since fixture doesn't have it
        file_contents["cicd/create_snowflake_tables.yml"] += "\nfail_on_run_failure: false\n"

        result = run_audit(file_contents, repo="org/repo")

        assert result.files_checked == 3
        assert len(result.findings) > 0, "Audit found no issues in known-vulnerable fixtures"
        assert result.critical_count > 0, "No critical issues found — SQL injection should be critical"
        assert result.high_count > 0, "No high issues found — int overflow should be high"

    def test_audit_returns_findings_sorted_by_severity(self):
        file_contents = {
            "pipeline.py": (
                'password = "secret123"\n'           # critical
                'df.withColumn("id", F.col("ROWID").cast("int"))\n'  # high
                '.option("mergeSchema", "true")\n'   # medium
            )
        }
        result = run_audit(file_contents)
        severities = [f.severity for f in result.findings]
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        assert severities == sorted(severities, key=lambda s: order.get(s, 9)), (
            "Findings are not sorted by severity"
        )

    def test_audit_on_clean_code_returns_no_findings(self):
        file_contents = {
            "clean_pipeline.py": (
                "def run(spark, config):\n"
                "    df = spark.read.parquet(config['path'])\n"
                "    return df.withColumn('id', F.col('ROWID').cast('long'))\n"
            )
        }
        result = run_audit(file_contents)
        assert not result.findings, (
            f"False positives on clean code: {[f.title for f in result.findings]}"
        )
