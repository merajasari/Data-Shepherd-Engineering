#!/usr/bin/env python3
"""Generate the Data Shepherd Engineering V2 showcase video.

This version reflects the current stock-market platform architecture:
- production Spark feature backend with fail-closed parity/materialization gates
- frozen V8 production/reference model and September forward holdout
- bounded V9 automatic tuning, purged walk-forward evaluation, fixed-winner confirmation
- active risk-controlled V9 Cycle 2 research
- separate V10 regime-conditioned research, prospective confirmation, Nov-2 formal holdout

The video deliberately distinguishes production, research, confirmation, and untouched holdout evidence.
It also keeps brokerage execution out of scope.

Outputs:
  outputs/data_shepherd_showcase_v2_16x9.mp4
  outputs/data_shepherd_showcase_v2_linkedin_1x1.mp4

Presenter options:
- Default: an original illustrated presenter with a macOS British English voice.
- To use your own still photo: set PRESENTER_IMAGE=/absolute/path/to/photo.png
- To use your own recorded narration for the WHOLE video, set VOICE_FILE=/absolute/path/to/audio.wav
  (When VOICE_FILE is supplied the per-scene macOS narration is disabled.)
"""
from __future__ import annotations

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
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


ensure_packages()

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402
import imageio_ffmpeg  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)
LOGO = ROOT / "webapp" / "static" / "images" / "data-shepherd-logo.png"

BG = (6, 14, 28)
PANEL = (12, 27, 48)
PANEL2 = (18, 37, 63)
BORDER = (45, 76, 108)
TEXT = (244, 248, 255)
MUTED = (151, 171, 198)
CYAN = (60, 219, 255)
GREEN = (65, 229, 166)
GOLD = (240, 198, 105)
PURPLE = (164, 112, 255)
ORANGE = (255, 167, 92)
RED = (255, 102, 126)

