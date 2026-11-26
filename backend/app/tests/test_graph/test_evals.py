"""The evaluation guarantees the multi-agent graph exists to provide must not regress."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("run_evals", Path(__file__).resolve().parents[3] / "evals" / "run_evals.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def test_graph_meets_all_guarantees_and_beats_baseline():
    g, b = ev.run_suite(ev.CASES, "graph"), ev.run_suite(ev.CASES, "baseline")
    ga, ba = ev.aggregate(g), ev.aggregate(b)
    for m in ("outcome", "budget", "dates", "overlaps", "rain", "prices", "schema", "constraints"):
        assert ga[m][0] == 1.0, (m, [r["id"] for r in g if r["scores"].get(m) not in (True, 1.0, None)])
    assert ba["outcome"][0] < ga["outcome"][0] and ba["budget"][0] < ga["budget"][0] and ba["rain"][0] < ga["rain"][0]
    replans = [r for r in g if next(c for c in ev.CASES if c["id"] == r["id"]).get("needs_replan")]
    assert replans and all(r["retries"] >= 1 for r in replans), "'tight' prompts must really trigger a retry"
    assert len(ev.CASES) >= 15


def test_report_renders(tmp_path):
    g, b = ev.run_suite(ev.CASES, "graph"), ev.run_suite(ev.CASES, "baseline")
    text = ev.build_report(g, b, None)
    assert "Multi-agent graph vs single-agent baseline" in text and "Skipped: no LLM API keys" in text
