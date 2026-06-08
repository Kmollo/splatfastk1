# SplatfastK1 Web Viewer

A single-page HTML viewer that loads a Gaussian splat `.ply` file and renders
it in the browser. Drag to orbit, scroll/pinch to zoom. Works on phones.

## Files

- `index.html` — the viewer itself (no build step, just open it)
- `scene.ply` — the splat scene (~135 MB, copied from `ui-workspace/outputs/...`)
- `TestLocal.bat` — double-click to run a local server and open the viewer

## Test it locally (before you share the link)

1. Double-click `TestLocal.bat`
2. Your browser opens to `http://localhost:8000`
3. Wait ~30 seconds for the scene to download
4. You should see the 3D scene — drag to orbit

## Share it publicly (so contractors can click a link)

You have three good options, easiest first:

### Option 1: Netlify Drop (zero config, free)

1. Go to https://app.netlify.com/drop
2. Drag this whole `viewer` folder onto the page
3. You get a public URL like `https://random-name-123.netlify.app`
4. Paste that URL in your cold emails

That's it. No account needed, no command line.

### Option 2: GitHub Pages (free, ties to your repo)

1. Push this `viewer` folder to a branch in your repo
2. In repo settings, enable Pages on that branch
3. Your URL will be `https://kmollo.github.io/splatfastk1/viewer/`

Trade-off: GitHub has a 100MB file size limit per file. The `scene.ply` here
is 135MB — too big. You'd need to either compress it (use SuperSplat to convert
to `.ksplat` or `.splat`, ~5x smaller) or host the `.ply` somewhere else.

### Option 3: Cloudflare Pages or Vercel (free, custom domain support)

Same idea as Netlify but with a free custom-domain option. Use this once you
have a real domain like `splatfastk1.com`.

## Why a separate viewer?

The desktop app opens splats in Blender. That's fine for power users — but for
cold-email demos and client previews, "click this link" beats "install Blender,
install BlendSplat, then open this file." Web viewer = removes that friction.

## What library is this using?

`@mkkellogg/gaussian-splats-3d` v0.4.5 loaded via jsDelivr CDN. No npm install,
no build step — pure HTML + ES modules. If the CDN ever goes down, you can
self-host that file too.