SCENES = [
    {
        "title": "I built Data Shepherd Engineering",
        "eyebrow": "END-TO-END DATA + ML PLATFORM",
        "body": "A production-minded market-data, machine-learning and model-governance platform — built to make evidence reproducible, inspectable and hard to fool.",
        "kind": "hero",
        "narration": "I built Data Shepherd Engineering as an end-to-end data and machine-learning platform for market research. The goal is not a flashy prediction demo. It is a system where data, models, evidence, and production behaviour are separated and governed on purpose.",
    },
    {
        "title": "The data path is engineered first",
        "eyebrow": "MARKET DATA → BRONZE → GOLD → FEATURES",
        "body": "Live and end-of-day feeds move through validated, reproducible transformations before any model gets to use them.",
        "kind": "pipeline",
        "nodes": ["MARKET FEEDS", "BRONZE", "SILVER", "GOLD", "FEATURES"],
        "narration": "Everything starts with the data path. Market feeds are ingested, validated, transformed through Bronze, Silver and Gold layers, and only then exposed as model-ready features. The model never gets to quietly redefine its own inputs.",
    },
    {
        "title": "Spark is now part of the stock production path",
        "eyebrow": "PYSPARK + PARQUET + FAIL-CLOSED VALIDATION",
        "body": "The platform supports a Spark feature backend, routes downstream consumers through a shared source contract, and validates the full materialized universe before model work continues.",
        "kind": "spark",
        "stats": [("101 / 101", "materialized output gate"), ("100 / 100", "V8 rankable universe"), ("Pandas ↔ Spark", "parity contract")],
        "narration": "The stock platform now has a real PySpark feature backend. Downstream consumers use a shared Pandas-or-Spark contract, and the scheduler fails closed if the Spark materialization is incomplete or inconsistent. The latest production cutover validated one hundred and one of one hundred and one outputs before downstream work continued.",
    },
    {
        "title": "V8 is frozen on purpose",
        "eyebrow": "PRODUCTION REFERENCE + FORWARD EVIDENCE",
        "body": "100-stock universe · Top 10 · 5-session hold · next-open execution assumption · fixed 10-bps cost · no retuning inside the frozen evidence stream.",
        "kind": "v8",
        "narration": "V8 is the frozen production reference model. It ranks the full one-hundred-stock universe, selects the top ten, uses a five-session hold and a next-open execution assumption, and keeps the ten-basis-point cost contract fixed. Its September forward holdout is an append-only evidence stream, not another tuning set.",
    },
    {
        "title": "V9 automates research — not hindsight",
        "eyebrow": "BOUNDED AUTOMATIC TUNING",
        "body": "Candidate generation is deterministic and immutable. Cycle 1 registered 27 challengers before evaluation and assigned content-derived candidate IDs.",
        "kind": "registry",
        "narration": "V9 adds bounded automatic model research. Cycle one registered twenty-seven deterministic challenger configurations before evaluation. Candidate identity is content-derived and immutable, which means the search space is declared first instead of rewritten after the results are known.",
    },
    {
        "title": "Walk-forward evaluation is purged and chronological",
        "eyebrow": "5 FOLDS · 10-SESSION PURGE · COSTED TURNOVER",
        "body": "Candidates are evaluated over chronological development folds with purge enforcement, portfolio turnover, transaction costs and holding-period-specific annualization.",
        "kind": "folds",
        "narration": "Those candidates are then evaluated through five chronological walk-forward folds with a ten-session purge. Exits have to remain inside the validation fold, turnover is modelled, costs are charged, and each holding period gets its own annualisation. That makes the evaluation much harder to game.",
    },
    {
        "title": "A winner can fail — and the system accepts it",
        "eyebrow": "FIXED WINNER CONFIRMATION",
        "body": "The selected V9 development winner was locked before confirmation. No runner-up substitution. A NOT_CONFIRMED result leaves V8 unchanged.",
        "kind": "gate",
        "narration": "The selected V9 development winner is locked before confirmation. The confirmation gate tests years, market regimes and higher trading-cost stress. If it fails, the system does not swap in the runner-up. A not-confirmed result is accepted, and V8 stays unchanged.",
    },
    {
        "title": "Cycle 2 expands risk controls without relaxing the gate",
        "eyebrow": "ACTIVE V9 RESEARCH",
        "body": "54 predeclared candidates · Top 10/15/20 · 10/20-session holds · no overlay / half exposure / cash below SPY SMA200 · no leverage · no shorting.",
        "kind": "cycle2",
        "narration": "The next V9 research cycle is now expanding the search in a controlled way. Fifty-four candidates are predeclared across broader portfolio sizes, longer holds, and explicit SPY trend-based exposure rules. There is still no leverage, no shorting, and the previous confirmation standards are not weakened.",
    },
    {
        "title": "V10 is a separate challenger research track",
        "eyebrow": "REGIME-CONDITIONED RANKING",
        "body": "Phase 1 discovery → Phase 2 robustness → Phase 3 fixed-contract simulation → Phase 4 pre-freeze gate → prospective confirmation versus frozen V8.",
        "kind": "v10",
        "narration": "V10 is separate again. It explores regime-conditioned ranking through four development phases, then runs prospective confirmation against frozen V8. Its formal holdout begins on November second, twenty twenty-six, and the code refuses to score through that boundary. Research, confirmation and holdout evidence remain distinct.",
    },
    {
        "title": "What the project is meant to demonstrate",
        "eyebrow": "DATA ENGINEERING + MLOPS + QUANT RESEARCH",
        "body": "Distributed processing. Reproducible pipelines. Automatic experimentation. Model governance. Forward evidence. Operational monitoring. One system, with explicit boundaries.",
        "kind": "close",
        "narration": "That is what Data Shepherd Engineering is meant to demonstrate: distributed data engineering, reproducible pipelines, automatic experimentation, model governance, forward evidence and production monitoring working together as one system. It is an engineering project first — and every result has to earn its way through the pipeline.",
    },
]


def font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def wrap(text: str, chars: int) -> str:
    return "\n".join(textwrap.wrap(text, chars))


