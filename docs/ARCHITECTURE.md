# Architecture

SplatfastK1 is designed as a small pipeline with replaceable stages.

```text
Input video/images
  -> frame staging
  -> feature extraction
  -> matching
  -> reconstruction
  -> Brush Gaussian splat training/export
  -> Blender handoff
```

## Core Boundary

The CLI owns orchestration, file layout, diagnostics, and error messages. External engines do the heavy compute work.

## Backend Layer

Backends live in `src/splatforge/backends`. The first backend is Brush because it is cross-platform, supports COLMAP datasets, and can export PLY splats.

## Project Manifest

Every output folder includes `splatforge.json`. The Blender add-on should use this manifest instead of guessing paths.

## Why This Shape

Gaussian splatting tooling changes quickly. Keeping COLMAP/GLOMAP, training, and Blender import as separate stages lets the project adopt better backends without changing the user-facing command.
