# tests/test_agent_inputs.py
from eagleeye.graphs.agent_inputs import slice_all, PrAgentInput, SchemaAgentInput, LineageAgentInput, ReferenceAgentInput, ArchDriftInput
from eagleeye.models import MultiAgentReviewInput


def _make_inp(**overrides):
    base = dict(
        diff="diff --git a/schema.sql b/schema.sql\n+ALTER TABLE users DROP COLUMN phone;\ndiff --git a/jobs/load.yml b/jobs/load.yml\n+schedule: daily\ndiff --git a/features/user_features.py b/features/user_features.py\n+from features import age\nimport os\n",
        pr_metadata={"title": "Test PR"},
        file_list=["schema.sql", "jobs/load.yml", "features/user_features.py"],
        full_file_contents={
            "schema.sql": "ALTER TABLE users DROP COLUMN phone;",
            "jobs/load.yml": "schedule: daily",
            "features/user_features.py": "from features import age",
            "src/app.py": "def main(): pass",
        },
        blast_radius_md="",
        schema_impact_md="schema md",
        test_coverage_md="test md",
        security_scan_md="sec md",
        snowflake_lineage_md="",
        feature_store_md="feature md",
        edp_impact_md="edp md",
        schema_impact_result=None,
        max_file_bytes=10_000,
    )
    base.update(overrides)
    return MultiAgentReviewInput(**base)


def test_pr_agent_input_gets_all_files():
    inp = _make_inp()
    slices = slice_all(inp)
    pr = slices["pr_agent_input"]
    assert isinstance(pr, PrAgentInput)
    assert len(pr.full_file_contents) == 4  # all files
    assert pr.test_coverage_md == "test md"
    assert pr.security_scan_md == "sec md"


def test_schema_agent_input_has_no_file_contents():
    inp = _make_inp()
    slices = slice_all(inp)
    schema = slices["schema_agent_input"]
    assert isinstance(schema, SchemaAgentInput)
    assert not hasattr(schema, "full_file_contents")
    assert schema.schema_impact_md == "schema md"
    assert "schema.sql" in schema.schema_diff


def test_lineage_agent_input_only_pipeline_files():
    inp = _make_inp()
    slices = slice_all(inp)
    lineage = slices["lineage_agent_input"]
    assert isinstance(lineage, LineageAgentInput)
    assert "jobs/load.yml" in lineage.pipeline_file_contents
    assert "schema.sql" not in lineage.pipeline_file_contents
    assert "src/app.py" not in lineage.pipeline_file_contents


def test_reference_agent_input_is_populated():
    inp = _make_inp()
    slices = slice_all(inp)
    reference = slices["reference_agent_input"]
    assert isinstance(reference, ReferenceAgentInput)
    assert reference.reference_matches_md == ""  # populated at node time after search_index
    assert reference.diff == inp.diff
    assert reference.file_list == inp.file_list


def test_arch_drift_input_is_minimal():
    inp = _make_inp()
    slices = slice_all(inp)
    arch = slices["arch_drift_input"]
    assert isinstance(arch, ArchDriftInput)
    assert not hasattr(arch, "full_file_contents")
    assert "from features import age" in arch.added_imports
    assert "import os" in arch.added_imports


def test_slice_all_returns_five_keys():
    inp = _make_inp()
    slices = slice_all(inp)
    assert set(slices.keys()) == {
        "pr_agent_input", "schema_agent_input", "lineage_agent_input",
        "reference_agent_input", "arch_drift_input",
    }
