from __future__ import annotations

import cgi
import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from splatforge.doctor import collect_diagnostics
from splatforge.hardware import collect_hardware


PROJECT_ROOT = Path.cwd()
WORKSPACE_DIR = PROJECT_ROOT / "ui-workspace"
UPLOAD_DIR = WORKSPACE_DIR / "uploads"
OUTPUT_DIR = WORKSPACE_DIR / "outputs"
VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}


@dataclass
class Job:
    id: str
    filename: str
    quality: str
    matcher: str
    backend: str
    dry_run: bool
    status: str = "queued"
    returncode: int | None = None
    output_path: str | None = None
    log: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


def run_ui(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> int:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), SplatfastK1Handler)
    url = f"http://{host}:{port}"
    print(f"SplatfastK1 UI running at {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Stopping SplatfastK1 UI.")
    finally:
        server.server_close()
    return 0


class SplatfastK1Handler(BaseHTTPRequestHandler):
    server_version = "SplatfastK1UI/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(INDEX_HTML)
            return
        if parsed.path == "/app.css":
            self.send_text(APP_CSS, "text/css")
            return
        if parsed.path == "/app.js":
            self.send_text(APP_JS, "application/javascript")
            return
        if parsed.path == "/api/doctor":
            self.send_json([asdict(status) for status in collect_diagnostics()])
            return
        if parsed.path == "/api/hardware":
            self.send_json(collect_hardware(PROJECT_ROOT).to_dict())
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                payload = asdict(job) if job else None
            if payload is None:
                self.send_error(HTTPStatus.NOT_FOUND, "Job not found")
                return
            self.send_json(payload)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/jobs":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            job = self.create_job_from_upload()
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return

        with JOBS_LOCK:
            JOBS[job.id] = job

        thread = threading.Thread(target=run_job, args=(job.id,), daemon=True)
        thread.start()
        self.send_json(asdict(job), status=HTTPStatus.CREATED)

    def create_job_from_upload(self) -> Job:
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type"),
            },
        )
        file_item = form["video"] if "video" in form else None
        if file_item is None or not file_item.filename:
            raise ValueError("Upload a video file.")

        original_name = Path(file_item.filename).name
        suffix = Path(original_name).suffix.lower()
        if suffix not in VIDEO_EXTENSIONS:
            raise ValueError("Use a video file: mp4, mov, mkv, avi, m4v, or webm.")

        quality = get_form_value(form, "quality", "balanced")
        matcher = get_form_value(form, "matcher", "sequential")
        backend = get_form_value(form, "backend", "brush")
        dry_run = get_form_value(form, "dry_run", "false") == "true"
        if quality not in {"fast", "balanced", "high"}:
            raise ValueError("Invalid quality preset.")
        if matcher not in {"sequential", "exhaustive"}:
            raise ValueError("Invalid matcher.")
        if backend not in {"brush", "none"}:
            raise ValueError("Invalid backend.")

        job_id = uuid.uuid4().hex[:12]
        upload_path = UPLOAD_DIR / f"{job_id}_{original_name}"
        with upload_path.open("wb") as handle:
            shutil.copyfileobj(file_item.file, handle)

        output_path = OUTPUT_DIR / f"{Path(original_name).stem}_{job_id}"
        return Job(
            id=job_id,
            filename=original_name,
            quality=quality,
            matcher=matcher,
            backend=backend,
            dry_run=dry_run,
            output_path=str(output_path),
            log=[f"Uploaded {original_name}"],
        )

    def send_html(self, content: str) -> None:
        self.send_text(content, "text/html; charset=utf-8")

    def send_text(self, content: str, content_type: str) -> None:
        body = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def get_form_value(form: cgi.FieldStorage, key: str, default: str) -> str:
    if key not in form:
        return default
    value = form[key].value
    return value if isinstance(value, str) else default


def run_job(job_id: str) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id]
        job.status = "running"
        job.log.append("Starting SplatfastK1 pipeline.")

    upload = next(UPLOAD_DIR.glob(f"{job_id}_*"))
    output_path = Path(job.output_path or OUTPUT_DIR / upload.stem).resolve()
    command = [
        sys.executable,
        "-u",
        "-m",
        "splatforge.cli",
        "create",
        str(upload),
        "--output",
        str(output_path),
        "--quality",
        job.quality,
        "--matcher",
        job.matcher,
        "--backend",
        job.backend,
    ]
    if job.dry_run:
        command.append("--dry-run")

    with JOBS_LOCK:
        job.log.append("Command: " + " ".join(command))

    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        with JOBS_LOCK:
            JOBS[job_id].log.append(line.rstrip())
    returncode = process.wait()

    with JOBS_LOCK:
        job = JOBS[job_id]
        job.returncode = returncode
        job.status = "complete" if returncode == 0 else "failed"
        job.log.append(f"Finished with exit code {returncode}.")


INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>SplatfastK1</title>
    <link rel="stylesheet" href="/app.css" />
  </head>
  <body>
    <main class="shell">
      <header class="topbar">
        <h1>SplatfastK1</h1>
        <div id="toolBadge" class="badge badge-muted">Checking tools...</div>
      </header>

      <p class="lede">Turn a video into a Blender-ready Gaussian splat. Pick a video, pick a quality, hit Create.</p>

      <form id="uploadForm" class="card">
        <label class="dropzone" for="videoInput">
          <input id="videoInput" name="video" type="file" accept="video/*" required />
          <div class="dropzone-inner">
            <div class="dropzone-icon">+</div>
            <div id="fileLabel" class="dropzone-text">Drop a video here or click to choose</div>
            <div class="dropzone-hint">MP4, MOV, MKV, AVI, M4V, or WebM</div>
          </div>
        </label>

        <div class="quality-row">
          <span class="label">Quality</span>
          <div class="segmented" role="radiogroup" aria-label="Quality">
            <label><input type="radio" name="quality" value="fast" /><span>Fast</span></label>
            <label><input type="radio" name="quality" value="balanced" checked /><span>Balanced</span></label>
            <label><input type="radio" name="quality" value="high" /><span>High</span></label>
          </div>
        </div>

        <button class="primary" type="submit">Create Splat</button>
      </form>

      <section id="runCard" class="card run-card hidden">
        <div class="run-header">
          <div>
            <div class="run-title" id="runTitle">Working...</div>
            <div class="run-sub" id="runSub">Starting</div>
          </div>
          <div class="run-time">
            <div class="time-value" id="elapsedTime">00:00</div>
            <div class="time-label">elapsed</div>
          </div>
        </div>

        <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>

        <ol class="steps" id="stepList">
          <li data-step="upload"><span class="dot"></span><span class="step-label">Upload</span></li>
          <li data-step="frames"><span class="dot"></span><span class="step-label">Extract frames</span></li>
          <li data-step="features"><span class="dot"></span><span class="step-label">Find features</span></li>
          <li data-step="match"><span class="dot"></span><span class="step-label">Match frames</span></li>
          <li data-step="reconstruct"><span class="dot"></span><span class="step-label">Build 3D model</span></li>
          <li data-step="splat"><span class="dot"></span><span class="step-label">Train splat</span></li>
        </ol>

        <details class="log-details">
          <summary>Show detailed log</summary>
          <pre id="logOutput"></pre>
        </details>
      </section>

      <details class="diagnostics">
        <summary>System details</summary>
        <div class="diag-grid">
          <div>
            <h3>Tools</h3>
            <div id="doctorStatus" class="diag-list"></div>
          </div>
          <div>
            <h3>This computer</h3>
            <div id="hardwareStatus" class="diag-list">Checking...</div>
          </div>
        </div>
      </details>
    </main>
    <script src="/app.js"></script>
  </body>
</html>
"""


APP_CSS = """
:root {
  color-scheme: light;
  --bg: #ffffff;
  --text: #000000;
  --muted: #6b6b6b;
  --line: #e5e5e5;
  --line-strong: #000000;
  --soft: #f6f6f6;
  --danger: #c00000;
  --success: #1f7a1f;
}

