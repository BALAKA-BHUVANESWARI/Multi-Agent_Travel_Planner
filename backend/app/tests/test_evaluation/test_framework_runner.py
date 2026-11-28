"""The runner and the report."""
import json
import os

import pytest

from evaluation import cases as datasets
from evaluation import report
from evaluation import run_evaluation as runner
from evaluation.results import Result

CASE = {"id": "x", "description": "d", "category": "c", "target": "planner", "input": {},
        "expected_constraints": {}, "expected": {}}


def test_every_dataset_loads_and_ids_are_unique():
    ids = [c["id"] for name, _ in runner.EVALUATORS.values() for c in datasets.load(datasets.DATASETS / name)]
    assert len(ids) == len(set(ids)) > 40


@pytest.mark.parametrize("change", [{"synthetic": False}, {"label": "real data"}, {"cases": []},
                                    {"cases": [{"id": "x"}]}, {"cases": [CASE, CASE]},
                                    {"cases": [{**CASE, "target": "other"}]}])
def test_incomplete_datasets_are_refused(tmp_path, change):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"synthetic": True, "label": "SYNTHETIC", "cases": [CASE], **change}), "utf-8")
    with pytest.raises(datasets.DatasetError):
        datasets.load(path)


def test_a_crashing_evaluator_is_an_error_not_a_pass():
    row = runner.run_case("budget", CASE, lambda case: 1 / 0)
    assert row["status"] == "error" and "ZeroDivisionError" in row["failures"][0]


def test_not_run_and_not_supported_never_count_as_passed():
    rows = [{"status": s, "target": "planner"} for s in ("passed", "failed", "not_run", "not_supported")]
    assert report.counts(rows)["pass_rate"] == 0.5
    assert report.counts(rows[2:])["pass_rate"] is None


def test_the_command_writes_both_reports(tmp_path, capsys):
    assert runner.main(["--agent", "budget", "--out", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert data["agents"] == ["budget"] and data["summary"]["all"]["not_supported"] == 2
    assert data["summary"]["all"]["total"] == len(data["cases"]) and data["timestamp"]
    assert data["latency"]["cases"] == len(data["cases"]) and data["tokens"]["llm_calls"] == 0
    for part in ("## By agent", "## By category", "## Failed cases", "## Not supported", "## Not built yet"):
        assert part in text


def test_a_failure_gives_exit_code_1(tmp_path, monkeypatch):
    monkeypatch.setitem(runner.EVALUATORS, "budget", ("budget_cases.json", lambda case: Result("failed", ["no"])))
    assert runner.main(["--agent", "budget", "--deterministic-only", "--out", str(tmp_path)]) == 1


def test_the_settings_come_back_after_a_run(monkeypatch):
    monkeypatch.setenv("REAL_DATA", "1")
    monkeypatch.delenv("OBSERVABILITY", raising=False)
    runner.run(["budget"])
    assert os.environ["REAL_DATA"] == "1" and "OBSERVABILITY" not in os.environ


def test_reasons_for_failure_reach_the_markdown():
    row = {**CASE, "agent": "budget", "status": "failed", "failures": ["the total is wrong"], "findings": [],
           "seconds": 0.1, "measured": {}}
    data = report.build([row], {"timestamp": "t", "version": "v", "fixed_date": "d", "agents": ["budget"]})
    assert "the total is wrong" in report.markdown(data) and "0.0%" in report.markdown(data)
