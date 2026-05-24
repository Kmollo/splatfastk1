# Requirements

SplatfastK1 turns a phone video into a 3D Gaussian splat you can open in
Blender. Here's everything you need installed before it'll work.

## Platform

**Windows 10 or Windows 11 (64-bit).** This release is Windows-only — see
[Cross-platform support](#cross-platform-support) at the bottom if you're on
Mac/Linux.

## Required

### 1. Python 3.11 or newer
Download from [python.org/downloads](https://www.python.org/downloads/windows/).
During install, **tick "Add python.exe to PATH"**.

Verify: open PowerShell and run
```powershell
python --version
```
You should see `Python 3.11.x` or higher.

### 2. COLMAP (free, ~150 MB)
The "structure-from-motion" engine that figures out where each video frame
was filmed from. Without it, no splat training is possible.

- Download: [github.com/colmap/colmap/releases](https://github.com/colmap/colmap/releases)
  → grab the `COLMAP-3.x-windows-cuda.zip` (or `-no-cuda.zip` if you don't
  have an NVIDIA GPU — only matters for local training, not cloud)
- Unzip it somewhere permanent like `C:\Tools\colmap\`
- Add that folder to your Windows PATH:
  - Press `Win` → type `Edit environment variables` → open it
  - Edit `Path` → New → paste `C:\Tools\colmap` → OK

Verify:
```powershell
colmap -h
```

### 3. FFmpeg (free, ~100 MB)
Extracts frames from your video file.

- Download: [ffmpeg.org/download.html](https://ffmpeg.org/download.html) →
  Windows builds → Gyan.dev → `ffmpeg-release-essentials.zip`
- Unzip to `C:\Tools\ffmpeg\` (you want the `bin/` subfolder on PATH)
- Add `C:\Tools\ffmpeg\bin` to your Windows PATH (same way as COLMAP above)

Verify:
```powershell
ffmpeg -version
```

### 4. A Replicate account + API key (for cloud training)
The app uploads your COLMAP dataset to Replicate, where a cloud GPU trains
the Gaussian splat. You pay per training run (~$0.03 for "fast", ~$0.20 for
"high quality").

- Sign up: [replicate.com](https://replicate.com)
- Add a payment method at [replicate.com/account/billing](https://replicate.com/account/billing)
  (no monthly fee — pay-as-you-go)
- Copy your token from [replicate.com/account/api-tokens](https://replicate.com/account/api-tokens)
- Paste it into **SplatfastK1 → Settings** the first time you open the app

> Without a Replicate key, the app still works for local training **if** you
> have an NVIDIA GPU. Without one, cloud is the only option.

## Required to view the result in Blender

### 5. Blender 5.1 (free)
- Download: [blender.org/download](https://www.blender.org/download/)
- Install to the default location: `C:\Program Files\Blender Foundation\Blender 5.1\`

The auto-import script also tries Blender 4.3 as a fallback, but 5.1 is the
target.

### 6. BlendSplat library (free, ~700 KB)
The geometry-nodes asset library by soerensc that turns the trained `.ply`
file into proper Gaussian splat rendering inside Blender.

The first-time setup screen in the SplatfastK1 app downloads and installs
this for you automatically. If you want to install it manually:

- Download: [blendsplat-core-v0.5.1.zip](https://codeberg.org/soerensc/BlendSplat-Library/releases/download/v0.5.1/blendsplat-core-v0.5.1.zip)
  (latest releases on the [BlendSplat releases page](https://codeberg.org/soerensc/BlendSplat-Library/releases))
- Unzip to:
  ```
  C:\Users\<You>\Documents\BlendSplat-Library\
  ```
  The folder should contain a `core/` subfolder with `display.blend`,
  `create.blend`, etc.

If BlendSplat isn't installed, the app falls back to the **Kiri Engine
3DGS Render** Blender addon if you have that installed. If neither is
available, the splat will open as a raw point cloud (still viewable, just
not pretty).

## Optional

- **NVIDIA GPU with 8 GB+ VRAM** — only if you want local training instead
  of cloud. Cloud doesn't need any local GPU.
- **Kiri Engine 3DGS Render** Blender addon — as a BlendSplat alternative.
  Available on the Blender Extensions site.

## Install SplatfastK1 itself

After all the above is in place:

```powershell
git clone https://github.com/Kmollo/splatfastk1.git
cd splatfastk1
pip install -e .
```

Then launch:
```powershell
python -m desktop.main
```

Or pin a Start Menu shortcut: see `desktop/launch.bat`.

## Verify everything works

Run the smoke test (no actual training, just checks every button is wired):
```powershell
python -m desktop.test_buttons
```
You should see `46 passed, 0 failed`.

## Cross-platform support

The **core pipeline** (COLMAP, FFmpeg, Brush via Replicate, keyring) is
cross-platform. The Windows-only parts are:

- Blender auto-launcher (hardcoded path `C:\Program Files\Blender Foundation\...`)
- The bundled Brush local viewer binary (`brush_app_windows.exe`)
- The `CREATE_NO_WINDOW` console-hiding flag (no-ops elsewhere)
- Start Menu shortcut script

A Mac/Linux build is feasible but not in this release. If you want it,
open an issue.
