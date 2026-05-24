"""CloudPipelineWorker — runs frames+COLMAP locally, then trains on Replicate.

Stages (same keys as the local worker so the UI can reuse its step list):

    upload       -> Preparing
    frames       -> Extracting frames (FFmpeg)
    features     -> Finding features (COLMAP)
    match        -> Matching frames (COLMAP)
    reconstruct  -> Building 3D model (COLMAP mapper)
    splat        -> Training splat in the cloud (Replicate)

The cloud_train + download both happen inside the "splat" stage so the
visible step list is identical between local and cloud modes.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from desktop import config
from desktop.cloud import (
    DEFAULT_MODEL,
    ReplicateError,
    cancel_prediction,
    download_output,
    get_latest_version_id,
    poll_prediction,
    submit_prediction,
    upload_file,
)
from desktop.widgets.pipeline_worker import _kill_process_tree


SPLATFORGE_ROOT = Path(__file__).resolve().parents[2]


# Map a stdout-line keyword from `splatforge create` to (stage_key, friendly, percent)
LOCAL_STAGE_MAP = [
    ("[Extract frames]",            "frames",       "Extracting frames",       15),
    ("[COLMAP feature extraction]", "features",     "Finding features",        30),
    ("matching]",                   "match",        "Matching frames",         50),
    ("[COLMAP reconstruction",      "reconstruct",  "Building 3D model",       70),
    ("[GLOMAP reconstruction",      "reconstruct",  "Building 3D model",       70),
    ("[Prepare backend dataset]",   "reconstruct",  "Preparing dataset",       72),
]


class CloudPipelineWorker(QThread):
    """Drives the cloud training flow on a background thread."""

    # Same signal shapes as the local worker so project_view can route to either
    stage_changed = pyqtSignal(str, str, int)
    elapsed_changed = pyqtSignal(int)
    log_line = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    finished_error = pyqtSignal(str)

    def __init__(
        self,
        video: Path,
        output_dir: Path,
        quality: str,
        total_steps: int,
        model: str = DEFAULT_MODEL,
    ) -> None:
        super().__init__()
        self.video = video
        self.output_dir = output_dir
        self.quality = quality
        self.total_steps = total_steps
        self.model = model
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._started_at: float = 0.0
        # We track the Replicate prediction ID + token so cancel() can call
        # the Replicate cancel API and actually stop billing. Without this,
        # cancel only stopped us POLLING — the GPU on Replicate kept running.
        self._prediction_id: Optional[str] = None
        self._token_for_cancel: str = ""

    # Match common Brush step-progress lines:
    #   step 5000/15000     5000 / 15000      step 5000 of 15000
    _STEP_PATTERNS = [
        # cached at class init below
    ]

    @staticmethod
    def _parse_brush_step(line: str) -> Optional[tuple[int, int]]:
        import re
        m = re.search(r"step\s+(\d+)\s*[/of]+\s*(\d+)", line, re.IGNORECASE)
        if not m:
            m = re.search(r"(\d+)\s*/\s*(\d+)\s*(?:steps?|iters?)", line, re.IGNORECASE)
        if not m:
            # Bare "5000/15000" — only if it's the main number on the line
            m = re.search(r"\b(\d{2,6})\s*/\s*(\d{3,6})\b", line)
        if m:
            try:
                step, total = int(m.group(1)), int(m.group(2))
                if total >= step and total >= 100:
                    return step, total
            except ValueError:
                pass
        return None

    def cancel(self) -> None:
        """Cancel the cloud run — really cancel it.

        Two things to stop:
          1. The local COLMAP/FFmpeg subprocess tree (if still running).
          2. The prediction running on Replicate's GPU. Without this, the
             cloud GPU keeps grinding and keeps charging the user's account
             until natural completion — even though we stopped watching.
        """
        self._cancelled = True
        # 1. Kill the local prep subprocess tree (python.exe -> ffmpeg, colmap, ...)
        if self._proc is not None and self._proc.poll() is None:
            _kill_process_tree(self._proc)
        # 2. Tell Replicate to stop. Best-effort: don't crash cancel if the
        #    API call fails (e.g. no network) — we still want the local UI
        #    to go back to the home screen.
        if self._prediction_id and self._token_for_cancel:
            try:
                cancel_prediction(self._token_for_cancel, self._prediction_id)
            except Exception:
                pass

    # ----- Helpers -----

    def _tick(self) -> int:
        return int(time.time() - self._started_at)

    def _emit_stage(self, key: str, friendly: str, percent: int) -> None:
        self.stage_changed.emit(key, friendly, percent)

    def _check_cancel(self) -> None:
        if self._cancelled:
            raise ReplicateError("Cancelled by user.")

    # ----- Main flow -----

    def run(self) -> None:  # noqa: D401
        self._started_at = time.time()
        self.elapsed_changed.emit(0)
        self._emit_stage("upload", "Preparing", 3)

        token = config.get_replicate_token() or ""
        if not token:
            self.finished_error.emit(
                "No Replicate API key saved. Open Settings to add one."
            )
            return

        try:
            # 1. Run local FFmpeg + COLMAP via the existing CLI with backend=none.
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._run_local_colmap()
            self._check_cancel()

            # Write a sentinel so the Projects view knows this run is in its
            # CLOUD-ACTIVE phase. Without it, Projects would see "PIPELINE_END:
            # complete" in pipeline.log (from the local --backend=none CLI) and
            # mislabel the run as "Failed" — even though Replicate is still
            # training. Removed in the finally block below.
            cloud_marker = self.output_dir / ".cloud_active"
            try:
                cloud_marker.parent.mkdir(parents=True, exist_ok=True)
                cloud_marker.write_text(
                    f"Cloud phase started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
                    encoding="utf-8",
                )
            except Exception:
                pass  # non-fatal

            # 2. Zip the COLMAP dataset (images/ + sparse/).
            self._emit_stage("reconstruct", "Packaging for upload", 75)
            zip_path = self._zip_dataset()
            self._check_cancel()

            # 3. Look up the latest model version.
            self.log_line.emit(f"Looking up latest version of {self.model}...")
            version_id = get_latest_version_id(token, self.model)
            self.log_line.emit(f"Version: {version_id}")
            self._check_cancel()

            # 4. Upload zip to Replicate.
            self._emit_stage("splat", "Uploading dataset to cloud", 80)
            self.log_line.emit(f"Uploading {zip_path.stat().st_size // 1024} KB...")
            file_url = upload_file(token, zip_path)
            self.log_line.emit(f"Upload URL: {file_url}")
            self._check_cancel()

            # 5. Submit prediction.
            self._emit_stage("splat", "Starting cloud training", 82)
            prediction = submit_prediction(
                token,
                version_id,
                {"colmap_zip": file_url, "total_steps": self.total_steps},
            )
            pred_id = prediction.get("id", "")
            self.log_line.emit(f"Prediction ID: {pred_id}")
            # Remember these so cancel() can hit the Replicate cancel API
            # and actually stop the GPU bill clock running on their side.
            self._prediction_id = pred_id
            self._token_for_cancel = token
            self._check_cancel()

            # 6. Poll until done.
            def on_status(s: str) -> None:
                friendly = {
                    "starting": "Cloud GPU starting",
                    "processing": "Training splat on cloud GPU",
                }.get(s, f"Status: {s}")
                pct = {"starting": 84, "processing": 88}.get(s, 90)
                self.log_line.emit(f"  -> {s}")
                self._emit_stage("splat", friendly, pct)
                self.elapsed_changed.emit(self._tick())

            def on_log(line: str) -> None:
                self.log_line.emit(f"  [cloud] {line}")
                # Try to extract Brush step progress: "step 5000/15000" or "5000/15000"
                step_info = self._parse_brush_step(line)
                if step_info is not None:
                    step, total_steps = step_info
                    if total_steps > 0:
                        # Map step progress into the 85-95% range visually
                        sub_pct = min(95, 85 + int(10 * step / total_steps))
                        self._emit_stage(
                            "splat",
                            f"Training splat ({step}/{total_steps} steps)",
                            sub_pct,
                        )
                        self.elapsed_changed.emit(self._tick())

            def is_cancelled() -> bool:
                return self._cancelled

            final = poll_prediction(
                token,
                pred_id,
                on_status=on_status,
                on_log=on_log,
                cancel=is_cancelled,
            )

            output = final.get("output")
            if isinstance(output, list):
                output_url = output[0] if output else ""
            else:
                output_url = str(output or "")
            if not output_url:
                raise ReplicateError("Prediction succeeded but returned no output URL.")

            # 7. Download scene.ply.
            self._emit_stage("splat", "Downloading splat", 95)
            ply_dest = self.output_dir / "splat" / "scene.ply"
            download_output(output_url, ply_dest)
            self.log_line.emit(f"scene.ply saved: {ply_dest} ({ply_dest.stat().st_size // 1024 // 1024} MB)")

            self.finished_ok.emit(str(ply_dest))
        except ReplicateError as e:
            self.finished_error.emit(str(e))
        except Exception as e:
            self.finished_error.emit(f"Unexpected error: {e}")
        finally:
            # Whatever happened (success, error, cancel), the cloud phase is over.
            # Remove the marker so Projects view no longer says "In progress".
            try:
                marker = self.output_dir / ".cloud_active"
                if marker.exists():
                    marker.unlink()
            except Exception:
                pass

    # ----- Step 1: local FFmpeg + COLMAP -----

    def _run_local_colmap(self) -> None:
        cmd = [
            sys.executable,
            "-u",
            "-m",
            "splatforge.cli",
            "create",
            str(self.video),
            "--output",
            str(self.output_dir),
            "--quality",
            self.quality,
            "--backend",
            "none",
        ]
        self.log_line.emit("Local prep: " + " ".join(cmd))
        # CREATE_NO_WINDOW (Windows only) prevents the splatforge.cli subprocess
        # from opening a visible console window when our app runs under pythonw.exe.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(SPLATFORGE_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        assert self._proc.stdout is not None

        last_tick = 0
        for raw in self._proc.stdout:
            if self._cancelled:
                break
            line = raw.rstrip()
            if line:
                self.log_line.emit(line)
                self._maybe_emit_local_stage(line)
            now = self._tick()
            if now != last_tick:
                last_tick = now
                self.elapsed_changed.emit(now)

        rc = self._proc.wait()
        if rc != 0:
            raise ReplicateError(f"Local frame extraction + COLMAP failed (exit {rc}).")

    def _maybe_emit_local_stage(self, line: str) -> None:
        lower = line.lower()
        for needle, key, friendly, pct in LOCAL_STAGE_MAP:
            if needle.lower() in lower:
                self._emit_stage(key, friendly, pct)
                return

    # ----- Step 2: zip the dataset -----

    def _zip_dataset(self) -> Path:
        """Pack output_dir/images and the COLMAP sparse output into a zip."""
        images_dir = self.output_dir / "images"
        # The canonical COLMAP output is reconstruction/sparse. The top-level
        # sparse/ folder is a placeholder that the CLI only fills in when a
        # backend (like Brush) runs. With --backend=none we have to use the
        # reconstruction/sparse path.
        recon_sparse = self.output_dir / "reconstruction" / "sparse"
        top_sparse = self.output_dir / "sparse"
        if recon_sparse.exists() and any(recon_sparse.rglob("*.bin")):
            sparse_dir = recon_sparse
        elif top_sparse.exists() and any(top_sparse.rglob("*.bin")):
            sparse_dir = top_sparse
        else:
            raise ReplicateError(
                f"Could not find a populated sparse/ folder at {recon_sparse} or {top_sparse}"
            )
        if not images_dir.exists():
            raise ReplicateError(f"Expected images/ folder missing at {images_dir}")

        zip_path = Path(tempfile.gettempdir()) / f"splatfastk1_dataset_{int(time.time())}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as zf:
            # IMPORTANT: arcnames must use forward slashes — backslashes get
            # written literally on Linux, breaking the predict.py folder lookup.
            for file in images_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, arcname=f"images/{file.relative_to(images_dir).as_posix()}")
            for file in sparse_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, arcname=f"sparse/{file.relative_to(sparse_dir).as_posix()}")
        size_mb = zip_path.stat().st_size / 1024 / 1024
        self.log_line.emit(f"Built dataset zip: {zip_path.name} ({size_mb:.1f} MB)")
        return zip_path
