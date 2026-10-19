from revive_api.metrics import Metrics


def test_core_metrics_render_without_high_cardinality_labels():
    m = Metrics()
    m.job("success", 2.5)
    m.sandbox_run("build")
    m.llm_cost("openai", "model", 0.3)
    m.repair(True)
    text = m.render()
    assert 'revive_jobs_total{outcome="success"} 1' in text
    assert "job_id" not in text
    assert "revive_repair_success_ratio 1.0" in text