* { box-sizing: border-box; }
html, body { background: var(--bg); color: var(--text); }
body {
  margin: 0;
  min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, ui-sans-serif, system-ui, sans-serif;
  font-size: 16px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.shell {
  width: min(720px, calc(100vw - 32px));
  margin: 0 auto;
  padding: 40px 0 64px;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.01em;
}
.lede {
  margin: 0 0 28px;
  color: var(--muted);
  font-size: 15px;
}
.badge {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--line);
}
.badge-muted { color: var(--muted); background: var(--soft); }
.badge-ok { color: var(--success); border-color: var(--success); background: #f1faf1; }
.badge-bad { color: var(--danger); border-color: var(--danger); background: #fdf2f2; }

.card {
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 20px;
}

.dropzone {
  display: block;
  border: 2px dashed var(--line);
  border-radius: 10px;
  background: var(--soft);
  padding: 32px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.dropzone:hover { border-color: var(--line-strong); }
.dropzone input { display: none; }
.dropzone-inner { display: grid; gap: 8px; justify-items: center; }
.dropzone-icon {
  width: 44px; height: 44px;
  border: 1.5px solid var(--text);
  border-radius: 50%;
  display: grid; place-items: center;
  font-size: 22px; font-weight: 400;
  color: var(--text);
}
.dropzone-text { font-size: 16px; font-weight: 600; color: var(--text); }
.dropzone-hint { font-size: 13px; color: var(--muted); }
.dropzone.has-file { background: #fff; border-color: var(--line-strong); border-style: solid; }

.quality-row {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 20px;
}
.label { font-size: 14px; font-weight: 600; color: var(--text); }
.segmented {
  display: inline-flex;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}
.segmented label {
  position: relative;
  padding: 8px 16px;
  font-size: 14px;
  color: var(--muted);
  cursor: pointer;
  border-right: 1px solid var(--line);
  user-select: none;
}
.segmented label:last-child { border-right: none; }
.segmented input { position: absolute; opacity: 0; pointer-events: none; }
.segmented label:has(input:checked) {
  background: var(--text); color: var(--bg); font-weight: 600;
}

.primary {
  width: 100%;
  margin-top: 24px;
  padding: 14px 20px;
  background: var(--text);
  color: var(--bg);
  border: none;
  border-radius: 10px;
  font: inherit;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.15s;
}
.primary:hover { opacity: 0.85; }
.primary:disabled { opacity: 0.4; cursor: not-allowed; }

.hidden { display: none !important; }

.run-card { padding: 28px; }
.run-card.is-success { border-color: var(--success); }
.run-card.is-error { border-color: var(--danger); }
.run-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 16px; margin-bottom: 20px;
}
.run-title { font-size: 18px; font-weight: 700; }
.run-sub { font-size: 14px; color: var(--muted); margin-top: 4px; }
.run-time { text-align: right; }
.time-value { font-size: 24px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1; }
.time-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; margin-top: 4px; }

.progress-bar {
  height: 6px;
  background: var(--soft);
  border-radius: 999px;
  overflow: hidden;
  margin-bottom: 24px;
}
.progress-fill {
  height: 100%;
  width: 0%;
  background: var(--text);
  border-radius: 999px;
  transition: width 0.4s ease-out;
}
.run-card.is-error .progress-fill { background: var(--danger); }

.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.steps li {
  display: flex; align-items: center; gap: 12px;
  font-size: 14px;
  color: var(--muted);
  padding: 6px 0;
}
.steps li .dot {
  width: 14px; height: 14px;
  border-radius: 50%;
  border: 1.5px solid var(--line);
  flex-shrink: 0;
  position: relative;
}
.steps li.done .dot { background: var(--text); border-color: var(--text); }
.steps li.done .dot::after {
  content: "";
  position: absolute; left: 3px; top: 0px;
  width: 4px; height: 8px;
  border: solid var(--bg); border-width: 0 1.5px 1.5px 0;
  transform: rotate(45deg);
}
.steps li.active .dot {
  border-color: var(--text);
  animation: pulse 1.2s infinite ease-in-out;
}
.steps li.error .dot { background: var(--danger); border-color: var(--danger); }
.steps li.done, .steps li.active { color: var(--text); font-weight: 600; }
.steps li.error { color: var(--danger); font-weight: 600; }

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(0,0,0,0.4); }
  50% { box-shadow: 0 0 0 6px rgba(0,0,0,0); }
}

