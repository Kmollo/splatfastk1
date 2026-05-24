bl_info = {
    "name": "SplatfastK1",
    "author": "SplatfastK1 Contributors",
    "version": (0, 2, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > SplatfastK1",
    "description": "Turn a video into a Blender-ready Gaussian splat with one click",
    "category": "3D View",
}

import os
import shutil
import subprocess
import threading
from pathlib import Path

import bpy
from bpy.props import EnumProperty, StringProperty

# ---------------------------------------------------------------------------
# Progress step mapping: substring in CLI stdout → (friendly label, percent)
# ---------------------------------------------------------------------------
_STEP_MAP = [
    ("Extract frames",            "Extracting frames from video",  10),
    ("COLMAP feature extraction", "Analyzing image features",      25),
    ("matching",                  "Matching camera positions",     45),
    ("reconstruction",            "Reconstructing 3D scene",       65),
    ("Prepare backend",           "Preparing splat training",      75),
    ("Brush",                     "Training Gaussian splat",       85),
    ("SplatfastK1 project ready",  "Complete!",                    100),
]

# ---------------------------------------------------------------------------
# Module-level job state
# Updated from background thread, read by modal timer and panel draw.
# ---------------------------------------------------------------------------
_job = {
    "running":     False,
    "status":      "idle",   # idle | running | done | failed
    "step":        "",
    "progress":    0,
    "error":       "",
    "output_path": "",
}
_job_lock = threading.Lock()


def _update_job(**kwargs):
    with _job_lock:
        _job.update(kwargs)


def _get_job():
    with _job_lock:
        return dict(_job)


# ---------------------------------------------------------------------------
# Background worker — called in a daemon thread from the operator
# ---------------------------------------------------------------------------
def _run_pipeline(command: list, output_path: str) -> None:
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
        )

        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue

            # Map CLI output lines to user-friendly progress steps
            for keyword, label, pct in _STEP_MAP:
                if keyword.lower() in line.lower():
                    _update_job(step=label, progress=pct)
                    break

            # CLI prints "Pipeline failed: <reason>" on RuntimeError
            if line.startswith("Pipeline failed:"):
                _update_job(error=line[len("Pipeline failed:"):].strip())

        proc.wait()

        if proc.returncode == 0:
            _update_job(status="done", step="Complete!", progress=100,
                        output_path=output_path)
        else:
            if not _get_job()["error"]:
                _update_job(error=f"Pipeline exited with code {proc.returncode}.")
            _update_job(status="failed", step="Failed")

    except Exception as exc:
        _update_job(status="failed", step="Failed", error=str(exc))
    finally:
        _update_job(running=False)


