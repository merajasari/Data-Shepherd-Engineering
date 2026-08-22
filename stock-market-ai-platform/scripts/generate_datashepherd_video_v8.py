#!/usr/bin/env python3
"""Data Shepherd Engineering showcase V8.

Polish pass over V7:
- explicitly selects a British female macOS voice (Serena/Kate/Martha preferred)
- masters narration for clearer, more even speech
- enriches real-site scenes with browser framing + cinematic detail panes
- adds restrained section/progress graphics across the film
- preserves V7's richer motion-design scenes and founder treatment
"""
from __future__ import annotations
import importlib.util, math, os, re, shutil, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("dsv7", HERE / "generate_datashepherd_video_v7.py")
v7 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v7)
v6 = v7.v6


def choose_british_female_voice() -> str:
    """Prefer known British female macOS voices and avoid falling back to Daniel/Oliver."""
    requested = os.environ.get("DS_VOICE", "").strip()
    try:
        listing = subprocess.check_output(["say", "-v", "?"], text=True)
    except Exception:
        listing = ""
    if requested:
        return requested
    # Common en_GB female voices across macOS releases.
    for name in ("Serena", "Kate", "Martha", "Stephanie"):
        if re.search(rf"(?m)^{re.escape(name)}\s+en_GB\b", listing) or re.search(rf"(?m)^{re.escape(name)}\s+", listing):
            return name
    # If Apple changes names, take an en_GB voice that is not a known male voice.
    male = {"Daniel", "Oliver", "Arthur", "Eddy", "Reed", "Rocko"}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and "en_GB" in line and parts[0] not in male:
            return parts[0]
    # Female fallback if no UK voice package is installed.
    for name in ("Samantha", "Ava", "Allison"):
        if re.search(rf"(?m)^{re.escape(name)}\s+", listing):
            return name
    return "Samantha"


def british_voice(text, path):
    voice_name = choose_british_female_voice()
    rate = os.environ.get("DS_RATE", "228")
    raw = Path(str(path) + ".raw.aiff")
    subprocess.check_call(["say", "-v", voice_name, "-r", rate, "-o", str(raw), text])
    # Gentle broadcast-style cleanup. Falls back to the raw file if ffmpeg filtering fails.
    try:
        subprocess.check_call([
            v6.ff(), "-y", "-i", str(raw),
            "-af", "highpass=f=75,lowpass=f=12500,acompressor=threshold=-20dB:ratio=2.2:attack=15:release=120,loudnorm=I=-16:TP=-1.5:LRA=7",
            str(path)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raw.unlink(missing_ok=True)
    except Exception:
        shutil.move(str(raw), str(path))
    print(f"Narration voice: {voice_name} (rate {rate} wpm)")

# V6's renderer calls this function directly.
v6.voice = british_voice


# Preserve V7's real-site treatment, then add a cleaner browser/product presentation.
_site_base = v6.site

def polished_site(path, t, title, subtitle):
    im = _site_base(path, t, title, subtitle)
    d = v6.ImageDraw.Draw(im)
    # Browser chrome reinforces that these are genuine product/site surfaces.
    x0, y0, x1 = 120, 205, 1800
    d.rounded_rectangle((x0, y0, x1, y0 + 48), 14, fill=(7, 18, 31), outline=v6.BORDER, width=2)
    for i, col in enumerate(((255,95,86),(255,189,46),(39,201,63))):
        cx = x0 + 25 + i*28
        d.ellipse((cx-7, y0+17, cx+7, y0+31), fill=col)
    d.rounded_rectangle((x0+130, y0+10, x1-25, y0+38), 10, fill=(11,30,49))
    d.text((x0+155, y0+13), "datashepherdengineering.com", font=v6.font(15, True), fill=v6.MUTED)

    # On product/engineering scenes, add two moving detail viewports instead of leaving a full static screenshot.
    if "PRODUCT" in title or "ENGINEERING" in title:
        try:
            src = v6.load(path)
            sw, sh = src.size
            panels = [
                (1280, 700, 1770, 950, .16 + .05*math.sin(t*math.pi), .27, "LIVE DETAIL"),
                (760, 700, 1240, 950, .64 - .04*math.sin(t*math.pi), .66, "SYSTEM DETAIL"),
            ]
            for px0,py0,px1,py1,xb,yb,label in panels:
                pane = v6.cover(src, (px1-px0, py1-py0), 1.75, xb, yb)
                im.paste(pane, (px0,py0))
                d = v6.ImageDraw.Draw(im)
                d.rounded_rectangle((px0,py0,px1,py1), 20, outline=v6.CYAN, width=3)
                d.rounded_rectangle((px0+18,py0+16,px0+165,py0+48), 9, fill=(4,17,30))
                d.text((px0+30,py0+22), label, font=v6.font(13,True), fill=v6.GREEN)
        except Exception:
            pass
    return im

v6.site = polished_site


# Add a subtle film-wide chapter rail without obscuring content.
_frame_base = v6.frame

def polished_frame(scene, t):
    im = _frame_base(scene, t)
    d = v6.ImageDraw.Draw(im)
    try:
        idx = v6.SC.index(scene) + 1
        total = len(v6.SC)
    except Exception:
        idx, total = 1, 13
    # chapter number + film progress
    d.text((94,1018), f"{idx:02d} / {total:02d}", font=v6.font(14,True), fill=v6.MUTED)
    x0, x1, y = 205, 1760, 1028
    d.line((x0,y,x1,y), fill=(25,54,78), width=3)
    progress = ((idx-1) + t) / total
    d.line((x0,y,x0+int((x1-x0)*progress),y), fill=v6.CYAN, width=4)
    return im

v6.frame = polished_frame


def main():
    old = v6.OUT / "data_shepherd_showcase_v7_16x9.mp4"
    new = v6.OUT / "data_shepherd_showcase_v8_16x9.mp4"
    v7.main()
    if old.exists():
        shutil.move(str(old), str(new))
    print(f"\nV8 DONE: {new}\nopen \"{new}\"")

if __name__ == "__main__":
    main()
