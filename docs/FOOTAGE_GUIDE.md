# Footage Guide

Good splats start with good footage.

## Capture Tips

- Move slowly.
- Keep the subject in frame.
- Avoid motion blur.
- Capture wide coverage before close detail.
- Avoid shiny, transparent, or textureless surfaces when possible.
- Use steady exposure and focus.

## Recommended First Test

Record a 20 to 40 second phone video around a small object, room corner, sculpture, or building detail.

## When Reconstruction Fails

Try:

- More light.
- Slower movement.
- More overlap between views.
- `--matcher exhaustive`.
- `--quality high`.

Avoid first tests where the object rotates but the camera stays fixed. COLMAP works best when the scene is static and the camera moves through or around it.
