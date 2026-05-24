# SkySplat Reference Notes

SkySplat validates the same core workflow SplatfastK1 is targeting:

```text
video -> frames -> COLMAP -> transformed dataset -> Brush -> Gaussian splat
```

Useful lessons for SplatfastK1:

- Keep every run in a separate project folder to avoid file collisions.
- Prefer automatic path linking over asking users to browse for intermediate folders.
- Treat Brush as the first real training backend.
- Detect `brush_app_windows.exe`, not only a command named `brush`.
- Keep separate GLOMAP optional so first-run users can start with COLMAP's mapper.
- Keep Blender integration as a handoff layer, while SplatfastK1 owns the easiest "video in, splat out" path.

Product difference:

SkySplat is a powerful Blender add-on. SplatfastK1 should be the simplified outer workflow:

```text
upload video -> click create -> preview splat -> open/import in Blender
```
