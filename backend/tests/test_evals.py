"""Part 5-6: golden-set evals (baseline vs full) and the admin efficiency report."""

import time

from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, approved, wait
from test_accounts import login

from app.evals import run_evals, table


def test_golden_set_full_pipeline_beats_baseline(app):
    results = run_evals(app.state.ai, app.state.settings)
    metrics = {m["name"]: m for m in results["metrics"]}
    assert set(metrics) == {
        "Retrieval hit rate @3",
        "Citation validity (notes)",
        "Quiz answer correctness",
        "Guardrail catch rate",
    }
    for name in ("Retrieval hit rate @3", "Citation validity (notes)", "Guardrail catch rate"):
        assert metrics[name]["full"] > metrics[name]["baseline"], name
    assert metrics["Quiz answer correctness"]["full"] == 1.0
    assert metrics["Guardrail catch rate"]["false_positive_rate"]["full"] == 0.0
    assert results["tokens"]["full"] > 0 and results["demo_mode"] is True
    text = table(results)
    assert "Baseline" in text and "Retrieval hit rate @3" in text


def test_admin_runs_evals_and_reads_efficiency(client, app, signed_in, course):
    approved(signed_in, app, course)
    wait(app, signed_in.post(course + "/notes/generate", json={}))
    admin = client.__class__(app, headers=client.headers)
    assert login(admin, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    assert signed_in.get("/api/v1/admin/evals").status_code == 403
    assert signed_in.get("/api/v1/admin/efficiency").status_code == 403

    started = admin.post("/api/v1/admin/evals")
    assert started.status_code == 202 and started.json()["status"] == "running"
    assert admin.post("/api/v1/admin/evals").status_code == 409  # one at a time
    deadline = time.time() + 120
    while time.time() < deadline:
        runs = admin.get("/api/v1/admin/evals").json()
        if runs[0]["status"] != "running":
            break
        time.sleep(0.3)
    assert runs[0]["status"] == "succeeded", runs[0]
    assert len(runs[0]["results"]["metrics"]) == 4

    report = admin.get("/api/v1/admin/efficiency").json()
    assert report["totals"]["calls"] > 0 and report["token_unit"].startswith("characters")
    purposes = {p["purpose"] for p in report["by_purpose"]}
    assert {"syllabus", "unit_notes"} <= purposes
    course_row = next(c for c in report["by_course"] if c["title"] == "Ecosystems")
    assert course_row["generation_calls"] == 4  # 1 syllabus + 3 unit notes
    assert course_row["naive_input_tokens"] >= course_row["pipeline_input_tokens"] > 0
    assert report["per_generated_course"]["courses"] >= 1
    assert {"baseline", "full"} <= set(report["by_pipeline"])
    naive = report["naive_vs_pipeline"]
    assert naive["naive_input_tokens"] >= naive["pipeline_input_tokens"]
