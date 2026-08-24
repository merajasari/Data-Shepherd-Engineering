#!/usr/bin/env python3
"""Data Shepherd Engineering IntroVideo12 (legacy filename compatibility).

The historical ``video_v12`` filename predates the IntroVideo naming rule.
New marketing videos must use ``IntroVideo<N>`` so they cannot be confused
with ML model generations such as V8 and V10.

Changes over V11:
- presents only V8 and V10 as model generations
- folds the retained V9 auto-tuning and Cycle 2 capabilities into V10
- removes the rejected-winner explanation scene
- removes every floating detail viewport from the product and engineering scenes
- preserves the original phone artwork, bezel, angle and placement
- replaces only the phone's existing screen content with an in-perspective market chart
- reveals the GitHub repository content already embedded in the engineering artwork
- gives the founder introduction a more polished executive-engineering treatment
- expands the model chapter with V8 operations, V10 research mechanics and a direct comparison
- uses a warm, natural female "friendly instructor" narration profile
"""
from __future__ import annotations

import importlib.util
import base64
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("dsv11", HERE / "generate_datashepherd_video_v11.py")
v11 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v11)
v10 = v11.v10
v6 = v11.v6
from platform_icon_assets import ICON_BASE64


# The legacy IntroVideo11 engine provides clause-based narration and light
# mastering. IntroVideo12 steers that
# engine toward a warm female "friendly instructor" character: confident,
# approachable and deliberately paced. A caller can still override DS_RATE or
# DS_VOICE explicitly on the Mac.
_natural_voice = v6.voice
_openai_tts_used = False


def choose_friendly_female_voice():
    requested = os.environ.get("DS_VOICE", "").strip()
    if requested:
        return requested
    try:
        listing = subprocess.check_output(["say", "-v", "?"], text=True)
    except Exception:
        listing = ""
    # Prefer the more natural female voices commonly available in current
    # macOS releases. The ordered fallback keeps the render portable.
    for name in ("Zoe", "Ava", "Samantha", "Serena", "Kate", "Martha", "Stephanie"):
        if re.search(rf"(?m)^{re.escape(name)}\s+", listing):
            return name
    return "Samantha"


