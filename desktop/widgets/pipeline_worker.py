"""SplatfastK1 Desktop — background worker that runs the local pipeline.

Spawns `python -u -m splatforge.cli create ...` as a subprocess, parses its
stdout for stage markers, emits progress signals back to the UI.

Also includes two free functions for launching the result viewers:
  * launch_brush_viewer(ply_path)        — opens Brush in --with-viewer mode
  * launch_blender_with_splat(ply_path)  — opens Blender with auto-import script
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal


# Map a stdout-line keyword to (stage_key, friendly label, percent)
STAGE_MAP = [
    ("[Extract frames]",            "frames",       "Extracting frames",       15),
    ("[COLMAP feature extraction]", "features",     "Finding features",        30),
    ("matching]",                   "match",        "Matching frames",         50),
    ("[COLMAP reconstruction",      "reconstruct",  "Building 3D model",       70),
    ("[GLOMAP reconstruction",      "reconstruct",  "Building 3D model",       70),
    ("[Prepare backend dataset]",   "reconstruct",  "Preparing splat dataset", 80),
    ("Gaussian splat training]",    "splat",        "Training splat",          90),
]


SPLATFORGE_ROOT = Path(__file__).resolve().parents[2]



def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill a subprocess AND every descendant it spawned.

    The naive proc.terminate() only signals the immediate child. On Windows,
    when we launch `python -m splatforge.cli`, that Python process then spawns
    grandchildren (ffmpeg, COLMAP, Brush, etc.) — those are NOT killed by
    terminating the parent. They get orphaned and keep eating GPU/CPU.

    On Windows we use `taskkill /T /F /PID <pid>` which kills the whole tree.
    On other platforms we fall back to proc.kill() (best effort).
    """
    if proc is None or proc.poll() is not None:
        return
    pid = proc.pid
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=10,
            )
        else:
            proc.kill()
    except Exception:
        # Last-ditch fallback
        try:
            proc.kill()
        except Exception:
            pass


class PipelineWorker(QThread):
    """Runs the SplatfastK1 CLI in a background thread, streams stdout, emits signals."""

    stage_changed = pyqtSignal(str, str, int)   # stage_key, friendly, percent
    elapsed_changed = pyqtSignal(int)            # seconds since start
    log_line = pyqtSignal(str)
    finished_ok = pyqtSignal(str)                # path to scene.ply
    finished_error = pyqtSignal(str)             # error message

    def __init__(
        self,
        video: Path,
        output_dir: Path,
        quality: str,
        total_steps: int,
    ) -> None:
        super().__init__()
        self.video = video
        self.output_dir = output_dir
        self.quality = quality
        self.total_steps = total_steps
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc is not None and self._proc.poll() is None:
            _kill_process_tree(self._proc)

    def run(self) -> None:  # noqa: D401
        started = time.time()
        # Tell the UI we're in "upload" stage immediately
        self.stage_changed.emit("upload", "Preparing", 5)

        self.output_dir.mkdir(parents=True, exist_ok=True)

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
        ]
        self.log_line.emit("Command: " + " ".join(cmd))

        # CREATE_NO_WINDOW (Windows only) hides the console window that would
        # otherwise pop up when our pythonw.exe app launches a python.exe child.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(SPLATFORGE_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creationflags,
            )
        except Exception as e:
            self.finished_error.emit(f"Could not start pipeline: {e}")
            return

        # Background ticker for elapsed time
        last_tick = int(time.time() - started)
        self.elapsed_changed.emit(last_tick)

        assert self._proc.stdout is not None
        for raw in self._proc.stdout:
            if self._cancelled:
                break
            line = raw.rstrip()
            if line:
                self.log_line.emit(line)
                self._maybe_emit_stage(line)
            # Update elapsed roughly every second
            now = int(time.time() - started)
            if now != last_tick:
                last_tick = now
                self.elapsed_changed.emit(now)

        rc = self._proc.wait() if self._proc else 1

        if self._cancelled:
            self.finished_error.emit("Cancelled.")
            return

        if rc == 0:
            ply = self.output_dir / "splat" / "scene.ply"
            if ply.exists():
                self.finished_ok.emit(str(ply))
            else:
                self.finished_error.emit(
                    f"Pipeline exited cleanly but {ply} was not produced."
                )
        else:
            # Pull the most recent "Pipeline failed:" line from the log if present
            self.finished_error.emit(f"Pipeline exited with code {rc}.")

    def _maybe_emit_stage(self, line: str) -> None:
        lower = line.lower()
        for needle, key, friendly, pct in STAGE_MAP:
            if needle.lower() in lower:
                self.stage_changed.emit(key, friendly, pct)
                return