.log-details {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}
.log-details summary {
  cursor: pointer;
  font-size: 13px;
  color: var(--muted);
  user-select: none;
}
.log-details pre {
  margin: 12px 0 0;
  padding: 14px;
  background: var(--soft);
  border-radius: 8px;
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text);
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.diagnostics {
  margin-top: 28px;
  font-size: 14px;
}
.diagnostics summary {
  cursor: pointer;
  color: var(--muted);
  font-size: 13px;
  padding: 6px 0;
  user-select: none;
}
.diag-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin-top: 16px;
  padding: 20px;
  background: var(--soft);
  border-radius: 8px;
}
.diag-grid h3 { margin: 0 0 10px; font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
.diag-list { display: grid; gap: 8px; font-size: 13px; }
.diag-item { display: flex; justify-content: space-between; gap: 12px; }
.diag-item .k { color: var(--muted); }
.diag-item .v { color: var(--text); font-weight: 500; text-align: right; }
.diag-item .v.ok { color: var(--success); }
.diag-item .v.bad { color: var(--danger); }

@media (max-width: 600px) {
  .quality-row { flex-direction: column; align-items: stretch; gap: 12px; }
  .segmented { display: grid; grid-template-columns: repeat(3, 1fr); }
  .diag-grid { grid-template-columns: 1fr; }
  .run-header { flex-direction: column; }
  .run-time { text-align: left; }
}
"""


APP_JS = """
const form = document.querySelector("#uploadForm");
const input = document.querySelector("#videoInput");
const dropzone = document.querySelector(".dropzone");
const fileLabel = document.querySelector("#fileLabel");
const submitBtn = form.querySelector(".primary");
const runCard = document.querySelector("#runCard");
const runTitle = document.querySelector("#runTitle");
const runSub = document.querySelector("#runSub");
const elapsedTime = document.querySelector("#elapsedTime");
const progressFill = document.querySelector("#progressFill");
const stepList = document.querySelector("#stepList");
const logOutput = document.querySelector("#logOutput");
const toolBadge = document.querySelector("#toolBadge");
const doctorStatus = document.querySelector("#doctorStatus");
const hardwareStatus = document.querySelector("#hardwareStatus");

const STEP_ORDER = ["upload", "frames", "features", "match", "reconstruct", "splat"];
const STEP_LABELS = {
  upload: "Uploading video",
  frames: "Extracting frames",
  features: "Finding features",
  match: "Matching frames",
  reconstruct: "Building 3D model",
  splat: "Training Gaussian splat",
};

let pollTimer = null;
let tickTimer = null;
let jobStartedAt = null;

input.addEventListener("change", () => {
  const file = input.files[0];
  if (file) {
    fileLabel.textContent = file.name;
    dropzone.classList.add("has-file");
  } else {
    fileLabel.textContent = "Drop a video here or click to choose";
    dropzone.classList.remove("has-file");
  }
});

loadDoctor();
loadHardware();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!input.files.length) return;
  submitBtn.disabled = true;
  submitBtn.textContent = "Uploading...";

  showRunCard();
  setStep("upload", "active");
  runTitle.textContent = "Uploading video";
  runSub.textContent = input.files[0].name;
  startTicker();

  const data = new FormData(form);
  data.set("dry_run", "false");
  let response;
  try {
    response = await fetch("/api/jobs", { method: "POST", body: data });
  } catch (e) {
    showError("Upload failed: " + e.message);
    return;
  }
  if (!response.ok) {
    showError(await response.text());
    return;
  }
  const job = await response.json();
  jobStartedAt = job.created_at * 1000;
  setStep("upload", "done");
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => pollJob(job.id), 900);
});

async function pollJob(id) {
  let response;
  try {
    response = await fetch(`/api/jobs/${id}`);
  } catch (e) { return; }
  if (!response.ok) return;
  const job = await response.json();
  renderJob(job);
  if (job.status === "complete" || job.status === "failed") {
    clearInterval(pollTimer);
    pollTimer = null;
    stopTicker();
    loadDoctor();
  }
}

function renderJob(job) {
  jobStartedAt = job.created_at * 1000;
  logOutput.textContent = job.log.join("\\n");
  logOutput.scrollTop = logOutput.scrollHeight;

  const stage = detectStage(job.log);
  const lastLine = lastMeaningfulLine(job.log);

  if (job.status === "complete") {
    setAllStepsDone();
    runCard.classList.remove("is-error");
    runCard.classList.add("is-success");
    progressFill.style.width = "100%";
    runTitle.textContent = "Done";
    runSub.textContent = `Open ${job.output_path}\\\\splat\\\\scene.ply in Blender`;
    submitBtn.disabled = false;
    submitBtn.textContent = "Create another";
    return;
  }
  if (job.status === "failed") {
    if (stage) setStep(stage, "error");
    runCard.classList.add("is-error");
    runTitle.textContent = "Failed";
    runSub.textContent = extractFailureReason(job.log) || "Something went wrong. Open the detailed log below.";
    submitBtn.disabled = false;
    submitBtn.textContent = "Try again";
    return;
  }

  // running
  if (stage) {
    advanceTo(stage);
    runTitle.textContent = STEP_LABELS[stage];
    runSub.textContent = lastLine || "Working...";
    const idx = STEP_ORDER.indexOf(stage);
    progressFill.style.width = ((idx + 0.5) / STEP_ORDER.length * 100) + "%";
  }
}

