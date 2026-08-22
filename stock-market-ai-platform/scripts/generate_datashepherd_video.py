#!/usr/bin/env python3
"""Generate Data Shepherd Engineering promo videos locally.

Outputs:
  outputs/data_shepherd_landing_16x9.mp4
  outputs/data_shepherd_linkedin_1x1.mp4

The generator is intentionally self-contained for macOS:
- installs Pillow + imageio-ffmpeg into the active Python environment if needed
- uses the repository logo when available
- uses macOS `say` for narration when available
- renders original motion-graphics scenes and encodes them with ffmpeg

This is a portfolio/engineering explainer, not a trading-results advertisement.
"""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap


def ensure_packages() -> None:
    missing = []
    try:
        import PIL  # noqa: F401
    except Exception:
        missing.append("pillow")
    try:
        import imageio_ffmpeg  # noqa: F401
    except Exception:
        missing.append("imageio-ffmpeg")
    if missing:
        print("Installing local video dependencies:", ", ".join(missing))
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


ensure_packages()

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402
import imageio_ffmpeg  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)
LOGO = ROOT / "webapp" / "static" / "images" / "data-shepherd-logo.png"

BG = (7, 16, 31)
PANEL = (13, 28, 49)
PANEL2 = (16, 34, 59)
BORDER = (36, 66, 97)
TEXT = (242, 246, 255)
MUTED = (145, 166, 194)
CYAN = (54, 216, 255)
GREEN = (57, 227, 161)
GOLD = (239, 197, 107)
PURPLE = (155, 101, 255)
RED = (255, 102, 128)

SCENES = [
    {
        "duration": 8,
        "eyebrow": "DATA SHEPHERD ENGINEERING",
        "title": "From raw market data\nto governed model evidence",
        "subtitle": "An end-to-end data engineering, machine-learning, and quantitative research platform.",
        "kind": "hero",
    },
    {
        "duration": 10,
        "eyebrow": "DATA ARCHITECTURE",
        "title": "Market data becomes a reproducible pipeline",
        "subtitle": "Ingestion is separated from transformation, analytics, and model-ready features.",
        "kind": "pipeline",
        "nodes": ["TIINGO / IEX", "BRONZE", "SILVER", "GOLD", "FEATURES"],
    },
    {
        "duration": 9,
        "eyebrow": "ENGINEERING DESIGN",
        "title": "The platform is built as layers — not a notebook",
        "subtitle": "Python services, Parquet datasets, validation boundaries, APIs, and web monitoring stay independently testable.",
        "kind": "layers",
    },
    {
        "duration": 10,
        "eyebrow": "MODEL RESEARCH",
        "title": "Experiments evolve. Contracts freeze.",
        "subtitle": "V4 → V5 → research iterations → frozen V8. Each stage keeps its evidence and assumptions explicit.",
        "kind": "models",
    },
    {
        "duration": 11,
        "eyebrow": "FROZEN V8 CONTRACT",
        "title": "DISTANCE_ONLY · Top 10 · 5 sessions",
        "subtitle": "Next-open execution · five cohort offsets · 10 bps modeled trading cost · SPY benchmark.",
        "kind": "contract",
    },
    {
        "duration": 11,
        "eyebrow": "FORWARD HOLDOUT",
        "title": "Decision → Entry → Hold → Exit",
        "subtitle": "The September 1, 2026+ append-only stream is kept separate from development-era evidence.",
        "kind": "holdout",
    },
    {
        "duration": 10,
        "eyebrow": "APPLICATION LAYER",
        "title": "Research becomes a monitored product",
        "subtitle": "Flask APIs, JavaScript dashboards, portfolio views, model comparisons, stream health, and read-only holdout monitoring.",
        "kind": "dashboard",
    },
    {
        "duration": 10,
        "eyebrow": "TECHNOLOGY STACK",
        "title": "Built across data, ML, software, and operations",
        "subtitle": "Python · Pandas · NumPy · Parquet · Flask · JavaScript · Git · GitHub · LaunchAgents · Tiingo",
        "kind": "stack",
    },
    {
        "duration": 9,
        "eyebrow": "WHAT IT IS FOR",
        "title": "A working engineering portfolio —\nnot a black-box prediction demo",
        "subtitle": "Designed to show reproducibility, governance, monitoring, and scientific discipline around real market data.",
        "kind": "final",
    },
]