# ---------------------------------------------------------------------------
# Result launchers
# ---------------------------------------------------------------------------

def launch_brush_viewer(ply_path: Path) -> None:
    """Launch Brush in viewer mode on the given .ply."""
    if not ply_path.exists():
        return
    brush_exe = SPLATFORGE_ROOT / "references" / "skysplat_blender" / "binaries" / "brush_app_windows.exe"
    if not brush_exe.exists():
        return
    # CREATE_NO_WINDOW hides the console flash on Windows when launched from pythonw.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [str(brush_exe), str(ply_path), "--with-viewer"],
        cwd=str(SPLATFORGE_ROOT),
        creationflags=creationflags,
    )


def launch_blender_with_splat(ply_path: Path) -> None:
    """Launch Blender 5.1 and run an auto-import script that wires the splat through BlendSplat.

    Looks for blender.exe in common install locations on Windows. Falls back to PATH.
    """
    if not ply_path.exists():
        return

    candidates = [
        Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"),
    ]
    blender_exe = next((p for p in candidates if p.exists()), None)
    if blender_exe is None:
        which = shutil.which("blender")
        if which:
            blender_exe = Path(which)
    if blender_exe is None:
        return

    # Write a one-shot startup script that imports the splat through BlendSplat.
    # We embed paths via repr() rather than raw-string concatenation: repr() guarantees
    # a valid quoted Python literal even if the path contains quotes, backslashes, or
    # other characters that could otherwise break the template (or be used to inject
    # Python code through a maliciously crafted path).
    blendsplat_lib = Path(os.environ.get("USERPROFILE", "")) / "Documents" / "BlendSplat-Library"

    script = SPLATFORGE_ROOT / "outputs" / "_blender_autoimport.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(_AUTOIMPORT_TEMPLATE.format(
        ply_path_literal=repr(str(ply_path)),
        blendsplat_lib_literal=repr(str(blendsplat_lib)),
    ), encoding="utf-8")

    # CREATE_NO_WINDOW hides the brief console flash on Windows when launched
    # from pythonw. Without this the user briefly sees a black box appear.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [str(blender_exe), "--online-mode", "--python", str(script)],
        creationflags=creationflags,
    )