function detectStage(log) {
  let stage = "upload";
  for (const line of log) {
    if (line.includes("[Extract frames]")) stage = "frames";
    else if (line.includes("[COLMAP feature extraction]")) stage = "features";
    else if (line.includes("matching]")) stage = "match";
    else if (line.includes("reconstruction") && line.startsWith("[")) stage = "reconstruct";
    else if (line.includes("[Prepare backend dataset]")) stage = "reconstruct";
    else if (line.includes("Gaussian splat training]")) stage = "splat";
  }
  return stage;
}

function lastMeaningfulLine(log) {
  for (let i = log.length - 1; i >= 0; i--) {
    const l = log[i].trim();
    if (!l) continue;
    if (l.startsWith("Command:") || l.startsWith("Uploaded ") || l === "Starting SplatfastK1 pipeline.") continue;
    return l.length > 110 ? l.slice(0, 107) + "..." : l;
  }
  return "";
}

function extractFailureReason(log) {
  for (let i = log.length - 1; i >= 0; i--) {
    if (log[i].startsWith("Pipeline failed:")) return log[i].replace("Pipeline failed:", "").trim();
  }
  return null;
}

function setStep(name, state) {
  const li = stepList.querySelector(`[data-step="${name}"]`);
  if (!li) return;
  li.classList.remove("done", "active", "error");
  if (state) li.classList.add(state);
}

function advanceTo(stage) {
  const idx = STEP_ORDER.indexOf(stage);
  STEP_ORDER.forEach((s, i) => {
    if (i < idx) setStep(s, "done");
    else if (i === idx) setStep(s, "active");
    else setStep(s, null);
  });
}

function setAllStepsDone() {
  STEP_ORDER.forEach(s => setStep(s, "done"));
}

function showRunCard() {
  runCard.classList.remove("hidden", "is-success", "is-error");
  STEP_ORDER.forEach(s => setStep(s, null));
  progressFill.style.width = "0%";
  logOutput.textContent = "";
}

function showError(msg) {
  runCard.classList.add("is-error");
  runTitle.textContent = "Failed";
  runSub.textContent = msg;
  submitBtn.disabled = false;
  submitBtn.textContent = "Try again";
  stopTicker();
}

function startTicker() {
  jobStartedAt = Date.now();
  if (tickTimer) clearInterval(tickTimer);
  tickTimer = setInterval(updateElapsed, 250);
  updateElapsed();
}
function stopTicker() {
  if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
  updateElapsed();
}
function updateElapsed() {
  if (!jobStartedAt) { elapsedTime.textContent = "00:00"; return; }
  const secs = Math.max(0, Math.floor((Date.now() - jobStartedAt) / 1000));
  const m = String(Math.floor(secs / 60)).padStart(2, "0");
  const s = String(secs % 60).padStart(2, "0");
  elapsedTime.textContent = `${m}:${s}`;
}

async function loadDoctor() {
  try {
    const response = await fetch("/api/doctor");
    const tools = await response.json();
    const required = tools.filter(t => t.required);
    const missing = required.filter(t => !t.found);
    if (missing.length === 0) {
      toolBadge.className = "badge badge-ok";
      toolBadge.textContent = "Tools ready";
    } else {
      toolBadge.className = "badge badge-bad";
      toolBadge.textContent = `Missing: ${missing.map(t => t.name).join(", ")}`;
    }
    doctorStatus.innerHTML = tools.map(t => `
      <div class="diag-item">
        <span class="k">${t.name}${t.required ? "" : " (optional)"}</span>
        <span class="v ${t.found ? "ok" : (t.required ? "bad" : "")}">${t.found ? "OK" : "Missing"}</span>
      </div>
    `).join("");
  } catch (e) {
    toolBadge.className = "badge badge-bad";
    toolBadge.textContent = "Tool check failed";
  }
}

async function loadHardware() {
  try {
    const response = await fetch("/api/hardware");
    const h = await response.json();
    hardwareStatus.innerHTML = `
      <div class="diag-item"><span class="k">Tier</span><span class="v">${h.tier}</span></div>
      <div class="diag-item"><span class="k">CPU</span><span class="v">${h.cpu || "?"}</span></div>
      <div class="diag-item"><span class="k">RAM</span><span class="v">${h.ram_gb ?? "?"} GB</span></div>
      <div class="diag-item"><span class="k">GPU</span><span class="v">${h.gpu || "?"}</span></div>
      <div class="diag-item"><span class="k">VRAM</span><span class="v">${h.vram_gb ?? "?"} GB</span></div>
      <div class="diag-item"><span class="k">Free disk</span><span class="v">${h.free_disk_gb} GB</span></div>
    `;
  } catch (e) {
    hardwareStatus.textContent = "Hardware check failed";
  }
}
"""
