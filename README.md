# SplatfastK1

**Turn a phone video into a 3D Gaussian splat — without a GPU, without the command line.**

SplatfastK1 is a free, open-source Windows desktop app that takes a normal
phone video and produces a Blender-ready Gaussian splat scene. It does the
heavy training on a cloud GPU (your own Replicate account) so you don't need
an NVIDIA card on your laptop, and it opens the result in Blender at the
exact angle the first video frame was shot from.

> **No telemetry. No SaaS lock-in. Your videos and trained splats stay on
> your machine.** The only cloud component is the GPU training step, which
> runs in your own Replicate account using a token you paste once.

## What it does, in one picture

```text
   phone video                 cloud GPU (your account)
       |                              ^
       v                              |
   [ Extract frames ] --> [ COLMAP SfM ] --> [ Upload zip ]
                                                  |
                                                  v
                                          [ Brush trains splat ]
                                                  |
                                                  v
   [ Blender opens at first-frame camera pose ] <- [ Download .ply ]
```

## Why it's different

| | SplatfastK1 | Polycam / Luma | PostShot | SkySplat |
|---|---|---|---|---|
| Standalone desktop app | ✅ | ❌ (mobile/web) | ✅ | ❌ (Blender addon) |
| Works without a GPU | ✅ (cloud) | ✅ (their cloud) | ❌ | ❌ |
| Your own cloud account, not a SaaS | ✅ | ❌ | n/a | n/a |
| Auto-opens in Blender | ✅ | ❌ | ❌ | ✅ |
| Opens at original camera angle | ✅ | ❌ | ❌ | ✅ |
| Free & open source | ✅ | ❌ | ✅ (closed) | ✅ |
| Non-technical UX (no CLI) | ✅ | ✅ | ✅ | ❌ |

We don't compete on the splat algorithm — we use [Brush](https://github.com/ArthurBrussee/brush)
under the hood. We compete on the **end-to-end UX**: a non-technical person
with a phone and a $5 Replicate credit can produce a real Gaussian splat in
Blender in about 5 minutes.

## Quick start