def openai_female_voice(text, path):
    """Generate natural female narration through OpenAI when locally enabled."""
    global _openai_tts_used
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    provider = os.environ.get("DS_TTS_PROVIDER", "auto").strip().lower()
    if provider not in {"auto", "openai"} or not api_key:
        if provider == "openai" and not api_key:
            print("OPENAI_API_KEY is not set; using the Zoe/macOS female fallback.")
        return False

    model = os.environ.get("DS_OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()
    voice_name = os.environ.get("DS_OPENAI_VOICE", "coral").strip()
    speed = float(os.environ.get("DS_OPENAI_SPEED", "0.96"))
    payload = json.dumps({
        "model": model,
        "voice": voice_name,
        "input": text,
        "instructions": (
            "Speak as a warm, natural, professional female narrator and friendly instructor. "
            "Sound conversational, confident and kind, with clear technical pronunciation, "
            "gentle emphasis, natural pauses and restrained enthusiasm. Never sound theatrical, "
            "sales-driven, rushed or robotic."
        ),
        "response_format": "wav",
        "speed": speed,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    tmp = Path(tempfile.mkdtemp(prefix="ds_openai_tts_"))
    try:
        wav_path = tmp / "speech.wav"
        with urllib.request.urlopen(request, timeout=180) as response:
            wav_path.write_bytes(response.read())
        subprocess.check_call([
            v6.ff(), "-y", "-i", str(wav_path),
            "-af", "highpass=f=60,lowpass=f=15000,loudnorm=I=-19:TP=-1.5:LRA=11",
            "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16be", str(path),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _openai_tts_used = True
        print(f"Narration voice: OpenAI {voice_name} ({model}, speed {speed:.2f})")
        return True
    except urllib.error.HTTPError as exc:
        error_code = f"http_{exc.code}"
        error_message = "OpenAI rejected the speech request."
        try:
            body = json.loads(exc.read().decode("utf-8"))
            error = body.get("error", {})
            error_code = error.get("code") or error.get("type") or error_code
            error_message = error.get("message") or error_message
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            pass
        print(f"OpenAI narration unavailable: {error_code} — {error_message}")
        if provider == "openai":
            raise RuntimeError(
                "OpenAI narration was explicitly required. Resolve the API billing/rate-limit "
                "error above, then rerun; no macOS fallback was generated."
            ) from None
        print("Using the Zoe/macOS female fallback because DS_TTS_PROVIDER is auto.")
        return False
    except (urllib.error.URLError, TimeoutError, subprocess.CalledProcessError) as exc:
        detail = type(exc).__name__
        print(f"OpenAI narration unavailable ({detail}).")
        if provider == "openai":
            raise RuntimeError(
                "OpenAI narration was explicitly required. Resolve the connection/audio error "
                "above, then rerun; no macOS fallback was generated."
            ) from None
        print("Using the Zoe/macOS female fallback because DS_TTS_PROVIDER is auto.")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def kinder_voice(text, path):
    if openai_female_voice(text, path):
        return
    previous_rate = os.environ.get("DS_RATE")
    previous_voice = os.environ.get("DS_VOICE")
    if previous_rate is None:
        os.environ["DS_RATE"] = "172"
    if previous_voice is None:
        os.environ["DS_VOICE"] = choose_friendly_female_voice()
    try:
        return _natural_voice(text, path)
    finally:
        if previous_rate is None:
            os.environ.pop("DS_RATE", None)
        else:
            os.environ["DS_RATE"] = previous_rate
        if previous_voice is None:
            os.environ.pop("DS_VOICE", None)
        else:
            os.environ["DS_VOICE"] = previous_voice


v6.voice = kinder_voice


# Render site imagery directly instead of calling the V8/V10 site wrappers.
# Those wrappers add the floating LIVE DETAIL / SYSTEM DETAIL viewports and the
# oversized portfolio phone that the user asked to remove.
def clean_site(path, t, title, subtitle):
    im = v6.bg()
    v6.head(im, title, subtitle)
    d = v6.ImageDraw.Draw(im)
    area = (70, 200, 1850, 1015)
    if path.exists():
        source = v6.load(path)
        sd = v6.ImageDraw.Draw(source)
        sw, sh = source.size

        if path == v6.ASSETS["dashboard"]:
            # Remove the two lower-right source panels before the animated crop,
            # leaving a clean continuation of the architecture background.
            x0, y0 = int(sw * 0.522), int(sh * 0.842)
            x1, y1 = int(sw * 0.997), int(sh * 0.997)
            sd.rectangle((x0, y0, x1, y1), fill=(6, 18, 29))
            for x in range(x0 + 34, x1, 88):
                sd.line((x, y0, x, y1), fill=(7, 25, 40), width=1)
            for y in range(y0 + 34, y1, 70):
                sd.line((x0, y, x1, y), fill=(7, 25, 40), width=1)

        elif path == v6.ASSETS["overview"]:
            # The phone is already part of the source artwork.  Its inner screen
            # is a perspective quadrilateral, not an axis-aligned card.  Paint
            # directly inside those four corners so the original bezel, tilt,
            # placement and surrounding artwork remain untouched.
            quad = [
                (int(sw * 0.258), int(sh * 0.593)),  # top-left
                (int(sw * 0.313), int(sh * 0.602)),  # top-right
                (int(sw * 0.297), int(sh * 0.791)),  # bottom-right
                (int(sw * 0.244), int(sh * 0.784)),  # bottom-left
            ]
            sd.polygon(quad, fill=(3, 13, 23))

            def qpoint(u, v):
                top_x = quad[0][0] + (quad[1][0] - quad[0][0]) * u
                top_y = quad[0][1] + (quad[1][1] - quad[0][1]) * u
                bot_x = quad[3][0] + (quad[2][0] - quad[3][0]) * u
                bot_y = quad[3][1] + (quad[2][1] - quad[3][1]) * u
                return (int(top_x + (bot_x - top_x) * v), int(top_y + (bot_y - top_y) * v))

            # Subtle chart grid follows the same phone perspective.
            for v in (0.25, 0.45, 0.65, 0.85):
                sd.line((qpoint(0.08, v), qpoint(0.92, v)), fill=(18, 45, 62), width=max(1, sw // 1200))
            for u in (0.18, 0.38, 0.58, 0.78):
                sd.line((qpoint(u, 0.18), qpoint(u, 0.88)), fill=(12, 34, 50), width=max(1, sw // 1400))

            values = [0.76, 0.69, 0.72, 0.58, 0.62, 0.47, 0.52, 0.36, 0.40, 0.25, 0.30, 0.16]
            points = [qpoint(0.09 + i * 0.075, value) for i, value in enumerate(values)]
            sd.line(points, fill=(20, 92, 111), width=max(4, sw // 310))
            sd.line(points, fill=v6.GREEN, width=max(2, sw // 600))
            pulse_index = min(len(points) - 1, int(t * len(points)))
            px, py = points[pulse_index]
            pr = max(3, sw // 420)
            sd.ellipse((px - pr, py - pr, px + pr, py + pr), fill=v6.CYAN)

            # Small volume bars remain inside the original screen.
            for i, height in enumerate((0.08, 0.13, 0.10, 0.18, 0.15, 0.22, 0.17, 0.27)):
                left = qpoint(0.10 + i * 0.105, 0.93)
                top = qpoint(0.10 + i * 0.105, 0.93 - height)
                right = qpoint(0.15 + i * 0.105, 0.93)
                sd.polygon([top, qpoint(0.15 + i * 0.105, 0.93 - height), right, left], fill=(31, 119, 139))

        im.paste(
            v6.cover(source, (1780, 815), 1 + 0.09 * v6.ease(t), 0.5 + 0.05 * v6.math.sin(t * v6.math.pi), 0.47),
            (70, 200),
        )

    # One browser frame around the main image only—never extra inset boxes.
    bx0, by0, bx1 = 120, 205, 1800
    d.rounded_rectangle((bx0, by0, bx1, by0 + 48), 14, fill=(7, 18, 31), outline=v6.BORDER, width=2)
    for n, colour in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        cx = bx0 + 25 + n * 28
        d.ellipse((cx - 7, by0 + 17, cx + 7, by0 + 31), fill=colour)
    d.rounded_rectangle((bx0 + 130, by0 + 10, bx1 - 25, by0 + 38), 10, fill=(11, 30, 49))
    d.text((bx0 + 155, by0 + 13), "datashepherdengineering.com", font=v6.font(15, True), fill=v6.MUTED)
    d.rounded_rectangle(area, 26, outline=v6.CYAN, width=3)
    d.rounded_rectangle((1435, 145, 1815, 190), 12, fill=(4, 18, 31), outline=v6.BORDER, width=2)
    d.text((1460, 157), "ACTUAL DATA SHEPHERD PLATFORM", font=v6.font(15, True), fill=v6.GREEN)
    return im


v6.site = clean_site


_founder_base = v6.founder


def professional_founder(t, close=False):
    if close:
        im = _founder_base(t, True)
        if _openai_tts_used:
            d = v6.ImageDraw.Draw(im)
            d.text(
                (1390, 1015), "AI-GENERATED NARRATION • OPENAI TTS",
                font=v6.font(14, True), fill=v6.MUTED,
            )
        return im

    # Build a dedicated Data Shepherd opening rather than covering the original
    # founder frame.  The portrait is intentionally a small supporting element;
    # the platform's data/AI story owns the canvas.
    im = v6.bg()
    d = v6.ImageDraw.Draw(im)

    # Layered cyan/green glows create depth while retaining the site's dark navy
    # palette.  They are drawn as translucent rings so the grid remains visible.
    glow = v6.Image.new("RGBA", (v6.W, v6.H), (0, 0, 0, 0))
    gd = v6.ImageDraw.Draw(glow)
    core_x, core_y = 1270, 610
    for radius in range(470, 90, -38):
        alpha = max(3, int(27 * (1 - radius / 520)))
        colour = (*v6.CYAN, alpha) if (radius // 38) % 2 else (*v6.GREEN, alpha)
        gd.ellipse((core_x - radius, core_y - radius, core_x + radius, core_y + radius), outline=colour, width=3)
    im = v6.Image.alpha_composite(im.convert("RGBA"), glow).convert("RGB")
    d = v6.ImageDraw.Draw(im)

    v6.logo(im, 62, 38, 300, 112)
    d.text((100, 250), "MERAJ ASARI", font=v6.font(68, True), fill=v6.TEXT)
    d.text((103, 336), "FOUNDER  •  LEAD ENGINEER  •  CEO", font=v6.font(25, True), fill=v6.CYAN)
    d.line((103, 395, 700, 395), fill=v6.CYAN, width=3)
    d.text((103, 455), "BUILDING TRUSTED", font=v6.font(54, True), fill=v6.TEXT)
    d.text((103, 520), "DATA & AI SYSTEMS", font=v6.font(54, True), fill=v6.GREEN)
    d.multiline_text(
        (105, 610),
        "Governed pipelines. Transparent machine learning.\nEvidence that earns its way into the platform.",
        font=v6.font(25), fill=v6.MUTED, spacing=13,
    )

    # Animated neural/data graph.  Fixed geometry makes every render
    # reproducible; the travelling pulses supply restrained motion.
    nodes = [
        (1020, 475), (1155, 385), (1320, 420), (1445, 520),
        (1045, 650), (1195, 565), (1350, 610), (1490, 690),
        (1110, 790), (1290, 760), (1430, 830),
    ]
    edges = [
        (0, 1), (0, 4), (1, 2), (1, 5), (2, 3), (2, 6),
        (3, 6), (4, 5), (4, 8), (5, 6), (5, 8), (5, 9),
        (6, 7), (6, 9), (7, 10), (8, 9), (9, 10),
    ]
    for a, b in edges:
        d.line((*nodes[a], *nodes[b]), fill=(24, 86, 111), width=2)
        phase = (t * 1.8 + (a * 0.13 + b * 0.07)) % 1.0
        px = int(nodes[a][0] + (nodes[b][0] - nodes[a][0]) * phase)
        py = int(nodes[a][1] + (nodes[b][1] - nodes[a][1]) * phase)
        d.ellipse((px - 5, py - 5, px + 5, py + 5), fill=v6.GREEN)
    for i, (x, y) in enumerate(nodes):
        r = 9 if i not in (5, 6) else 13
        d.ellipse((x - r - 7, y - r - 7, x + r + 7, y + r + 7), outline=(26, 105, 132), width=2)
        d.ellipse((x - r, y - r, x + r, y + r), fill=v6.CYAN if i % 3 else v6.GREEN)

    d.ellipse((1195, 535, 1405, 745), fill=(7, 24, 42), outline=v6.CYAN, width=5)
    d.ellipse((1220, 560, 1380, 720), outline=v6.GREEN, width=2)
    ai_box = d.textbbox((0, 0), "AI", font=v6.font(66, True))
    d.text((1300 - (ai_box[2] - ai_box[0]) / 2, 595), "AI", font=v6.font(66, True), fill=v6.TEXT)
    d.text((1240, 680), "ML CORE", font=v6.font(19, True), fill=v6.GREEN)

    # Compact portrait in the top-right.  It is part of the composition rather
    # than a full-height split screen, leaving the AI scene visually dominant.
    card = (1535, 52, 1840, 360)
    d.rounded_rectangle(card, 26, fill=(7, 22, 38), outline=v6.CYAN, width=3)
    portrait_path = v6.fp()
    if portrait_path:
        portrait = v6.cover(v6.load(portrait_path), (267, 267), 1.05, 0.5, 0.22)
        mask = v6.Image.new("L", portrait.size, 0)
        v6.ImageDraw.Draw(mask).rounded_rectangle((0, 0, 266, 266), 20, fill=255)
        im.paste(portrait, (1554, 71), mask)
    else:
        d.ellipse((1625, 105, 1750, 230), outline=v6.CYAN, width=5)
        d.arc((1592, 190, 1783, 350), 190, 350, fill=v6.CYAN, width=5)

    # A concise governed-data path anchors the lower third without competing
    # with the narration or portrait.
    labels = [("BRONZE", v6.GOLD), ("SILVER", v6.MUTED), ("GOLD", v6.GOLD), ("SPARK", v6.CYAN), ("V8", v6.GREEN), ("V10", v6.CYAN)]
    x0, y0, gap = 115, 885, 277
    for i, (label, colour) in enumerate(labels):
        x = x0 + i * gap
        d.rounded_rectangle((x, y0, x + 208, y0 + 72), 18, fill=(7, 24, 41), outline=colour, width=2)
        box = d.textbbox((0, 0), label, font=v6.font(21, True))
        d.text((x + 104 - (box[2] - box[0]) / 2, y0 + 23), label, font=v6.font(21, True), fill=colour)
        if i < len(labels) - 1:
            d.line((x + 211, y0 + 36, x + gap - 10, y0 + 36), fill=v6.BORDER, width=3)
    return im


v6.founder = professional_founder


def draw_tech_icon(d, kind, cx, cy, size, colour, muted=False):
    """Draw a dependable vector icon without relying on missing font glyphs."""
    col = v6.MUTED if muted else colour
    line = max(2, size // 14)
    r = size // 2
    if kind == "ingest":
        d.arc((cx-r, cy-r//2, cx+r, cy+r//2), 180, 360, fill=col, width=line)
        d.line((cx-r, cy, cx-r, cy+r//2, cx+r, cy+r//2, cx+r, cy), fill=col, width=line)
        d.line((cx, cy-r, cx, cy+r//5), fill=col, width=line)
        d.polygon([(cx-size//6, cy), (cx+size//6, cy), (cx, cy+size//5)], fill=col)
    elif kind in {"bronze", "silver", "gold", "parquet"}:
        for off in (-size//5, 0, size//5):
            d.ellipse((cx-r, cy-r//2+off, cx+r, cy+r//2+off), outline=col, width=line)
        d.line((cx-r, cy-r//2, cx-r, cy+r//2+size//5), fill=col, width=line)
        d.line((cx+r, cy-r//2, cx+r, cy+r//2+size//5), fill=col, width=line)
    elif kind == "spark":
        pts = [(cx,cy-r),(cx+size//7,cy-size//7),(cx+r,cy-size//9),(cx+size//5,cy+size//8),
               (cx+size//4,cy+r),(cx,cy+size//4),(cx-size//4,cy+r),(cx-size//5,cy+size//8),
               (cx-r,cy-size//9),(cx-size//7,cy-size//7)]
        d.polygon(pts, outline=col)
        d.ellipse((cx-size//8,cy-size//8,cx+size//8,cy+size//8), fill=col)
    elif kind in {"features", "score", "chart"}:
        d.line((cx-r,cy+r,cx-r,cy-r,cx+r,cy-r), fill=col, width=line)
        pts=[(cx-r+5,cy+r-8),(cx-size//5,cy+size//8),(cx+size//10,cy+size//4),(cx+r-3,cy-r+8)]
        d.line(pts, fill=col, width=line)
        for x,y in pts:d.ellipse((x-line,y-line,x+line,y+line),fill=col)
    elif kind in {"model", "ai", "network"}:
        nodes=[(cx,cy),(cx-r,cy-r//2),(cx-r,cy+r//2),(cx+r,cy-r//2),(cx+r,cy+r//2),(cx,cy-r)]
        for p in nodes[1:]:d.line((*nodes[0],*p),fill=col,width=line)
        for j,(x,y) in enumerate(nodes):
            rr=size//9 if j else size//7
            d.ellipse((x-rr,y-rr,x+rr,y+rr),fill=(7,24,41),outline=col,width=line)
    elif kind in {"validated", "confirm", "gate"}:
        d.ellipse((cx-r,cy-r,cx+r,cy+r),outline=col,width=line)
        d.line((cx-r//2,cy,cx-size//10,cy+r//2,cx+r//2,cy-r//2),fill=col,width=line+1)
    elif kind in {"lock", "fixed"}:
        d.rounded_rectangle((cx-r,cy-size//8,cx+r,cy+r),size//8,outline=col,width=line)
        d.arc((cx-size//3,cy-r,cx+size//3,cy+size//5),180,360,fill=col,width=line)
    elif kind == "rank":
        for j,w in enumerate((size//3,size//2,size*2//3)):
            yy=cy-r+j*size//2
            d.line((cx-w//2,yy,cx+w//2,yy),fill=col,width=line)
        d.polygon([(cx+r,cy-r),(cx+r-size//6,cy-r+size//8),(cx+r-size//6,cy-r-size//8)],fill=col)
    elif kind in {"publish", "monitor"}:
        d.rounded_rectangle((cx-r,cy-r*3//4,cx+r,cy+r*3//4),size//9,outline=col,width=line)
        d.line((cx-size//3,cy+r,cx+size//3,cy+r),fill=col,width=line)
        d.line((cx,cy+r*3//4,cx,cy+r),fill=col,width=line)
        d.line([(cx-r+8,cy+size//5),(cx-size//5,cy),(cx+size//8,cy+size//8),(cx+r-8,cy-size//3)],fill=col,width=line)
    elif kind == "folds":
        for j in range(4):
            x=cx-r+j*size//3
            d.rounded_rectangle((x,cy-r+j*3,x+size//4,cy+r-j*3),4,outline=col,width=max(2,line-1))
    elif kind == "cost":
        d.ellipse((cx-r,cy-r,cx+r,cy+r),outline=col,width=line)
        d.text((cx-size//6,cy-size//3),"$",font=v6.font(size//2,True),fill=col)
    elif kind == "regime":
        d.arc((cx-r,cy-r,cx+r,cy+r),180,360,fill=col,width=line)
        d.line((cx-r,cy,cx-size//3,cy-size//6,cx,cy+size//5,cx+size//3,cy-size//3,cx+r,cy),fill=col,width=line)
    else:
        d.ellipse((cx-r,cy-r,cx+r,cy+r),outline=col,width=line)


_reference_source = None
_reference_icons = {}


def reference_icon(kind, size):
    """Crop an icon from the real platform-engineering artwork for visual continuity."""
    global _reference_source
    icon_dir=v6.ROOT/"assets"/"video"/"platform-icons"
    icon_files={
        "cloud":"cloud.png","bronze_3d":"bronze.png","silver_3d":"silver.png",
        "gold_3d":"gold.png","feature_table":"features.png","ai_brain":"brain.png",
        "prediction":"prediction.png",
    }
    direct=icon_dir/icon_files.get(kind,"")
    if direct.is_file():
        key=(kind,size)
        if key not in _reference_icons:
            icon=v6.Image.open(direct).convert("RGBA")
            icon.thumbnail((size,size),v6.Image.Resampling.LANCZOS)
            _reference_icons[key]=icon
        return _reference_icons[key].copy()
    embedded_name=icon_files.get(kind,"").removesuffix(".png")
    if embedded_name in ICON_BASE64:
        key=(kind,size)
        if key not in _reference_icons:
            raw=base64.b64decode(ICON_BASE64[embedded_name])
            icon=v6.Image.open(io.BytesIO(raw)).convert("RGBA")
            icon.thumbnail((size,size),v6.Image.Resampling.LANCZOS)
            _reference_icons[key]=icon
        return _reference_icons[key].copy()
    boxes = {
        # Normalized boxes in the existing END-TO-END PIPELINE artwork.
        "cloud": (0.025, 0.395, 0.145, 0.625),
        "bronze_3d": (0.165, 0.235, 0.260, 0.445),
        "silver_3d": (0.300, 0.235, 0.395, 0.445),
        "gold_3d": (0.435, 0.230, 0.535, 0.450),
        "feature_table": (0.555, 0.235, 0.655, 0.445),
        "ai_brain": (0.700, 0.215, 0.810, 0.455),
        "prediction": (0.840, 0.235, 0.970, 0.475),
    }
    if kind not in boxes or not v6.ASSETS["engineering"].exists():
        return None
    key=(kind,size)
    if key in _reference_icons:
        return _reference_icons[key].copy()
    if _reference_source is None:
        _reference_source=v6.load(v6.ASSETS["engineering"])
    sw,sh=_reference_source.size; x0,y0,x1,y1=boxes[kind]
    crop=_reference_source.crop((int(sw*x0),int(sh*y0),int(sw*x1),int(sh*y1)))
    # Remove the source panel background while retaining the luminous artwork.
    rgba=crop.convert("RGBA"); px=rgba.load(); bg=rgba.getpixel((2,2))[:3]
    for yy in range(rgba.height):
        for xx in range(rgba.width):
            rr,gg,bb,aa=px[xx,yy]
            distance=max(abs(rr-bg[0]),abs(gg-bg[1]),abs(bb-bg[2]))
            alpha=max(0,min(255,(distance-8)*12))
            px[xx,yy]=(rr,gg,bb,min(aa,alpha))
    rgba.thumbnail((size,size),v6.Image.Resampling.LANCZOS)
    _reference_icons[key]=rgba
    return rgba.copy()


def paste_reference_icon(im, kind, cx, cy, size):
    icon=reference_icon(kind,size)
    if icon is None:return False
    im.paste(icon,(int(cx-icon.width/2),int(cy-icon.height/2)),icon)
    return True


def executive_founder(t, close=False):
    """A restrained branded opener using the platform's own visual language."""
    if close:return professional_founder(t,True)
    im=v6.bg(); d=v6.ImageDraw.Draw(im)
    v6.logo(im,62,38,300,112)
    d.text((105,220),"MERAJ ASARI",font=v6.font(70,True),fill=v6.TEXT)
    d.text((108,310),"FOUNDER  •  LEAD ENGINEER  •  CEO",font=v6.font(24,True),fill=v6.CYAN)
    d.line((108,365,945,365),fill=v6.CYAN,width=3)
    d.text((108,415),"DATA ENGINEERING",font=v6.font(46,True),fill=v6.TEXT)
    d.text((108,470),"MEETS TRUSTED AI",font=v6.font(46,True),fill=v6.GREEN)
    d.multiline_text((110,545),"Governed market data. Distributed processing.\nTransparent machine learning. Observable results.",font=v6.font(23),fill=v6.MUTED,spacing=11)

    # Small portrait remains a supporting identity element, not the hero image.
    d.rounded_rectangle((1510,48,1845,382),28,fill=(7,22,38),outline=v6.CYAN,width=3)
    portrait_path=v6.fp()
    if portrait_path:
        portrait=v6.cover(v6.load(portrait_path),(293,293),1.04,.5,.22)
        mask=v6.Image.new("L",portrait.size,0)
        v6.ImageDraw.Draw(mask).rounded_rectangle((0,0,292,292),22,fill=255)
        im.paste(portrait,(1531,69),mask)
    d.text((1512,404),"FOUNDER-LED ENGINEERING",font=v6.font(16,True),fill=v6.MUTED)

    # The platform's own dimensional icons tell one clean story.
    cards=[
        (245,"GOVERNED DATA","cloud",v6.CYAN),
        (675,"FEATURE ENGINEERING","feature_table",v6.GREEN),
        (1105,"MACHINE LEARNING","ai_brain",(196,105,255)),
        (1535,"OBSERVABLE SIGNALS","prediction",v6.GOLD),
    ]
    y=800
    for i,(x,label,icon,colour) in enumerate(cards):
        active=i<=int(t*4)
        outline=colour if active else v6.BORDER
        d.rounded_rectangle((x-155,y-120,x+155,y+150),28,fill=(7,22,39),outline=outline,width=4)
        if active:paste_reference_icon(im,icon,x,y-30,142)
        bb=d.textbbox((0,0),label,font=v6.font(18,True))
        d.text((x-(bb[2]-bb[0])/2,y+91),label,font=v6.font(18,True),fill=v6.TEXT)
        if i<len(cards)-1:
            d.line((x+158,y+10,cards[i+1][0]-158,y+10),fill=v6.GREEN,width=4)
            d.polygon([(cards[i+1][0]-170,y),(cards[i+1][0]-170,y+20),(cards[i+1][0]-154,y+10)],fill=v6.GREEN)
    d.text((575,1018),"FROM TRUSTED INPUTS TO TESTABLE ARTIFICIAL INTELLIGENCE",font=v6.font(23,True),fill=v6.CYAN)
    return im


v6.founder=executive_founder


def icon_node(im, d, x, y, label, kind, colour, on=True, reference=None):
    col = colour if on else v6.BORDER
    d.rounded_rectangle((x-125,y-85,x+125,y+85),24,fill=v6.PANEL,outline=col,width=4)
    used=paste_reference_icon(im,reference,x,y-24,66) if reference and on else False
    if not used:draw_tech_icon(d, kind, x, y-24, 48, colour, not on)
    bb=d.textbbox((0,0),label,font=v6.font(18,True))
    d.text((x-(bb[2]-bb[0])/2,y+43),label,font=v6.font(18,True),fill=v6.TEXT)


def architecture_frame(kind, t):
    im=v6.bg(); d=v6.ImageDraw.Draw(im)
    if kind == "pipeline":
        v6.head(im,"END-TO-END DATA ARCHITECTURE","Governed model inputs from ingestion to features")
        labs=[("INGEST","ingest",v6.CYAN,"cloud"),("BRONZE","bronze",v6.GOLD,"bronze_3d"),("SILVER","silver",v6.MUTED,"silver_3d"),("GOLD","gold",v6.GOLD,"gold_3d"),("ML FEATURES","features",v6.GREEN,"feature_table")]
        captions=["LIVE MARKET","RAW IMMUTABLE","CLEANSED","CURATED","MODEL READY"]
    else:
        v6.head(im,"PYSPARK IN PRODUCTION","Distributed feature processing with fail-closed validation")
        labs=[("MARKET","chart",v6.CYAN,"prediction"),("PYSPARK","spark",v6.CYAN,None),("PARQUET","parquet",v6.GOLD,"silver_3d"),("101 / 101","validated",v6.GREEN,None),("MODELS","network",v6.GREEN,"ai_brain")]
        captions=["SOURCE FRAMES","DISTRIBUTED COMPUTE","COLUMNAR LAYER","CONTRACT PASS","AI / ML READY"]
    xs=[220,570,920,1270,1620]
    for i,(label,icon,colour,reference) in enumerate(labs):
        icon_node(im,d,xs[i],550,label,icon,colour,i<=int(t*5),reference)
        if i<4:
            d.line((xs[i]+130,550,xs[i+1]-130,550),fill=v6.GREEN if kind=="spark" else v6.CYAN,width=4)
            phase=(t*1.7+i*.19)%1
            px=int(xs[i]+130+(xs[i+1]-xs[i]-260)*phase)
            d.ellipse((px-6,544,px+6,556),fill=v6.GREEN)
        bb=d.textbbox((0,0),captions[i],font=v6.font(15,True))
        d.text((xs[i]-(bb[2]-bb[0])/2,665),captions[i],font=v6.font(15,True),fill=v6.MUTED)
    if kind=="pipeline":
        d.rounded_rectangle((245,780,1675,930),26,fill=(6,25,34),outline=v6.CYAN,width=3)
        d.text((360,818),"PRESERVE",font=v6.font(23,True),fill=v6.GOLD)
        d.text((620,818),"STANDARDIZE",font=v6.font(23,True),fill=v6.MUTED)
        d.text((955,818),"CURATE",font=v6.font(23,True),fill=v6.GOLD)
        d.text((1205,818),"FEATURE ENGINEER",font=v6.font(23,True),fill=v6.GREEN)
        d.text((460,875),"GOVERNED LINEAGE FROM SOURCE OBSERVATION TO MACHINE-LEARNING INPUT",font=v6.font(20,True),fill=v6.TEXT)
    else:
        d.rounded_rectangle((300,780,1620,930),26,fill=(6,25,34),outline=v6.GREEN,width=3)
        for j,(label,kind2) in enumerate((("DISTRIBUTED","network"),("PARALLEL","spark"),("VALIDATED","validated"),("FAIL-CLOSED","lock"))):
            x=410+j*315; draw_tech_icon(d,kind2,x,830,34,v6.GREEN); d.text((x+35,816),label,font=v6.font(20,True),fill=v6.TEXT)
        d.text((555,878),"NO MODEL WORK UNTIL THE FEATURE CONTRACT PASSES",font=v6.font(21,True),fill=v6.GREEN)
    return im


def two_generation_frame(t):
    im = v6.bg()
    v6.head(im, "THE MODEL GENERATIONS", "V8 operates the frozen reference; V10 tests whether a challenger can earn promotion")
    d = v6.ImageDraw.Draw(im)
    cards = [
        (
            170, 310, 870, 845, "V8", "FROZEN PRODUCTION MODEL", "Production reference",
            ["Validated Spark features", "Deterministic 100-stock ranking", "Frozen model + feature contract", "Dashboard + paper monitoring"], v6.GREEN,
        ),
        (
            1050, 310, 1750, 845, "V10", "INTEGRATED ML RESEARCH", "Next-generation challenger",
            ["Bounded automatic tuning", "Chronological folds + Cycle 2", "Regime and cost robustness", "Independent confirmation + holdout"], v6.CYAN,
        ),
    ]
    active = min(1, int(t * 2))
    for i, (x0, y0, x1, y1, version, label, sub, bullets, colour) in enumerate(cards):
        outline = colour if i <= active else v6.BORDER
        d.rounded_rectangle((x0, y0, x1, y1), 32, fill=v6.PANEL, outline=outline, width=5)
        d.text((x0 + 46, y0 + 38), version, font=v6.font(82, True), fill=colour)
        if not paste_reference_icon(im,"ai_brain",x1-105,y0+95,82):
            draw_tech_icon(d,"fixed" if version=="V8" else "network",x1-105,y0+95,70,colour)
        d.text((x0 + 46, y0 + 150), label, font=v6.font(25, True), fill=v6.TEXT)
        d.text((x0 + 46, y0 + 202), sub, font=v6.font(20, True), fill=v6.MUTED)
        d.line((x0 + 46, y0 + 255, x1 - 46, y0 + 255), fill=v6.BORDER, width=2)
        for n, bullet in enumerate(bullets):
            yy = y0 + 305 + n * 58
            d.ellipse((x0 + 48, yy + 7, x0 + 64, yy + 23), fill=colour)
            d.text((x0 + 86, yy), bullet, font=v6.font(22, True), fill=v6.TEXT)
        d.rounded_rectangle((x0 + 46, y1 - 82, x1 - 46, y1 - 34), 14, fill=(6, 20, 34), outline=outline, width=2)
        d.text((x0 + 80, y1 - 69), "MACHINE LEARNING / AI", font=v6.font(18, True), fill=colour)
    d.text((305, 920), "V8 OPERATES.  V10 CHALLENGES.  RESEARCH CANNOT SILENTLY CHANGE THE REFERENCE.", font=v6.font(25, True), fill=v6.GOLD)
    return im


def v8_operation_frame(t):
    im = v6.bg()
    v6.head(im, "HOW V8 WORKS", "A frozen, deterministic path from validated features to ranked portfolio signals")
    d = v6.ImageDraw.Draw(im)
    steps = [
        ("VALIDATED", "Spark features", "validated", None),
        ("FIXED MODEL", "Frozen artifacts", "fixed", "ai_brain"),
        ("SCORE", "Each stock", "score", "prediction"),
        ("RANK", "100-stock universe", "rank", "feature_table"),
        ("PUBLISH", "Dashboard + monitor", "publish", "prediction"),
    ]
    xs = [205, 570, 935, 1300, 1665]
    for i, (label, detail, icon, reference) in enumerate(steps):
        on = i <= int(t * len(steps))
        icon_node(im,d,xs[i],515,label,icon,v6.GREEN,on,reference)
        box = d.textbbox((0, 0), detail, font=v6.font(17, True))
        d.text((xs[i] - (box[2] - box[0]) / 2, 625), detail, font=v6.font(17, True), fill=v6.MUTED)
        if i < len(xs) - 1:
            d.line((xs[i] + 130, 515, xs[i + 1] - 130, 515), fill=v6.GREEN, width=4)

    d.rounded_rectangle((165, 735, 1755, 905), 26, fill=(6, 25, 34), outline=v6.GREEN, width=3)
    guards = [
        ("FIXED INPUT CONTRACT", "same feature meaning"),
        ("NO AUTO-RETUNING", "artifacts stay locked"),
        ("FAIL-CLOSED", "no ranking on bad data"),
        ("REPRODUCIBLE", "same inputs, same result"),
    ]
    for i, (label, detail) in enumerate(guards):
        x = 215 + i * 390
        d.text((x, 770), label, font=v6.font(18, True), fill=v6.CYAN)
        d.text((x, 815), detail, font=v6.font(17), fill=v6.TEXT)
    d.text((580, 945), "V8'S RESPONSIBILITY IS CONSISTENCY — NOT EXPERIMENTATION.", font=v6.font(25, True), fill=v6.GREEN)
    return im


def integrated_v10_frame(mode, t):
    im = v6.bg()
    d = v6.ImageDraw.Draw(im)
    if mode == "autotune":
        v6.head(im, "V10 AUTOMATIC-TUNING ENGINE", "Bounded search, chronological evidence and locked confirmation")
        d.ellipse((175, 395, 535, 755), outline=v6.CYAN, width=7)
        d.text((275, 485), "27", font=v6.font(116, True), fill=v6.CYAN)
        d.text((235, 625), "INITIAL CANDIDATES", font=v6.font(20, True), fill=v6.TEXT)
        steps = [("REGISTER", "declared first", "features"), ("5 FOLDS", "chronological", "folds"), ("LOCK", "no retuning", "lock"), ("CONFIRM", "independent", "confirm")]
        for i, (label, detail, icon) in enumerate(steps):
            x = 660 + i * 295
            on = i <= int(t * 4)
            icon_node(im,d,x,565,label,icon,v6.GREEN if i<3 else v6.GOLD,on,"ai_brain" if i==0 else None)
            d.text((x - 62, 685), detail.upper(), font=v6.font(14, True), fill=v6.MUTED)
        d.text((565, 855), "DECLARE  →  EVALUATE  →  LOCK  →  CONFIRM", font=v6.font(30, True), fill=v6.GREEN)
    else:
        v6.head(im, "V10 CYCLE 2 + REGIME RESEARCH", "Expanded deterministic search under the same scientific constraints")
        d.ellipse((150, 395, 500, 745), outline=v6.CYAN, width=7)
        d.text((242, 485), "54", font=v6.font(116, True), fill=v6.CYAN)
        d.text((215, 625), "CANDIDATES", font=v6.font(22, True), fill=v6.TEXT)
        cards = [
            ("TOP N", "10 / 15 / 20", "rank"), ("HOLD", "10 / 20 sessions", "folds"),
            ("EXPOSURE", "trend controlled", "chart"), ("COST", "10 / 30 bps", "cost"),
            ("REGIMES", "conditioned ranking", "regime"), ("GATE", "frozen V8 comparison", "gate"),
        ]
        for i, (label, detail, icon) in enumerate(cards):
            x = 620 + (i % 3) * 390
            y = 340 + (i // 3) * 245
            d.rounded_rectangle((x, y, x + 340, y + 185), 24, fill=v6.PANEL, outline=v6.GREEN if i <= int(t * 6) else v6.BORDER, width=4)
            d.text((x + 26, y + 28), label, font=v6.font(21, True), fill=v6.CYAN)
            draw_tech_icon(d, icon, x + 292, y + 52, 42, v6.GREEN if i <= int(t * 6) else v6.BORDER)
            d.text((x + 26, y + 88), detail, font=v6.font(25, True), fill=v6.TEXT)
        d.text((540, 895), "WIDER SEARCH. SAME RULES. HIGHER STANDARDS.", font=v6.font(29, True), fill=v6.GREEN)
    return im


def model_comparison_frame(t):
    im = v6.bg()
    v6.head(im, "V8 AND V10 — DIFFERENT BY DESIGN", "The active reference and the research challenger have separate responsibilities")
    d = v6.ImageDraw.Draw(im)
    rows = [
        ("ROLE", "Stable platform reference", "Research challenger"),
        ("MODEL CONTRACT", "Frozen and deterministic", "Preregistered bounded search"),
        ("CORE BEHAVIOR", "Score and rank 100 stocks", "Tune, test and stress challengers"),
        ("EVALUATION", "Paper monitoring", "Folds, regimes, costs, holdout"),
        ("CHANGE POLICY", "Never changes silently", "Must pass every gate to advance"),
    ]
    d.rounded_rectangle((120, 285, 1800, 855), 28, fill=v6.PANEL, outline=v6.BORDER, width=3)
    d.text((180, 320), "RESPONSIBILITY", font=v6.font(19, True), fill=v6.MUTED)
    d.text((690, 315), "V8 — FROZEN REFERENCE", font=v6.font(24, True), fill=v6.GREEN)
    d.text((1250, 315), "V10 — CHALLENGER", font=v6.font(24, True), fill=v6.CYAN)
    d.line((160, 370, 1760, 370), fill=v6.BORDER, width=2)
    for i, (label, v8_text, v10_text) in enumerate(rows):
        y = 405 + i * 88
        if i <= int(t * len(rows)):
            d.rounded_rectangle((150, y - 12, 1770, y + 60), 12, fill=(7, 22, 39))
        d.text((180, y), label, font=v6.font(17, True), fill=v6.MUTED)
        d.text((690, y), v8_text, font=v6.font(19, True), fill=v6.TEXT)
        d.text((1250, y), v10_text, font=v6.font(19, True), fill=v6.TEXT)
    d.text((345, 920), "V10 MAY STUDY A BETTER PATH.  IT CANNOT MODIFY V8 OR PROMOTE ITSELF.", font=v6.font(27, True), fill=v6.GOLD)
    return im


_frame_base = v6.frame


def frame_v12(scene, t):
    if scene[0] == "diagram" and scene[1] in {"pipeline", "spark"}:
        return architecture_frame(scene[1], t)
    if scene[0] == "model_lineage_v12":
        return two_generation_frame(t)
    if scene[0] == "v8_operation":
        return v8_operation_frame(t)
    if scene[0] == "v10_integrated":
        return integrated_v10_frame(scene[1], t)
    if scene[0] == "model_comparison":
        return model_comparison_frame(t)
    return _frame_base(scene, t)


v6.frame = frame_v12


# Replace the prior three-generation section with a V8/V10-only story.  The
# rejection explainer is removed even if an older imported generator restores it.
rebuilt = []
inserted = False
for scene in v6.SC:
    old_model_scene = scene[0] == "model_lineage" or (scene[0] == "diagram" and scene[1] in {"v9", "cycle2", "v10"})
    if old_model_scene:
        if not inserted:
            rebuilt.extend([
                (
                    "model_lineage_v12", None,
                    "V8 and V10 are separate machine-learning systems with different responsibilities. V8 is the frozen platform reference: stable, deterministic and protected from research changes. V10 is the integrated research challenger. It can explore new configurations within declared boundaries, while remaining carefully separated from V8 until every required promotion gate has been satisfied.",
                ),
                (
                    "v8_operation", None,
                    "V8 begins after the Spark feature universe passes its validation contract. It applies fixed preprocessing and frozen model artifacts to score each stock, ranks the one-hundred-stock universe cross-sectionally, derives portfolio signals and publishes the result to the scheduler, paper monitor and secure dashboard. The feature definitions, model artifacts and decision rules stay locked. If the data contract is not satisfied, V8 simply waits rather than publishing a ranking. Its responsibility is consistent and reproducible operation.",
                ),
                (
                    "v10_integrated", "autotune",
                    "V10 works differently. It can search, but only inside a bounded, preregistered research contract. Candidate configurations are declared before evaluation, tested across five chronological folds, and compared using fixed metrics. A development winner can be identified and is then carefully locked, unchanged, for independent confirmation. V10 can explore alternatives, while its rules remain fixed once evaluation begins.",
                ),
                (
                    "v10_integrated", "cycle2",
                    "The expanded V10 Cycle Two design evaluates fifty-four deterministic candidates across portfolio size, holding period, trend-controlled exposure and transaction-cost assumptions. It also examines regime-conditioned ranking and robustness. Every candidate is measured against the same fixed standard and compared with frozen V8; research results remain isolated from the active reference.",
                ),
                (
                    "model_comparison", None,
                    "The difference is responsibility. V8 answers: what does the frozen system rank today, using the same validated pipeline and fixed model contract? V10 asks: can a carefully defined challenger demonstrate a reliable improvement across time, market regimes, trading costs and unseen evidence? Preregistered gates, a locked winner, independent confirmation and the untouched future holdout provide the path toward any later promotion. Until that evidence is complete, V8 remains unchanged and V10 remains safely within research.",
                ),
            ])
            inserted = True
        continue
    if scene[0] == "fail":
        continue
    rebuilt.append(scene)

v6.SC[:] = rebuilt

# Give the opening a concise, senior introduction before the platform tour.
for i, scene in enumerate(v6.SC):
    if scene[0] == "founder":
        v6.SC[i] = (
            "founder", None,
            "Meet Meraj Asari, founder, lead engineer and CEO of Data Shepherd Engineering. With nearly two decades in data and cloud engineering, he built Data Shepherd to turn governed market data into transparent, testable artificial intelligence.",
        )
        break


def main():
    old = v6.OUT / "data_shepherd_showcase_v11_16x9.mp4"
    new = v6.OUT / "data_shepherd_showcase_v12_16x9.mp4"
    v11.main()
    if old.exists():
        shutil.move(str(old), str(new))
    print(f"\nV12 DONE: {new}\nopen \"{new}\"")


if __name__ == "__main__":
    main()
