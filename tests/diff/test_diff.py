# SPDX-License-Identifier: MIT
import subprocess
import sys
from pathlib import Path

from llm_registry.diff import DiffWarning, diff_models
from llm_registry.output import read_models_json
from llm_registry.schema.model_entry import ModelEntry, Pricing


FIXTURES = Path(__file__).parent.parent / "fixtures" / "diff"
SCRIPT = Path(__file__).parents[2] / "scripts" / "check_diff.py"


def _load(name: str) -> list[ModelEntry]:
    return list(read_models_json(FIXTURES / name).values())


def test_diff_models_flags_suspicious_changes_from_fixtures():
    warnings = diff_models(_load("before.json"), _load("after.json"))
    categories = [warning.category for warning in warnings]

    assert "provider_count_drop" in categories
    assert categories.count("missing_model") == 2
    assert "field_coverage_drop" in categories

    messages = "\n".join(warning.message for warning in warnings)
    assert "available model count dropped from 4 to 2" in messages
    assert "provider/m3: marked unavailable" in messages
    assert "provider/m4: missing from current file" in messages
    assert "context_window coverage dropped from 2 to 1" in messages
    assert "may be provider delisting or discovery regression" in messages


def test_diff_models_no_warning_for_identical_snapshot():
    models = _load("before.json")
    assert diff_models(models, models) == []


def test_count_drop_threshold_is_strictly_greater_than_threshold():
    previous = [
        ModelEntry(model_id=f"m{i}", provider="provider")
        for i in range(100)
    ]
    at_threshold = previous[:75]
    over_threshold = previous[:74]

    assert _warnings_by_category(
        diff_models(previous, at_threshold, count_drop_threshold=0.25)
    )["provider_count_drop"] == []
    assert _warnings_by_category(
        diff_models(previous, over_threshold, count_drop_threshold=0.25)
    )["provider_count_drop"]


def test_coverage_drop_threshold_is_strictly_greater_than_threshold():
    previous = [
        ModelEntry(
            model_id=f"m{i}",
            provider="provider",
            pricing=Pricing(input_per_1m=1.0),
        )
        for i in range(100)
    ]
    at_threshold = [
        ModelEntry(
            model_id=f"m{i}",
            provider="provider",
            pricing=Pricing(input_per_1m=1.0) if i < 75 else None,
        )
        for i in range(100)
    ]
    over_threshold = [
        ModelEntry(
            model_id=f"m{i}",
            provider="provider",
            pricing=Pricing(input_per_1m=1.0) if i < 74 else None,
        )
        for i in range(100)
    ]

    assert _warnings_by_category(
        diff_models(previous, at_threshold, coverage_drop_threshold=0.25)
    )["field_coverage_drop"] == []
    assert _warnings_by_category(
        diff_models(previous, over_threshold, coverage_drop_threshold=0.25)
    )["field_coverage_drop"]


def test_check_diff_script_defaults_to_zero_exit_with_warnings():
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(FIXTURES / "before.json"),
            str(FIXTURES / "after.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "model diff warning" in result.stdout
    assert "provider_count_drop" in result.stdout


def test_check_diff_script_strict_exits_nonzero_with_warnings():
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--strict",
            str(FIXTURES / "before.json"),
            str(FIXTURES / "after.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "model diff warning" in result.stdout


def _warnings_by_category(warnings: list[DiffWarning]) -> dict[str, list[DiffWarning]]:
    by_category = {
        "provider_count_drop": [],
        "missing_model": [],
        "field_coverage_drop": [],
    }
    for warning in warnings:
        by_category.setdefault(warning.category, []).append(warning)
    return by_category
