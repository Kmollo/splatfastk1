from splatforge.ui.server import APP_CSS, APP_JS, INDEX_HTML


def test_ui_has_upload_form():
    assert 'id="uploadForm"' in INDEX_HTML
    assert 'name="video"' in INDEX_HTML
    assert "Create Splat" in INDEX_HTML


def test_ui_scripts_poll_jobs():
    assert "/api/jobs" in APP_JS
    assert "pollJob" in APP_JS
    assert "/api/hardware" in APP_JS


def test_ui_css_is_not_empty():
    assert ".dropzone" in APP_CSS