1. Install **Python 3.11+** from [python.org](https://www.python.org/downloads/)
   (check **"Add Python to PATH"** when installing).
2. Clone the repo:
   ```powershell
   git clone https://github.com/Kmollo/splatfastk1.git
   cd splatfastk1
   ```
3. **Double-click `Start_SplatfastK1.bat`** in the folder. That's it.

The launcher will:
- Install Python dependencies automatically (one-time, ~30 sec)
- Add **SplatfastK1** to your Start Menu + Desktop (so you can find it via Windows search next time)
- Open the app, which shows a Setup screen on first launch — click **Install everything I can** and it downloads Brush, BlendSplat, and COLMAP for you

After Setup completes, you'll only need to install **Blender 5.1** ([download](https://www.blender.org/download/)) and grab a free **Replicate API key** ([signup](https://replicate.com/signin)) for cloud training. See **[REQUIREMENTS.md](REQUIREMENTS.md)** for the full list.

### ⚠️ First-launch SmartScreen warning

The **very first time** you double-click `Start_SplatfastK1.bat`, Windows
Defender SmartScreen will probably pop up a blue warning:

> *"Windows protected your PC — Microsoft Defender SmartScreen prevented an unrecognized app from starting."*

This is standard for **any** script downloaded from the internet — even from
big legitimate projects. It just means we haven't paid Microsoft for a code-
signing certificate (which costs ~$200/year). The app itself is fine; you can
read every line of source code in this repo.

To proceed: click **"More info"**, then **"Run anyway"**. Windows remembers
your decision — you won't be prompted again.

### Once you've launched the app

In **Settings**, paste your Replicate API token (free signup at
[replicate.com](https://replicate.com), pay-as-you-go ~$0.03 per fast
train, ~$0.20 per high-quality train).

Then click **Start Project**, drop a video, name it, hit **Train**. When
it's done, click **Open in Blender**.

### Alternative: launch from the command line

If you prefer the terminal:

```powershell
python -m desktop.main
   ```
4. In **Settings**, paste your Replicate API token (free signup at
   [replicate.com](https://replicate.com), pay-as-you-go ~$0.03 per fast
   train, ~$0.20 per high-quality train).
5. Click **Start Project**, drop a video, name it, hit **Train**.
6. When it's done, click **Open in Blender**.

## How to capture a good video

- Walk *around* the subject, not *toward* it (orbit, don't dolly).
- Keep the subject in frame, well-lit, no motion blur.
- 30-90 seconds at 30 fps is plenty.
- Avoid: flat textureless walls, mirrors, fast-moving subjects, transparent
  glass, rotating turntables (the camera needs to move, not the object).

## Features

- **Drag-and-drop UI** built in PyQt6 — no terminal required
- **Local prep + cloud train** — frame extraction + COLMAP run on your
  machine; only the small COLMAP dataset gets uploaded for training (your
  original video never leaves your computer)
- **Live progress** — streaming logs from the cloud GPU, with parsed step
  counters so you actually know how far in you are
- **Project library** — saved projects appear in the **Projects** tab, click
  to re-open at the Done page with all action buttons (View Splat / Blender
  / Show Files / Train Again)
- **Resume training** — train the same project again at a different quality
  setting without re-doing COLMAP
- **Smart Blender import** — auto-detects BlendSplat or Kiri 3DGS Render and
  builds the right shader chain; reads the COLMAP camera poses to place
  Blender's camera at the original first-frame angle
- **Secure secret storage** — API key lives in Windows Credential Manager,
  never in plaintext on disk
- **Local-only mode** — if you have an NVIDIA GPU, you can skip the cloud
  step entirely (toggle on the project setup page)

## CLI (optional)

The desktop app is the primary interface, but there's also a real CLI:

```bash
splatforge doctor                                # check what's installed
splatforge create input.mp4 --quality fast       # run the full pipeline
splatforge create input.mp4 --backend none       # local prep only, no training
```

## Project structure

A completed project at `~/SplatfastK1/outputs/<name>/`:

```text
<name>/
  images/              <- extracted frames
  reconstruction/      <- COLMAP sparse model
  splat/scene.ply      <- the trained Gaussian splat
  blender/             <- placeholder for Blender outputs
  logs/                <- pipeline logs
  splatforge.json      <- project manifest
```

## Architecture

```
desktop/         PyQt6 GUI — the app a user opens
src/splatforge/  Pipeline core: CLI, FFmpeg + COLMAP orchestration, project layout
replicate_model/ The Cog/Replicate model code that trains Brush in the cloud
blender_addon/   Optional Blender addon for importing a project folder
docs/            Architecture notes and design decisions
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the deeper tour.

## Security

- No telemetry, no analytics, no third-party SDKs
- API key stored in **Windows Credential Manager** (same vault Edge uses)
- All network calls are HTTPS, scoped to `api.replicate.com` and
  `*.replicate.delivery`
- Full threat model + defenses are in **[SECURITY.md](SECURITY.md)**

## Status

**Working end-to-end on Windows 10/11.** Mac and Linux support is feasible
but not in this release — the cloud pipeline is cross-platform, but the
Blender launcher and Start Menu integration are Windows-only.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Run the smoke test before submitting
a PR:

```bash
python -m desktop.test_buttons    # 46 button-wiring checks
python -m pytest                  # CLI/pipeline tests
```

## Credits

- Gaussian splat training: [Brush](https://github.com/ArthurBrussee/brush) by Arthur Brussee
- Splat rendering in Blender: [BlendSplat](https://codeberg.org/soerensc/BlendSplat-Library) by soerensc
- Photogrammetry: [COLMAP](https://github.com/colmap/colmap)
- Cloud GPU runtime: [Replicate](https://replicate.com) + [cog](https://github.com/replicate/cog)

## License

MIT — see [LICENSE](LICENSE).
