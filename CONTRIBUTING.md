# Contributing

SplatfastK1 is trying to make Gaussian splatting feel simple for Blender users.

Good first contributions:

- Improve install instructions for Windows, macOS, or Linux.
- Add better diagnostics for failed reconstructions.
- Add support for a splat training backend.
- Improve the Blender add-on import flow.
- Add sample datasets with permissive licenses.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check src tests
pytest
```

Keep user-facing errors plain and helpful. Most SplatfastK1 users should not need to know which internal tool failed unless they are debugging.