_AUTOIMPORT_TEMPLATE = '''"""Auto-import a SplatfastK1 Gaussian splat into Blender.

Strategy (best-first):
  1. BlendSplat library (~/Documents/BlendSplat-Library/) — preferred. Wires
     splat.import -> splat.display(splat.shader) and gives the dense, filled
     Gaussian look that matches what Brush's own viewer shows.
  2. Kiri Engine "3DGS Render" Blender addon, if installed — same idea but
     using Kiri's geometry-nodes setup.
  3. Last resort: plain wm.ply_import. Renders the splat as raw vertex points
     (a streaky point cloud, NOT proper Gaussians). Visible-but-ugly fallback
     so the user still gets something rather than a black screen.

Also: reads COLMAP cameras.bin + images.bin from <project>/reconstruction/sparse/0/
to place the Blender camera at the first training-frame pose. This matches
the default view Brush opens to.

Works on Blender 5.1 (BLENDER_EEVEE engine identifier) and 4.x
(BLENDER_EEVEE_NEXT) — picks whichever exists at runtime.
"""
import bpy
import os
import math
import struct
import mathutils
import addon_utils

# Paths are embedded via repr() from the parent process, so {ply_path_literal}
# is already a complete, safely-quoted Python string literal — no injection risk
# even if the path contains quotes, backslashes, or unicode.
PLY_PATH = {ply_path_literal}
BLENDSPLAT_LIB = {blendsplat_lib_literal}


# ---------- COLMAP first-camera pose (Brush-matching view) ----------

# Number of params per COLMAP camera model_id (from src/colmap/scene/camera_models.h)
_COLMAP_PARAMS_BY_MODEL = {{
    0: 3,  1: 4,  2: 4,  3: 5,  4: 8,  5: 8,
    6: 12, 7: 5,  8: 4,  9: 5, 10: 12,
}}


def _read_colmap_first_image(images_bin):
    """Parse the first image entry from a COLMAP images.bin.
    Returns ((qw,qx,qy,qz), (tx,ty,tz), camera_id) or None.
    """
    try:
        with open(images_bin, "rb") as f:
            num_reg = struct.unpack("<Q", f.read(8))[0]
            if num_reg == 0:
                return None
            _image_id = struct.unpack("<I", f.read(4))[0]
            qw, qx, qy, qz = struct.unpack("<dddd", f.read(32))
            tx, ty, tz = struct.unpack("<ddd", f.read(24))
            camera_id = struct.unpack("<I", f.read(4))[0]
            return (qw, qx, qy, qz), (tx, ty, tz), camera_id
    except Exception as e:
        print("[splatforge] images.bin parse failed:", e)
        return None


def _read_colmap_camera(cameras_bin, camera_id):
    """Find the camera_id record in cameras.bin and return (focal_px, width, height) or None."""
    try:
        with open(cameras_bin, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            for _ in range(n):
                cam_id    = struct.unpack("<I", f.read(4))[0]
                model_id  = struct.unpack("<I", f.read(4))[0]
                width     = struct.unpack("<Q", f.read(8))[0]
                height    = struct.unpack("<Q", f.read(8))[0]
                npar = _COLMAP_PARAMS_BY_MODEL.get(model_id, 4)
                params = struct.unpack("<" + "d" * npar, f.read(8 * npar))
                if cam_id == camera_id:
                    return float(params[0]), int(width), int(height)
        return None
    except Exception as e:
        print("[splatforge] cameras.bin parse failed:", e)
        return None


def _apply_colmap_pose(cam_obj, quat, tvec, focal_px, width_px):
    """Convert COLMAP world-to-camera (qvec, tvec) -> Blender camera transform.

    COLMAP: cameras look down +Z, +Y is down. Blender: cameras look down -Z, +Y is up.
    Pose conversion:
        cam_center_world = -R^T @ t
        cam_rot_world    = R^T @ diag(1, -1, -1)   # flip Y and Z to swap axis convention
    """
    q = mathutils.Quaternion((quat[0], quat[1], quat[2], quat[3]))  # (w,x,y,z) — same order as COLMAP
    R = q.to_matrix()
    t = mathutils.Vector(tvec)
    cam_center = -1 * (R.transposed() @ t)
    flip = mathutils.Matrix((( 1.0, 0.0,  0.0),
                             ( 0.0,-1.0,  0.0),
                             ( 0.0, 0.0, -1.0)))
    R_blender = R.transposed() @ flip
    cam_obj.location = cam_center
    cam_obj.rotation_mode = "XYZ"
    cam_obj.rotation_euler = R_blender.to_euler("XYZ")
    if focal_px and width_px:
        # Use a 36mm sensor as the reference, lens_mm = focal_px * 36 / width_px
        cam_obj.data.sensor_fit = "HORIZONTAL"
        cam_obj.data.sensor_width = 36.0
        cam_obj.data.lens = focal_px * 36.0 / width_px


def _try_colmap_camera(cam_obj):
    """Place cam_obj at the first COLMAP training-image pose. Returns True on success."""
    project_dir = os.path.dirname(os.path.dirname(PLY_PATH))  # <proj>/splat/ -> <proj>
    sparse_dir = os.path.join(project_dir, "reconstruction", "sparse", "0")
    images_bin = os.path.join(sparse_dir, "images.bin")
    cameras_bin = os.path.join(sparse_dir, "cameras.bin")
    if not (os.path.exists(images_bin) and os.path.exists(cameras_bin)):
        print("[splatforge] no COLMAP recon at", sparse_dir, "-- falling back to bbox frame")
        return False
    first = _read_colmap_first_image(images_bin)
    if not first:
        return False
    quat, tvec, camera_id = first
    cam_info = _read_colmap_camera(cameras_bin, camera_id)
    if cam_info is None:
        focal_px, width_px = None, None
    else:
        focal_px, width_px, _h = cam_info
    _apply_colmap_pose(cam_obj, quat, tvec, focal_px, width_px)
    print(f"[splatforge] camera placed at COLMAP frame 1 pose: t=({{tvec[0]:.2f}}, {{tvec[1]:.2f}}, {{tvec[2]:.2f}}) focal={{focal_px}}")
    return True


def _ensure_addon(mod_name):
    """Enable the addon if it's installed but not enabled. Returns True if usable."""
    try:
        loaded_default, loaded_state = addon_utils.check(mod_name)
        if not loaded_state:
            addon_utils.enable(mod_name, default_set=True, persistent=True)
        return True
    except Exception as e:
        print("[splatforge] could not enable addon", mod_name, ":", e)
        return False


def _frame_camera(target_obj):
    """Place a camera framing target_obj AND lock the user view so orbit / pan
    keeps the splat in sight.

    Three things together solve the 'splat disappears when I move' problem:
      1. The splat object is selected + active  -> Numpad-. (frame selected) works.
      2. The 3D cursor is moved to the splat center -> orbit pivots around splat.
      3. Viewport clip_start / clip_end are sized to the splat -> no near/far culling.
    """
    target_obj.update_tag()
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    ev = target_obj.evaluated_get(deps)
    bb = [ev.matrix_world @ mathutils.Vector(c) for c in ev.bound_box]
    if not bb:
        return
    bbm = mathutils.Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
    bbM = mathutils.Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
    center = (bbm + bbM) / 2
    size = max((bbM - bbm).length, 0.1)

    # --- Camera placement ---
    # 1st choice: use the actual first COLMAP training-camera pose so the view
    # matches what Brush shows on startup (same angle as the original first
    # video frame). Fall back to bbox-based smart-framing if COLMAP files are
    # missing or unreadable.
    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    # Clipping has to handle wide range of COLMAP scene scales (1 unit -> 1000s of units).
    cam.data.clip_start = max(0.001, size * 0.0005)
    cam.data.clip_end   = max(10000.0, size * 50)

    if not _try_colmap_camera(cam):
        # Fallback: bbox-based front-right-above
        cam.location = center + mathutils.Vector((1.0, -1.5, 0.6)).normalized() * (size * 1.3 / math.tan(cam.data.angle / 2) / 2)
        look = center - cam.location
        cam.rotation_mode = "XYZ"
        cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam

    # --- Make the splat the orbit pivot ---
    # 1. Move the 3D cursor to the splat center (orbit-around-cursor anchors here)
    bpy.context.scene.cursor.location = center
    # 2. Select + activate the splat so Numpad-. (view_selected) and middle-mouse
    #    orbit-around-active both target it.
    for o in bpy.context.scene.objects:
        o.select_set(False)
    target_obj.select_set(True)
    bpy.context.view_layer.objects.active = target_obj

    # --- Configure every 3D viewport in every open window ---
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            # Sync viewport clipping with camera clipping so the splat doesn't
            # disappear when you orbit out of camera view.
            space.clip_start = cam.data.clip_start
            space.clip_end   = cam.data.clip_end
            # Orbit around the active selection (this is the real "stay on splat" fix).
            try:
                bpy.context.preferences.inputs.view_rotate_method = "TURNTABLE"
            except Exception:
                pass
            for region in area.regions:
                if region.type == "WINDOW":
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        # Frame the splat (so even outside camera view, we start on it)
                        bpy.ops.view3d.view_selected(use_all_regions=False)
                        # Then switch to camera view (matches Brush's default).
                        bpy.ops.view3d.view_camera()
            space.shading.type = "RENDERED"


def try_kiri_dgs():
    """Use Kiri Engine 3DGS Render addon — the proper splat path."""
    candidates = ["dgs_render_by_kiri_engine", "bl_ext.user_default.dgs_render_by_kiri_engine"]
    enabled = False
    for name in candidates:
        if _ensure_addon(name):
            enabled = True
            break
    op = getattr(getattr(bpy.ops, "sna", None), "dgs_render_import_ply_e0a3a", None)
    if not enabled or op is None:
        print("[splatforge] Kiri 3DGS Render addon not available")
        return False
    try:
        op('EXEC_DEFAULT', filepath=PLY_PATH)
    except Exception as e:
        print("[splatforge] Kiri 3DGS import failed:", e)
        return False

    # Kiri sets the imported object active. Frame it.
    obj = bpy.context.view_layer.objects.active
    if obj is None:
        # Fallback: grab the last mesh
        meshes = [o for o in bpy.data.objects if o.type == "MESH"]
        obj = meshes[-1] if meshes else None
    if obj is not None:
        bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
        _frame_camera(obj)
    print("[splatforge] imported via Kiri 3DGS Render")
    return True


def try_blendsplat():
    """Fall back to wiring BlendSplat node groups manually."""
    if not os.path.isdir(BLENDSPLAT_LIB):
        return False
    if "splat.import" not in bpy.data.node_groups or "splat.display" not in bpy.data.node_groups:
        for fname in ("display.blend", "create.blend", "process.blend", "convert.blend", "utils.blend"):
            path = os.path.join(BLENDSPLAT_LIB, "core", fname)
            if not os.path.exists(path):
                continue
            try:
                with bpy.data.libraries.load(path, link=False) as (df, dt):
                    dt.node_groups = list(df.node_groups)
                    dt.materials = list(df.materials)
            except Exception as e:
                print("[splatforge] couldn't load", path, ":", e)

    import_ng = bpy.data.node_groups.get("splat.import")
    display_ng = bpy.data.node_groups.get("splat.display")
    shader_mat = bpy.data.materials.get("splat.shader")
    if not (import_ng and display_ng and shader_mat):
        print("[splatforge] BlendSplat node groups / shader not found")
        return False

    # CRITICAL: BlendSplat ships splat.shader with DITHERED stochastic alpha,
    # which causes the sparse / grainy "almost there" look. Switching to BLENDED
    # gives proper Gaussian alpha-compositing — i.e. the dense, "epic Brush" look.
    for attr, value in (("surface_render_method", "BLENDED"),  # Blender 4.2+
                        ("blend_method",          "BLEND")):    # legacy fallback
        if hasattr(shader_mat, attr):
            try:
                setattr(shader_mat, attr, value)
                print(f"[splatforge] splat.shader.{{attr}} -> {{value}}")
            except Exception as e:
                print(f"[splatforge] couldn't set {{attr}}: {{e}}")

    mesh = bpy.data.meshes.new("BlendSplat")
    obj = bpy.data.objects.new("BlendSplat", mesh)
    bpy.context.scene.collection.objects.link(obj)

    wrap = bpy.data.node_groups.new("BSChain", "GeometryNodeTree")
    wrap.is_modifier = True
    wrap.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    wrap.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    inp = wrap.nodes.new("NodeGroupInput"); inp.location = (-400, 0)
    out = wrap.nodes.new("NodeGroupOutput"); out.location = (600, 0)
    imp = wrap.nodes.new("GeometryNodeGroup"); imp.node_tree = import_ng; imp.location = (-150, 0)
    imp.inputs["Path"].default_value = PLY_PATH
    # The 'ply' Menu input picks the color-space treatment. Default 'srgb' matches Brush's export.
    if "ply" in imp.inputs:
        try:
            imp.inputs["ply"].default_value = "srgb"
        except Exception as e:
            print("[splatforge] couldn't set ply menu:", e)
    disp = wrap.nodes.new("GeometryNodeGroup"); disp.node_tree = display_ng; disp.location = (250, 0)
    disp.inputs["Material"].default_value = shader_mat
    wrap.links.new(imp.outputs["Splat"], disp.inputs["Splat"])
    wrap.links.new(disp.outputs["Splat"], out.inputs[0])

    mod = obj.modifiers.new("BlendSplat", type="NODES")
    mod.node_group = wrap

    # Force evaluation so the modifier actually runs before we frame the camera.
    obj.update_tag()
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    _ = obj.evaluated_get(deps)

    _frame_camera(obj)
    print("[splatforge] imported via BlendSplat: splat.import -> splat.display(splat.shader)")
    return True


def _set_render_engine():
    """Blender 5.1 uses BLENDER_EEVEE_NEXT; older releases use BLENDER_EEVEE."""
    scene = bpy.context.scene
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = eng
            print("[splatforge] render engine ->", eng)
            return
        except TypeError:
            continue


def _set_viewport_rendered():
    """Switch every 3D viewport in every window to RENDERED shading.

    Brush-like splats are alpha-compositions of thousands of soft Gaussians —
    they only look right with the shader actually running. Material Preview /
    Solid will show streaky points (which is what looked 'partial' before).
    """
    n = 0
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.type = "RENDERED"
                    n += 1
    print(f"[splatforge] viewport RENDERED applied to {{n}} space(s)")


def _set_dark_world():
    """Make the world background black so splats pop, like Brush's viewer."""
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        bg.inputs["Strength"].default_value = 0.0


def setup():
    # Clean default scene
    for n in ("Cube", "Light", "Camera"):
        o = bpy.data.objects.get(n)
        if o:
            bpy.data.objects.remove(o, do_unlink=True)

    _set_render_engine()
    _set_dark_world()

    # BlendSplat is the PRIMARY path — it ships the proper Gaussian-splat shader.
    if try_blendsplat():
        _set_viewport_rendered()
        # Re-apply after one more redraw tick in case the area wasn't ready yet
        bpy.app.timers.register(lambda: (_set_viewport_rendered(), None)[1], first_interval=1.5)
        return
    # Kiri's 3DGS Render is the fallback (adds its own splat geo-nodes + shader).
    if try_kiri_dgs():
        _set_viewport_rendered()
        bpy.app.timers.register(lambda: (_set_viewport_rendered(), None)[1], first_interval=1.5)
        return
    # Last resort — raw point cloud (the streaky look in the screenshot).
    print("[splatforge] FALLBACK: importing raw PLY (no splat shader)")
    bpy.ops.wm.ply_import(filepath=PLY_PATH)


bpy.app.timers.register(lambda: (setup(), None)[1], first_interval=1.0)
'''
