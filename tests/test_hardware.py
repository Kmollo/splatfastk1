from splatforge.hardware import classify_hardware, collect_hardware


def test_hardware_collection_returns_recommendation(tmp_path):
    report = collect_hardware(tmp_path)

    assert report.free_disk_gb >= 0
    assert report.tier
    assert report.recommendation


def test_hardware_classifier_prefers_small_jobs_without_gpu():
    tier, recommendation = classify_hardware(ram_gb=16, vram_gb=0, free_disk_gb=100)

    assert tier == "cpu-only/small"
    assert "short" in recommendation
