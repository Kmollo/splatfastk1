# Security

SplatfastK1 is a desktop app you install and run as yourself. It has **no
telemetry, no analytics, no third-party SDKs**. The only network calls go to
`api.replicate.com` (over HTTPS) and `*.replicate.delivery` (to fetch your
trained splat back).

## Threat model

| Trust level | What it is |
|---|---|
| **Trusted**  | The user themselves, their Replicate account, the source code in this repo, the official Brush binary built by our GitHub Actions workflow |
| **Untrusted**| The input video (could be crafted), the dataset zip uploaded to Replicate (could be crafted by a man-in-the-middle), any URL returned by the Replicate API, the contents of any `splatforge.json` manifest on disk |

## How sensitive data is handled

### Replicate API key

- Stored in **Windows Credential Manager** via `keyring` — encrypted, scoped to
  the local Windows user account. Same vault that Edge, Chrome, and Outlook use.
- Never written to `config.json`, never logged, never sent in URL parameters,
  never included in error messages.
- Sent only over HTTPS to `api.replicate.com` in the `Authorization: Bearer`
  header.

### Source video + COLMAP frames

- The **original video stays on your machine** — only the COLMAP-derived
  dataset zip (extracted frames + sparse reconstruction) is uploaded for cloud
  training.
- Outputs (`scene.ply`) are downloaded back to `%USERPROFILE%\SplatfastK1\outputs\`.

### Preferences

- Plain JSON at `%APPDATA%\SplatfastK1\config.json`.
- `save_prefs()` whitelists keys (`outputs_dir`, `last_project_id`,
  `default_quality`) — even if a caller passes a secret, it's filtered out.
- Written atomically (write to `.tmp`, then `os.replace()`) so a mid-write
  crash can't corrupt your settings.

## Defenses in place

| Surface | Defense |
|---|---|
| Command injection | All subprocess calls use list-args, never `shell=True` |
| Code injection via template | Blender auto-import script embeds paths via `repr()` — quotes/backslashes/unicode in paths can't break out of the literal |
| Path traversal in project names | Sanitized via `_UNSAFE_NAME_CHARS = '<>:"/\\|?*'` |
| Zip-slip (Replicate side) | Each zip entry validated: rejects absolute paths, `..` segments, and any entry whose resolved path leaves the dataset dir |
| Zip-bomb (Replicate side) | 50 GB cap on total decompressed size, checked both from the manifest and during extraction |
| SSRF on output download | Strict HTTPS-only host allowlist: `replicate.delivery`, `api.replicate.com`. AWS metadata, localhost, file://, and suffix-attack hosts (`replicate.delivery.evil.com`) are rejected |
| Supply chain (model version) | Optional `PINNED_VERSION_ID` constant in `desktop/cloud/replicate_client.py` — set to a vetted version hash to opt out of auto-fetching the latest |
| Memory bomb on download | Streamed in 1 MB chunks; never loads the full file into memory |
| `eval` / `exec` / `pickle.loads` | None used. (The only `.exec()` calls are PyQt's `QApplication.exec()` and `menu.exec()` — Qt event loop entry, not Python code execution.) |
| TLS bypass | `verify=False` and friends are never used |
| Console window flash | All subprocess launches set `CREATE_NO_WINDOW` on Windows |

## What we still rely on

- **The user's Windows account** is the trust boundary. If it's compromised,
  so is the Credential Manager and so is the app's working data.
- **Replicate's API** is trusted to return a sane prediction structure. We
  validate output URLs against the allowlist, but we trust the model's stdout
  logs (which we display) and the `output` field's PLY contents.
- **Brush** and **COLMAP** binaries are trusted. Brush is built by our public
  GitHub Actions workflow from a pinned source commit; COLMAP is whatever the
  user has installed locally.
- **BlendSplat** library files are loaded into Blender — anyone with write
  access to `~/Documents/BlendSplat-Library/` can run code in your Blender
  session.

## Reporting a vulnerability

If you find a security issue, open an issue on the GitHub repo with
"[security]" in the title, or contact the maintainer directly. We aim to
acknowledge within 72 hours.
