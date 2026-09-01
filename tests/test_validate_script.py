"""Tests for the schema validation helper script."""

import json
import sys
from pathlib import Path

import pytest

from scripts import validate as validate_script

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"


def run_main(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["validate.py", *(str(arg) for arg in args)])
    exit_code = validate_script.main()
    return exit_code, capsys.readouterr()


def test_detect_schema_prefers_seed_v11_before_seed_v1():
    schema = validate_script.detect_schema(Path("seed-v1.1-example.yaml"))

    assert schema is not None
    assert schema.name == "seed-v1.1.schema.json"


def test_detect_schema_returns_none_for_unknown_file():
    assert validate_script.detect_schema(Path("unmapped-contract.json")) is None


def test_load_data_reads_json_and_yaml(tmp_path):
    json_file = tmp_path / "sample.json"
    yaml_file = tmp_path / "sample.yaml"
    json_file.write_text(json.dumps({"kind": "json"}))
    yaml_file.write_text("kind: yaml\ncount: 2\n")

    assert validate_script.load_data(json_file) == {"kind": "json"}
    assert validate_script.load_data(yaml_file) == {"kind": "yaml", "count": 2}


def test_load_data_exits_when_yaml_dependency_is_missing(tmp_path, monkeypatch, capsys):
    yaml_file = tmp_path / "sample.yaml"
    yaml_file.write_text("kind: yaml\n")
    monkeypatch.setattr(validate_script, "yaml", None)

    with pytest.raises(SystemExit) as excinfo:
        validate_script.load_data(yaml_file)

    assert excinfo.value.code == 1
    assert "pyyaml not installed" in capsys.readouterr().err


def test_validate_file_reports_unknown_schema(tmp_path):
    target = tmp_path / "unknown.json"
    target.write_text("{}")

    ok, errors = validate_script.validate_file(target)

    assert ok is False
    assert errors == ["Cannot detect schema for unknown.json"]


def test_validate_file_accepts_explicit_schema_override(tmp_path):
    target = tmp_path / "contract.json"
    target.write_text(
        json.dumps(
            {
                "event": "product.release",
                "source": {"organ": "ORGAN-II"},
                "target": {"organ": "ORGAN-IV"},
                "payload": {
                    "version": "1.0.0",
                    "repo": "organvm/schema-definitions",
                    "changelog_url": "https://example.test/changelog",
                },
            }
        )
    )

    ok, errors = validate_script.validate_file(
        target,
        SCHEMAS_DIR / "dispatch-payload.schema.json",
    )

    assert ok is True
    assert errors == []


def test_validate_file_formats_nested_errors_in_path_order(tmp_path):
    target = tmp_path / "dispatch-invalid.json"
    target.write_text(
        json.dumps(
            {
                "event": "theory.published",
                "source": {"organ": "ORGAN-I"},
                "target": {"organ": "ORGAN-II"},
                "payload": {
                    "artifact_id": "theory-001",
                    "title": "Foundational Theory",
                    "source_repo": "recursive-engine",
                },
                "metadata": {
                    "priority": "urgent",
                    "ttl_seconds": -1,
                },
            }
        )
    )

    ok, errors = validate_script.validate_file(target)

    assert ok is False
    assert len(errors) == 2
    assert errors[0].startswith("  metadata.priority:")
    assert "'urgent'" in errors[0]
    assert errors[1].startswith("  metadata.ttl_seconds:")
    assert "less than the minimum" in errors[1]


def test_main_without_targets_prints_help_and_succeeds(monkeypatch, capsys):
    exit_code, captured = run_main(monkeypatch, capsys)

    assert exit_code == 0
    assert "Validate files against JSON Schema" in captured.out


def test_main_fails_missing_explicit_files_and_counts_existing_passes(
    tmp_path,
    monkeypatch,
    capsys,
):
    target = tmp_path / "contract.json"
    missing = tmp_path / "missing.json"
    target.write_text(
        json.dumps(
            {
                "event": "product.release",
                "source": {"organ": "ORGAN-II"},
                "target": {"organ": "ORGAN-IV"},
                "payload": {
                    "version": "1.0.0",
                    "repo": "organvm/schema-definitions",
                    "changelog_url": "https://example.test/changelog",
                },
            }
        )
    )

    exit_code, captured = run_main(
        monkeypatch,
        capsys,
        "--schema",
        SCHEMAS_DIR / "dispatch-payload.schema.json",
        target,
        missing,
    )

    assert exit_code == 1
    assert "PASS contract.json" in captured.out
    assert f"FAIL {missing}: not found" in captured.out
    assert "1 passed, 1 failed" in captured.out


def test_main_can_explicitly_ignore_missing_files(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "optional.json"

    exit_code, captured = run_main(
        monkeypatch,
        capsys,
        "--ignore-missing",
        missing,
    )

    assert exit_code == 0
    assert f"SKIP {missing}: not found" in captured.out
    assert "0 passed, 0 failed" in captured.out


def test_main_returns_failure_and_prints_validation_errors(tmp_path, monkeypatch, capsys):
    target = tmp_path / "dispatch-invalid.json"
    target.write_text(
        json.dumps(
            {
                "event": "theory.published",
                "source": {"organ": "ORGAN-I"},
                "target": {"organ": "ORGAN-II"},
                "payload": {
                    "artifact_id": "theory-001",
                    "title": "Foundational Theory",
                    "source_repo": "recursive-engine",
                },
                "metadata": {"priority": "urgent"},
            }
        )
    )

    exit_code, captured = run_main(monkeypatch, capsys, target)

    assert exit_code == 1
    assert "FAIL dispatch-invalid.json" in captured.out
    assert "metadata.priority" in captured.out
    assert "0 passed, 1 failed" in captured.out


def test_main_all_examples_uses_json_and_yaml_globs(tmp_path, monkeypatch, capsys):
    dispatch = tmp_path / "dispatch-example.json"
    seed = tmp_path / "seed-minimal.yaml"
    dispatch.write_text(
        json.dumps(
            {
                "event": "product.release",
                "source": {"organ": "ORGAN-II"},
                "target": {"organ": "ORGAN-IV"},
                "payload": {
                    "version": "1.0.0",
                    "repo": "organvm/schema-definitions",
                    "changelog_url": "https://example.test/changelog",
                },
            }
        )
    )
    seed.write_text('schema_version: "1.0"\norgan: I\nrepo: seed\norg: meta-organvm\n')
    monkeypatch.setattr(validate_script, "EXAMPLES_DIR", tmp_path)

    exit_code, captured = run_main(monkeypatch, capsys, "--all-examples")

    assert exit_code == 0
    assert "PASS dispatch-example.json" in captured.out
    assert "PASS seed-minimal.yaml" in captured.out
    assert "2 passed, 0 failed" in captured.out