# ---------------------------------------------------------------------------
# Operator: Create Splat
# ---------------------------------------------------------------------------
class SPLATFORGE_OT_create(bpy.types.Operator):
    bl_idname = "splatforge.create"
    bl_label = "Create Splat"
    bl_description = (
        "Extract frames, run COLMAP reconstruction, and train a Gaussian splat"
    )

    _timer = None

    def execute(self, context):
        props = context.scene.splatforge

        video_path = Path(bpy.path.abspath(props.video_path))
        if not video_path.exists():
            self.report({"ERROR"}, "Video file not found — check the path.")
            return {"CANCELLED"}

        cli = shutil.which("splatforge")
        if cli is None:
            self.report(
                {"ERROR"},
                "splatforge command not found. Run: pip install -e . in the project folder.",
            )
            return {"CANCELLED"}

        output_path = Path.home() / "SplatfastK1" / video_path.stem
        output_path.mkdir(parents=True, exist_ok=True)

        command = [
            cli, "create", str(video_path),
            "--quality", props.quality,
            "--matcher", "sequential",
            "--backend", "brush",
            "--output", str(output_path),
        ]

        _update_job(
            running=True,
            status="running",
            step="Starting...",
            progress=5,
            error="",
            output_path="",
        )

        thread = threading.Thread(
            target=_run_pipeline,
            args=(command, str(output_path)),
            daemon=True,
        )
        thread.start()

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        # Redraw the sidebar panel
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()

        job = _get_job()
        if not job["running"] and job["status"] in ("done", "failed"):
            self._finish(context)
            if job["status"] == "done":
                self.report({"INFO"}, "SplatfastK1: splat created successfully!")
            else:
                self.report({"ERROR"}, f"SplatfastK1 failed: {job['error']}")
            return {"FINISHED"}

        return {"PASS_THROUGH"}

    def _finish(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

    def cancel(self, context):
        self._finish(context)


# ---------------------------------------------------------------------------
# Operator: Open output folder in Explorer
# ---------------------------------------------------------------------------
class SPLATFORGE_OT_open_output(bpy.types.Operator):
    bl_idname = "splatforge.open_output"
    bl_label = "Open Output Folder"
    bl_description = "Open the output folder in File Explorer"

    def execute(self, context):
        output = _get_job().get("output_path", "")
        if not output or not Path(output).exists():
            self.report({"WARNING"}, "Output folder not found.")
            return {"CANCELLED"}
        os.startfile(output)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Properties stored on bpy.types.Scene
# ---------------------------------------------------------------------------
class SplatfastK1Properties(bpy.types.PropertyGroup):
    video_path: StringProperty(
        name="Video",
        description="Path to your input video (.mp4, .mov, .avi, ...)",
        subtype="FILE_PATH",
    )
    quality: EnumProperty(
        name="Quality",
        description="Trade off processing speed against splat quality",
        items=[
            ("fast",     "Fast",
             "1 frame/sec, smaller images — done in minutes"),
            ("balanced", "Balanced",
             "2 frames/sec, medium images — good for most videos"),
            ("high",     "High",
             "4 frames/sec, large images — best quality, takes longer"),
        ],
        default="fast",
    )


# ---------------------------------------------------------------------------
# Panel: View3D > Sidebar > SplatfastK1
# ---------------------------------------------------------------------------
class SPLATFORGE_PT_main(bpy.types.Panel):
    bl_label = "SplatfastK1"
    bl_idname = "SPLATFORGE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SplatfastK1"

    def draw(self, context):
        layout = self.layout
        props = context.scene.splatforge
        job = _get_job()
        status = job["status"]

        # ---- Input section ----
        box = layout.box()
        box.label(text="Your Video", icon="FILE_MOVIE")
        box.prop(props, "video_path", text="")
        box.label(
            text="Tip: walk around your subject — don't pan flat.",
            icon="INFO",
        )

        layout.separator()

        # ---- Quality section ----
        box = layout.box()
        box.label(text="Quality", icon="SETTINGS")
        box.prop(props, "quality", text="")

        layout.separator()

        # ---- Action / status section ----
        if status == "running":
            col = layout.column(align=True)
            col.label(text=job["step"], icon="TIME")
            col.label(text=f"{job['progress']}% complete")

        elif status == "done":
            layout.label(text="Splat is ready!", icon="CHECKMARK")
            layout.operator("splatforge.open_output", icon="FOLDER_REDIRECT")
            layout.separator()
            layout.label(text="To view in Blender:", icon="INFO")
            layout.label(text="File > Import > SplatfastK1 Project")

        elif status == "failed":
            col = layout.column(align=True)
            col.label(text="Something went wrong:", icon="ERROR")
            for line in _wrap(job["error"], 38):
                col.label(text=line)
            layout.separator()
            layout.operator(
                "splatforge.create", text="Try Again", icon="FILE_REFRESH"
            )

        else:
            # idle
            row = layout.row()
            row.scale_y = 1.6
            row.operator("splatforge.create", icon="PLAY", text="Create Splat")


def _wrap(text: str, width: int) -> list:
    words = text.split()
    lines, current = [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            if current:
                lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    if current:
        lines.append(current)
    return lines or ["(unknown error)"]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
_classes = (
    SplatfastK1Properties,
    SPLATFORGE_OT_create,
    SPLATFORGE_OT_open_output,
    SPLATFORGE_PT_main,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.splatforge = bpy.props.PointerProperty(type=SplatfastK1Properties)


def unregister():
    del bpy.types.Scene.splatforge
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