def draw_grid(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    w, h = img.size
    for x in range(0, w, max(80, w // 18)):
        d.line((x, 0, x, h), fill=(13, 29, 49), width=1)
    for y in range(0, h, max(70, h // 14)):
        d.line((0, y, w, y), fill=(13, 29, 49), width=1)


def presenter_image(size: tuple[int, int]) -> Image.Image:
    supplied = os.environ.get("PRESENTER_IMAGE")
    if supplied and Path(supplied).exists():
        src = Image.open(supplied).convert("RGB")
        sw, sh = src.size
        tw, th = size
        scale = max(tw / sw, th / sh)
        src = src.resize((int(sw * scale), int(sh * scale)), Image.Resampling.LANCZOS)
        x = (src.width - tw) // 2
        y = max(0, (src.height - th) // 3)
        return src.crop((x, y, x + tw, y + th))

    # Original illustrated presenter: neutral, professional, intentionally non-identifiable.
    tw, th = size
    img = Image.new("RGB", size, PANEL)
    d = ImageDraw.Draw(img)
    d.ellipse((tw * .22, th * .05, tw * .78, th * .53), fill=(185, 136, 105))
    d.pieslice((tw * .18, th * .00, tw * .82, th * .45), 180, 360, fill=(40, 32, 31))
    d.ellipse((tw * .35, th * .25, tw * .40, th * .30), fill=(26, 27, 31))
    d.ellipse((tw * .60, th * .25, tw * .65, th * .30), fill=(26, 27, 31))
    d.arc((tw * .42, th * .31, tw * .58, th * .42), 10, 170, fill=(115, 66, 61), width=max(2, tw // 80))
    d.polygon([(tw*.05, th), (tw*.28, th*.55), (tw*.72, th*.55), (tw*.95, th)], fill=(18, 40, 67))
    d.polygon([(tw*.40, th*.55), (tw*.50, th*.76), (tw*.60, th*.55)], fill=(234, 239, 245))
    d.line((tw*.5, th*.76, tw*.5, th), fill=CYAN, width=max(2, tw//100))
    return img


def rounded(d, box, radius=22, fill=PANEL, outline=BORDER, width=2):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_presenter_panel(img: Image.Image, square: bool) -> None:
    d = ImageDraw.Draw(img)
    w, h = img.size
    pw = int(w * (0.28 if not square else 0.34))
    ph = int(h * (0.55 if not square else 0.38))
    x = w - pw - int(w * .045)
    y = int(h * (.21 if not square else .56))
    rounded(d, (x-8, y-8, x+pw+8, y+ph+8), radius=28, fill=(9, 21, 39), outline=CYAN, width=2)
    p = presenter_image((pw, ph))
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,pw,ph), radius=22, fill=255)
    img.paste(p, (x,y), mask)
    d.rounded_rectangle((x+18, y+ph-50, x+pw-18, y+ph-16), radius=14, fill=(6, 15, 29))
    d.text((x+32, y+ph-45), "DATA SHEPHERD · PRESENTER", font=font(max(16, w//95), True), fill=CYAN)
    # tiny voice waveform motif
    base = y+ph-68
    for i, amp in enumerate([8,16,24,13,20,10,18,7]):
        xx = x+pw-120+i*11
        d.line((xx, base-amp//2, xx, base+amp//2), fill=GREEN, width=3)


def draw_scene(scene: dict, size: tuple[int,int], index: int) -> Image.Image:
    w, h = size
    square = w == h
    img = Image.new("RGB", size, BG)
    draw_grid(img)
    d = ImageDraw.Draw(img)

    # Accent glow
    glow = Image.new("RGBA", size, (0,0,0,0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((int(w*.03), int(h*.03), int(w*.45), int(h*.62)), fill=(25,145,215,32))
    glow = glow.filter(ImageFilter.GaussianBlur(max(30, w//30)))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    d = ImageDraw.Draw(img)

    margin = int(w * .055)
    content_right = int(w * (.66 if not square else .92))
    d.text((margin, int(h*.075)), scene["eyebrow"], font=font(max(17, w//80), True), fill=CYAN)
    title_size = max(38, w//27) if not square else max(34, w//23)
    d.multiline_text((margin, int(h*.13)), wrap(scene["title"], 34 if not square else 28), font=font(title_size, True), fill=TEXT, spacing=8)
    body_y = int(h * (.31 if not square else .28))
    body_width_chars = 56 if not square else 40
    d.multiline_text((margin, body_y), wrap(scene["body"], body_width_chars), font=font(max(22, w//55)), fill=MUTED, spacing=8)

    kind = scene["kind"]
    top = int(h * (.50 if not square else .41))
    left = margin
    right = content_right
    bottom = int(h * (.88 if not square else .53))

    if kind == "pipeline":
        nodes = scene["nodes"]
        gap = (right-left) / len(nodes)
        y = top + (bottom-top)//2
        for i, n in enumerate(nodes):
            cx = int(left + gap*(i+.5))
            if i:
                px = int(left + gap*(i-.5))
                d.line((px+45, y, cx-45, y), fill=CYAN, width=4)
                d.polygon([(cx-45,y),(cx-58,y-8),(cx-58,y+8)], fill=CYAN)
            rounded(d, (cx-62,y-36,cx+62,y+36), radius=16, fill=PANEL2)
            tw = d.textbbox((0,0), n, font=font(max(14,w//95),True))[2]
            d.text((cx-tw/2,y-10),n,font=font(max(14,w//95),True),fill=TEXT)
    elif kind == "spark":
        stats = scene["stats"]
        cw = int((right-left-30)/3)
        for i,(num,label) in enumerate(stats):
            x0=left+i*(cw+15)
            rounded(d,(x0,top,x0+cw,bottom),radius=20,fill=PANEL2)
            d.text((x0+18,top+22),num,font=font(max(25,w//45),True),fill=GREEN if i<2 else CYAN)
            d.multiline_text((x0+18,top+76),wrap(label,20),font=font(max(15,w//90)),fill=MUTED,spacing=5)
    elif kind in {"v8","registry","gate","cycle2","v10","close","hero"}:
        labels = {
            "v8": ["100 STOCKS", "TOP 10", "5 SESSIONS", "10 BPS"],
            "registry": ["27 CANDIDATES", "IMMUTABLE IDS", "DECLARED FIRST"],
            "gate": ["WINNER LOCKED", "STRESS TESTED", "FAIL = NO CHANGE"],
            "cycle2": ["54 CANDIDATES", "RISK CONTROLS", "NO LEVERAGE"],
            "v10": ["PHASES 1–4", "PROSPECTIVE", "NOV 2 HOLDOUT"],
            "close": ["SPARK", "AUTO-TUNING", "GOVERNANCE", "MONITORING"],
            "hero": ["DATA", "MODELS", "EVIDENCE", "PRODUCTION"],
        }[kind]
        n=len(labels)
        cw=int((right-left-(n-1)*14)/n)
        for i,label in enumerate(labels):
            x0=left+i*(cw+14)
            rounded(d,(x0,top,x0+cw,bottom),radius=18,fill=PANEL2)
            d.text((x0+16,top+24),str(i+1).zfill(2),font=font(max(18,w//70),True),fill=GOLD)
            d.multiline_text((x0+16,top+68),wrap(label,14),font=font(max(15,w//82),True),fill=TEXT,spacing=5)
    elif kind == "folds":
        y=(top+bottom)//2
        for i in range(5):
            x0=int(left+(right-left)*i/5)
            x1=int(left+(right-left)*(i+1)/5)-8
            rounded(d,(x0,y-48,x1,y+48),radius=12,fill=PANEL2)
            d.text((x0+15,y-10),f"FOLD {i+1}",font=font(max(14,w//95),True),fill=TEXT)
        d.text((left, bottom+12),"PURGE → VALIDATE → EXIT INSIDE FOLD",font=font(max(14,w//90),True),fill=GREEN)

    # Footer/progress
    d.line((margin, int(h*.94), w-margin, int(h*.94)), fill=BORDER, width=2)
    d.line((margin, int(h*.94), margin+int((w-2*margin)*(index+1)/len(SCENES)), int(h*.94)), fill=CYAN, width=4)
    d.text((margin, int(h*.955)), "DATA SHEPHERD ENGINEERING · EXPERIMENTAL RESEARCH PLATFORM · NOT FINANCIAL ADVICE", font=font(max(12,w//110)), fill=MUTED)

    draw_presenter_panel(img, square)
    return img


def pick_voice() -> str | None:
    if not shutil.which("say"):
        return None
    try:
        names = subprocess.check_output(["say", "-v", "?"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    available = {line.split()[0] for line in names.splitlines() if line.strip()}
    for name in ["Daniel", "Serena", "Oliver", "Samantha"]:
        if name in available:
            return name
    return None


def run(cmd: list[str]) -> None:
    subprocess.check_call(cmd)


def audio_duration(ffmpeg: str, path: Path) -> float:
    ffprobe = str(Path(ffmpeg).with_name("ffprobe"))
    if Path(ffprobe).exists():
        try:
            out = subprocess.check_output([ffprobe,"-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],text=True)
            return float(out.strip())
        except Exception:
            pass
    return 9.0


def build(format_name: str, size: tuple[int,int], target: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    voice = pick_voice()
    custom_voice = os.environ.get("VOICE_FILE")

    with tempfile.TemporaryDirectory(prefix="datashepherd-v2-") as td:
        tmp = Path(td)
        clips=[]
        for i,scene in enumerate(SCENES):
            png=tmp/f"scene_{i:02d}.png"
            draw_scene(scene,size,i).save(png)
            wav=tmp/f"scene_{i:02d}.aiff"
            if custom_voice:
                # Per-scene narration is suppressed when a whole-video custom voice file is provided.
                duration=9.0
                clip=tmp/f"scene_{i:02d}.mp4"
                run([ffmpeg,"-y","-loop","1","-i",str(png),"-t",str(duration),"-vf","fade=t=in:st=0:d=0.35,fade=t=out:st=8.55:d=0.35,format=yuv420p","-r","30","-c:v","libx264","-crf","20",str(clip)])
            else:
                if voice:
                    subprocess.check_call(["say","-v",voice,"-r","184","-o",str(wav),scene["narration"]])
                    duration=max(7.5,audio_duration(ffmpeg,wav)+0.7)
                else:
                    duration=9.0
                clip=tmp/f"scene_{i:02d}.mp4"
                if wav.exists():
                    run([ffmpeg,"-y","-loop","1","-i",str(png),"-i",str(wav),"-t",str(duration),"-vf",f"fade=t=in:st=0:d=0.35,fade=t=out:st={max(0,duration-0.35):.2f}:d=0.35,format=yuv420p","-af",f"afade=t=in:st=0:d=0.18,afade=t=out:st={max(0,duration-0.25):.2f}:d=0.25","-r","30","-c:v","libx264","-crf","20","-c:a","aac","-b:a","160k","-shortest",str(clip)])
                else:
                    run([ffmpeg,"-y","-loop","1","-i",str(png),"-t",str(duration),"-vf","format=yuv420p","-r","30","-c:v","libx264","-crf","20",str(clip)])
            clips.append(clip)

        listing=tmp/"concat.txt"
        listing.write_text("\n".join(f"file '{p.as_posix()}'" for p in clips)+"\n")
        silent_or_narrated=tmp/"assembled.mp4"
        run([ffmpeg,"-y","-f","concat","-safe","0","-i",str(listing),"-c","copy",str(silent_or_narrated)])

        if custom_voice:
            run([ffmpeg,"-y","-i",str(silent_or_narrated),"-i",custom_voice,"-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac","-b:a","160k","-shortest",str(target)])
        else:
            shutil.copy2(silent_or_narrated,target)

    print(target)


def main() -> None:
    build("landing",(1920,1080),OUT/"data_shepherd_showcase_v2_16x9.mp4")
    build("linkedin",(1080,1080),OUT/"data_shepherd_showcase_v2_linkedin_1x1.mp4")
    print("\nDONE")
    print("Landing:",OUT/"data_shepherd_showcase_v2_16x9.mp4")
    print("LinkedIn:",OUT/"data_shepherd_showcase_v2_linkedin_1x1.mp4")
    print("\nPresenter: set PRESENTER_IMAGE=/path/to/your/photo.png to use your own still image.")
    print("Narration: set VOICE_FILE=/path/to/your/recording.wav to use your own full narration recording.")


if __name__ == "__main__":
    main()