NARRATION = (
    "I built Data Shepherd Engineering as an end-to-end quantitative research and data engineering platform. "
    "The goal is to show what it takes to turn raw market data into reproducible, testable model evidence. "
    "Market data enters through ingestion services, then moves through bronze, silver, and gold layers before becoming model-ready features. "
    "The system is deliberately separated into services, datasets, validation boundaries, APIs, and monitoring instead of living inside one notebook. "
    "Model research evolves through versioned experiments, while frozen candidates preserve the assumptions that produced their results. "
    "The current frozen V8 contract uses a distance-only ranking, a top-ten equal-weight basket, five-session holds, next-open execution, five cohort offsets, and ten basis points of modeled trading cost. "
    "Its genuine forward holdout begins on September first, twenty twenty-six, and keeps decision, entry, and exit events in a separate append-only evidence stream. "
    "The Flask application turns all of that engineering into an observable product, with model comparisons, portfolio monitoring, market-data health, and read-only holdout diagnostics. "
    "The stack spans Python, Pandas, NumPy, Parquet, Flask, JavaScript, Git, GitHub, macOS services, and Tiingo market data. "
    "Data Shepherd is meant to demonstrate how data engineering, machine learning, software engineering, governance, and quantitative research fit together in one reproducible system."
)


def font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def gradient_bg(size: tuple[int, int]) -> Image.Image:
    w, h = size
    im = Image.new("RGB", size, BG)
    px = im.load()
    for y in range(h):
        for x in range(w):
            gx = x / max(1, w - 1)
            gy = y / max(1, h - 1)
            glow = math.exp(-(((gx - 0.72) ** 2) / 0.08 + ((gy - 0.18) ** 2) / 0.06))
            glow2 = math.exp(-(((gx - 0.15) ** 2) / 0.12 + ((gy - 0.82) ** 2) / 0.12))
            px[x, y] = (
                int(BG[0] + 8 * glow + 4 * glow2),
                int(BG[1] + 25 * glow + 9 * glow2),
                int(BG[2] + 39 * glow + 18 * glow2),
            )
    d = ImageDraw.Draw(im, "RGBA")
    spacing = max(50, w // 28)
    for x in range(0, w, spacing):
        d.line((x, 0, x, h), fill=(54, 216, 255, 12), width=1)
    for y in range(0, h, spacing):
        d.line((0, y, w, y), fill=(54, 216, 255, 10), width=1)
    return im


def rounded(draw, xy, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_logo(im: Image.Image, x: int, y: int, max_w: int):
    if not LOGO.exists():
        return
    logo = Image.open(LOGO).convert("RGBA")
    scale = min(max_w / logo.width, (max_w * 0.58) / logo.height)
    logo = logo.resize((int(logo.width * scale), int(logo.height * scale)), Image.LANCZOS)
    im.alpha_composite(logo, (x, y))


def draw_header(draw, scene, w, h, margin):
    draw.text((margin, margin), scene["eyebrow"], font=font(max(18, w // 90), True), fill=CYAN)
    title_size = max(44, min(86, w // 24))
    draw.multiline_text((margin, int(h * 0.16)), scene["title"], font=font(title_size, True), fill=TEXT, spacing=8)
    sub_y = int(h * 0.16) + (scene["title"].count("\n") + 1) * (title_size + 10) + 18
    wrapped = textwrap.fill(scene["subtitle"], width=72 if w > h else 46)
    draw.multiline_text((margin, sub_y), wrapped, font=font(max(24, w // 60)), fill=MUTED, spacing=8)


def node(draw, cx, cy, label, color, scale=1.0):
    ww, hh = int(210 * scale), int(76 * scale)
    rounded(draw, (cx - ww // 2, cy - hh // 2, cx + ww // 2, cy + hh // 2), int(18 * scale), (*PANEL2, 245), (*color, 200), max(2, int(2 * scale)))
    bbox = draw.textbbox((0, 0), label, font=font(int(22 * scale), True))
    draw.text((cx - (bbox[2]-bbox[0]) / 2, cy - (bbox[3]-bbox[1]) / 2 - 2), label, font=font(int(22 * scale), True), fill=TEXT)


def arrow(draw, x1, y1, x2, y2, color=CYAN, width=4):
    draw.line((x1, y1, x2, y2), fill=(*color, 220), width=width)
    ang = math.atan2(y2-y1, x2-x1)
    a = 14
    p1 = (x2 - a * math.cos(ang - 0.6), y2 - a * math.sin(ang - 0.6))
    p2 = (x2 - a * math.cos(ang + 0.6), y2 - a * math.sin(ang + 0.6))
    draw.polygon([p1, p2, (x2, y2)], fill=(*color, 220))


def render_scene(scene, size: tuple[int, int]) -> Image.Image:
    w, h = size
    base = gradient_bg(size).convert("RGBA")
    draw = ImageDraw.Draw(base, "RGBA")
    margin = int(w * 0.065)
    draw_header(draw, scene, w, h, margin)
    kind = scene["kind"]
    y0 = int(h * 0.56)

    if kind == "hero":
        if LOGO.exists():
            draw_logo(base, margin, int(h * 0.62), int(w * 0.25))
        for i, label in enumerate(["DATA ENGINEERING", "MACHINE LEARNING", "QUANT RESEARCH"]):
            x = int(w * (0.48 + i * 0.16))
            rounded(draw, (x, int(h*.67), x+int(w*.135), int(h*.75)), 18, (*PANEL, 230), (*[CYAN, GREEN, GOLD][i], 150), 2)
            draw.text((x+18, int(h*.695)), label, font=font(max(18, w//95), True), fill=[CYAN, GREEN, GOLD][i])

    elif kind == "pipeline":
        labels = scene["nodes"]
        left, right = margin, w-margin
        xs = [int(left + i*(right-left)/(len(labels)-1)) for i in range(len(labels))]
        colors = [CYAN, PURPLE, CYAN, GREEN, GOLD]
        for i in range(len(xs)-1):
            arrow(draw, xs[i]+90, y0, xs[i+1]-90, y0, colors[i], 4)
        for x, label, c in zip(xs, labels, colors):
            node(draw, x, y0, label, c, 0.82 if w<h else 1.0)

    elif kind == "layers":
        cards = [
            ("INGESTION", "APIs · live streams · raw capture", CYAN),
            ("DATA", "Parquet · bronze / silver / gold", PURPLE),
            ("ML", "features · experiments · frozen artifacts", GOLD),
            ("APP", "Flask · APIs · JavaScript dashboard", GREEN),
        ]
        card_w = int((w - 2*margin - 3*24)/4) if w > h else int(w-2*margin)
        for i,(a,b,c) in enumerate(cards):
            x = margin + i*(card_w+24) if w>h else margin
            y = int(h*.58) if w>h else int(h*.48)+i*int(h*.105)
            rounded(draw,(x,y,x+card_w,y+int(h*.20 if w>h else h*.085)),20,(*PANEL,235),(*c,140),2)
            draw.text((x+20,y+18),a,font=font(max(20,w//85),True),fill=c)
            draw.multiline_text((x+20,y+58),textwrap.fill(b,22),font=font(max(18,w//105)),fill=MUTED,spacing=6)

    elif kind == "models":
        labels = ["V4", "V5", "V6/V7\nresearch", "V8\nFROZEN"]
        colors = [CYAN, GREEN, PURPLE, GOLD]
        xs = [int(w*.16), int(w*.37), int(w*.59), int(w*.82)]
        for i in range(3):
            arrow(draw,xs[i]+92,y0,xs[i+1]-92,y0,colors[i],5)
        for x,l,c in zip(xs,labels,colors):
            node(draw,x,y0,l,c,1.0)
        draw.text((margin,int(h*.79)),"Versioned evidence remains visible; production assumptions do not silently drift.",font=font(max(22,w//72),True),fill=TEXT)

    elif kind == "contract":
        items = [
            ("UNIVERSE", "100 stocks", CYAN),
            ("SELECT", "Top 10", GREEN),
            ("WEIGHT", "10% each", GOLD),
            ("ENTRY", "Next open", CYAN),
            ("HOLD", "5 sessions", PURPLE),
            ("COST", "10 bps", RED),
        ]
        cols = 3
        cw = int((w-2*margin-40)/cols)
        for i,(a,b,c) in enumerate(items):
            row,col=divmod(i,cols)
            x=margin+col*(cw+20); y=int(h*.52)+row*int(h*.16)
            rounded(draw,(x,y,x+cw,y+int(h*.13)),18,(*PANEL,238),(*c,150),2)
            draw.text((x+20,y+18),a,font=font(max(17,w//100),True),fill=c)
            draw.text((x+20,y+52),b,font=font(max(28,w//55),True),fill=TEXT)

    elif kind == "holdout":
        labels=[("DECISION",GOLD),("ENTRY",CYAN),("5-SESSION HOLD",PURPLE),("EXIT",GREEN)]
        xs=[int(w*.16),int(w*.38),int(w*.63),int(w*.84)]
        for i in range(3):arrow(draw,xs[i]+85,y0,xs[i+1]-85,y0,labels[i][1],5)
        for x,(l,c) in zip(xs,labels):node(draw,x,y0,l,c,0.95)
        rounded(draw,(margin,int(h*.76),w-margin,int(h*.86)),20,(239,197,107,18),(239,197,107,90),2)
        draw.text((margin+22,int(h*.79)),"APPEND-ONLY EVIDENCE · DEVELOPMENT HISTORY IS NOT RELABELED AS HOLDOUT",font=font(max(20,w//78),True),fill=GOLD)

    elif kind == "dashboard":
        x0,y=int(w*.50),int(h*.49)
        panel_w,panel_h=int(w*.42),int(h*.36)
        rounded(draw,(x0,y,x0+panel_w,y+panel_h),24,(*PANEL,245),(*BORDER,230),2)
        draw.text((x0+24,y+22),"LIVE ENGINEERING MONITOR",font=font(max(20,w//85),True),fill=CYAN)
        for r in range(3):
            for c in range(3):
                xx=x0+24+c*int(panel_w*.31); yy=y+72+r*int(panel_h*.24)
                rounded(draw,(xx,yy,xx+int(panel_w*.27),yy+int(panel_h*.18)),12,(*PANEL2,240),(*BORDER,180),1)
        # mini equity curve
        pts=[]
        for i in range(8):
            xx=x0+45+i*int(panel_w*.11)
            yy=y+panel_h-45-int((math.sin(i*.8)*.12+i*.06)*panel_h)
            pts.append((xx,yy))
        draw.line(pts,fill=(*GREEN,240),width=5,joint="curve")
        for i,t in enumerate(["Flask API","Portfolio Monitor","Model Comparison","Stream Health"]):
            draw.text((margin,int(h*.53)+i*int(h*.075)),"• "+t,font=font(max(25,w//65),True),fill=[CYAN,GREEN,GOLD,PURPLE][i])

    elif kind == "stack":
        tech=["PYTHON","PANDAS","NUMPY","PARQUET","FLASK","JAVASCRIPT","GIT","GITHUB","TIINGO","LAUNCHAGENTS"]
        chip_w=int(w*.145); chip_h=int(h*.075)
        for i,t in enumerate(tech):
            row=i//5; col=i%5
            x=margin+col*(chip_w+16); y=int(h*.54)+row*(chip_h+20)
            c=[CYAN,GREEN,GOLD,PURPLE,RED][col]
            rounded(draw,(x,y,x+chip_w,y+chip_h),999,(*PANEL,235),(*c,130),2)
            bbox=draw.textbbox((0,0),t,font=font(max(17,w//100),True))
            draw.text((x+(chip_w-(bbox[2]-bbox[0]))/2,y+(chip_h-(bbox[3]-bbox[1]))/2-3),t,font=font(max(17,w//100),True),fill=TEXT)

    elif kind == "final":
        principles=[("REPRODUCIBLE",CYAN),("GOVERNED",GOLD),("MONITORED",GREEN),("TESTABLE",PURPLE)]
        for i,(t,c) in enumerate(principles):
            x=margin+i*int((w-2*margin)/4); y=int(h*.66)
            draw.ellipse((x,y,x+18,y+18),fill=c)
            draw.text((x+32,y-6),t,font=font(max(21,w//76),True),fill=TEXT)
        if LOGO.exists():
            draw_logo(base, int(w*.69), int(h*.76), int(w*.20))
        draw.text((margin,int(h*.86)),"Experimental research platform · Not financial advice",font=font(max(18,w//95)),fill=MUTED)

    return base.convert("RGB")


def run(cmd: list[str]) -> None:
    subprocess.check_call(cmd)


def make_narration(path: Path) -> bool:
    say = shutil.which("say")
    if not say:
        return False
    run([say, "-r", "176", "-o", str(path), NARRATION])
    return path.exists()


def ffmpeg_path() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def make_scene_clip(ffmpeg: str, image_path: Path, duration: float, out_path: Path, size: tuple[int,int], index: int) -> None:
    w,h=size
    # Tiny push-in / drift creates a polished motion-graphics feel without requiring a video editor.
    zoom = "min(zoom+0.00035,1.035)" if index % 2 == 0 else "min(zoom+0.00022,1.025)"
    xexpr = "iw/2-(iw/zoom/2)+sin(on/80)*5"
    yexpr = "ih/2-(ih/zoom/2)+cos(on/95)*4"
    vf = (
        f"scale={w}:{h},"
        f"zoompan=z='{zoom}':x='{xexpr}':y='{yexpr}':d=1:s={w}x{h}:fps=30,"
        f"fade=t=in:st=0:d=0.35,fade=t=out:st={max(0,duration-0.35):.2f}:d=0.35"
    )
    run([ffmpeg,"-y","-loop","1","-i",str(image_path),"-t",str(duration),"-vf",vf,"-r","30","-c:v","libx264","-pix_fmt","yuv420p","-an",str(out_path)])


def concat_clips(ffmpeg: str, clips: list[Path], out_path: Path) -> None:
    concat_file = out_path.with_suffix(".txt")
    concat_file.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips))
    run([ffmpeg,"-y","-f","concat","-safe","0","-i",str(concat_file),"-c","copy",str(out_path)])


def mux_audio(ffmpeg: str, video: Path, narration: Path, out_path: Path) -> None:
    run([ffmpeg,"-y","-i",str(video),"-i",str(narration),"-c:v","copy","-c:a","aac","-b:a","160k","-shortest",str(out_path)])


def build(format_name: str, size: tuple[int,int], output_name: str) -> Path:
    ffmpeg=ffmpeg_path()
    with tempfile.TemporaryDirectory(prefix="datashepherd-video-") as tmp:
        td=Path(tmp)
        clips=[]
        print(f"Rendering {format_name} scenes...")
        for i,scene in enumerate(SCENES):
            img=render_scene(scene,size)
            ip=td/f"scene_{i:02d}.png"; img.save(ip,quality=95)
            cp=td/f"scene_{i:02d}.mp4"
            make_scene_clip(ffmpeg,ip,scene["duration"],cp,size,i)
            clips.append(cp)
        silent=td/"silent.mp4"
        concat_clips(ffmpeg,clips,silent)
        narration=td/"narration.aiff"
        final=OUTPUT_DIR/output_name
        if make_narration(narration):
            print("Adding macOS voice narration...")
            mux_audio(ffmpeg,silent,narration,final)
        else:
            shutil.copy2(silent,final)
            print("macOS `say` was unavailable, so the video was created without narration.")
        return final


def main() -> None:
    p=argparse.ArgumentParser(description="Generate Data Shepherd Engineering landing/LinkedIn promo videos")
    p.add_argument("--format",choices=["landscape","square","both"],default="both")
    args=p.parse_args()
    outputs=[]
    if args.format in ("landscape","both"):
        outputs.append(build("16:9 landing",(1920,1080),"data_shepherd_landing_16x9.mp4"))
    if args.format in ("square","both"):
        outputs.append(build("1:1 LinkedIn",(1080,1080),"data_shepherd_linkedin_1x1.mp4"))
    print("\nDONE")
    for out in outputs:
        print(out)
    print("\nTip: the 16:9 file is ideal for the landing page; the square file is optimized for LinkedIn feed viewing.")


if __name__ == "__main__":
    main()
