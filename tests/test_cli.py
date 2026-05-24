from splatforge.cli import main


def test_doctor_json_runs(capsys):
    exit_code = main(["doctor", "--json"])
    output = capsys.readouterr().out

    assert exit_code in {0, 1}
    assert '"name": "ffmpeg"' in output


def test_doctor_hardware_json_runs(capsys):
    exit_code = main(["doctor", "--json", "--hardware"])
    output = capsys.readouterr().out

    assert exit_code in {0, 1}
    assert '"hardware"' in output
    assert '"tools"' in output


def test_create_rejects_missing_source(tmp_path):
    exit_code = main(["create", str(tmp_path / "missing.mp4"), "--dry-run"])

    assert exit_code == 2
