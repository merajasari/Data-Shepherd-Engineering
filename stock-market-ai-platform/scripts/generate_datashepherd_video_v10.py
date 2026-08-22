#!/usr/bin/env python3
"""Data Shepherd Engineering showcase V10.

V10 includes the retained V9 presentation polish:
- more human British-female narration using sentence-by-sentence pace variation
- calmer default pace (~194 wpm average)
- a redesigned phone screen showing live charts instead of "built on my phone"
- a clearer, evidence-led failed-confirmation scene with no giant red box
- preserves the retained founder, product, Spark, V10 research, and holdout visuals
"""
from __future__ import annotations
import importlib.util, math, os, re, shutil, subprocess, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("dsv8", HERE / "generate_datashepherd_video_v8.py")
v8 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v8)
v7 = v8.v7
v6 = v8.v6


def choose_voice() -> str:
    requested = os.environ.get("DS_VOICE", "").strip()
    if requested:
        return requested
    try:
        listing = subprocess.check_output(["say", "-v", "?"], text=True)
    except Exception:
        listing = ""
    # Kate often has a softer, less synthetic cadence than Serena on recent macOS builds.
    # Fall back through British female voices only before using a non-UK female voice.
    for name in ("Kate", "Serena", "Martha", "Stephanie"):
        if re.search(rf"(?m)^{re.escape(name)}\s+", listing):
            return name
    male = {"Daniel", "Oliver", "Arthur", "Eddy", "Reed", "Rocko"}
    for line in listing.splitlines():
        if "en_GB" in line:
            name = line.split()[0]
            if name not in male:
                return name
    return "Samantha"


def _sentences(text: str):
    # Keep abbreviations simple and preserve punctuation so Apple's voice engine can phrase naturally.
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def human_voice(text, path):
    """Build narration as separately spoken phrases with subtle pace variation and real pauses."""
    voice_name = choose_voice()
    base = int(os.environ.get("DS_RATE", "194"))
    tmp = Path(tempfile.mkdtemp(prefix="ds_voice_"))
    try:
        segments = []
        rates = [base-5, base, base+3, base-2, base+1]
        for i, sentence in enumerate(_sentences(text)):
            # Add commas where a human narrator would naturally take a breath.
            sentence = sentence.replace("Data Shepherd Engineering", "Data Shepherd Engineering,")
            sentence = sentence.replace("Data Shepherd rejected it", "Data Shepherd rejected it,")
            sentence = sentence.replace("Frozen V8", "Frozen V8,")
            seg = tmp / f"seg_{i:02d}.aiff"
            subprocess.check_call(["say", "-v", voice_name, "-r", str(rates[i % len(rates)]), "-o", str(seg), sentence])
            segments.append(seg)
            if i < len(_sentences(text)) - 1:
                silence = tmp / f"sil_{i:02d}.aiff"
                # Small natural pause. Longer after the most consequential statements.
                pause = 0.20 if any(k in sentence.lower() for k in ("failed", "rejected", "future", "holdout")) else 0.12
                subprocess.check_call([
                    v6.ff(), "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", str(pause),
                    "-c:a", "pcm_s16be", str(silence)
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                segments.append(silence)

        concat = tmp / "list.txt"
        concat.write_text("".join(f"file '{p}'\n" for p in segments))
        raw = tmp / "joined.aiff"
        subprocess.check_call([
            v6.ff(), "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16be", str(raw)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Very light mastering only. Over-processing was making the voice feel more synthetic.
        filters = (
            "highpass=f=55,lowpass=f=13500,"
            "equalizer=f=170:t=q:w=1.0:g=1.2,"
            "equalizer=f=3500:t=q:w=1.4:g=-0.8,"
            "acompressor=threshold=-21dB:ratio=1.55:attack=28:release=220:makeup=1.0,"
            "loudnorm=I=-16:TP=-1.5:LRA=8"
        )
        subprocess.check_call([v6.ff(), "-y", "-i", str(raw), "-af", filters, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"Narration voice: {voice_name} (humanised British female, ~{base} wpm)")

v6.voice = human_voice


# Preserve the current site renderer, then repair the outdated phone content in the overview scene.
_site_base = v6.site

def _draw_phone_dashboard(im, t):
    d = v6.ImageDraw.Draw(im)
    # Covers the old phone artwork/text within the platform overview screenshot.
    x0,y0,x1,y1 = 400,650,635,965
    d.rounded_rectangle((x0,y0,x1,y1),28,fill=(3,8,15),outline=(75,91,112),width=5)
    d.rounded_rectangle((x0+12,y0+18,x1-12,y1-18),22,fill=(5,18,31),outline=v6.BORDER,width=2)
    d.rounded_rectangle((x0+82,y0+8,x0+153,y0+17),5,fill=(60,70,85))
    d.text((x0+34,y0+40),"PORTFOLIO",font=v6.font(15,True),fill=v6.CYAN)
    d.text((x0+34,y0+66),"$100,211.97",font=v6.font(21,True),fill=v6.TEXT)
    d.text((x0+34,y0+94),"+0.21%",font=v6.font(15,True),fill=v6.GREEN)
    # Main equity curve
    pts=[]
    for i in range(80):
        xx=x0+26+i*2.25
        yy=y0+190-int(25*math.sin(i*.10))-int(i*.45)-int(7*math.sin(i*.33+t*3))
        pts.append((xx,yy))
    d.line(pts,fill=v6.GREEN,width=3)
    d.line((x0+26,y0+200,x1-26,y0+200),fill=(30,55,77),width=1)
    # Mini model bars
    d.text((x0+28,y0+220),"MODEL SIGNALS",font=v6.font(11,True),fill=v6.MUTED)
    vals=[.82,.73]
    labs=['V8','V10']
    for i,(lab,val) in enumerate(zip(labs,vals)):
        yy=y0+250+i*25; d.text((x0+28,yy),lab,font=v6.font(10,True),fill=v6.TEXT)
        d.rounded_rectangle((x0+65,yy+2,x1-28,yy+12),5,fill=(20,43,62))
        d.rounded_rectangle((x0+65,yy+2,x0+65+int((x1-x0-95)*val),yy+12),5,fill=v6.CYAN if i==2 else v6.GREEN)
    d.text((x0+30,y1-42),"LIVE VIEW",font=v6.font(11,True),fill=v6.MUTED)


def polished_site(path, t, title, subtitle):
    im = _site_base(path, t, title, subtitle)
    if "REAL PLATFORM" in title:
        _draw_phone_dashboard(im, t)
    return im

v6.site = polished_site


# Replace the confirmation-failure visual with an evidence explanation instead of a large red warning box.
def confirmation_explainer(t):
    im = v6.bg(); v6.head(im, "WHY THE WINNER WAS REJECTED", "Confirmation is a separate gate — not a second chance to tune")
    d = v6.ImageDraw.Draw(im)

    # Left: development winner becomes immutable.
    d.rounded_rectangle((120,300,540,820),28,fill=v6.PANEL,outline=v6.CYAN,width=4)
    d.text((165,345),"DEVELOPMENT",font=v6.font(20,True),fill=v6.MUTED)
    d.text((165,390),"WINNER",font=v6.font(42,True),fill=v6.TEXT)
    d.ellipse((220,485,440,705),outline=v6.GOLD,width=7)
    d.text((278,545),"LOCKED",font=v6.font(27,True),fill=v6.GOLD)
    d.text((170,750),"No more tuning",font=v6.font(20,True),fill=v6.GREEN)

    # Centre: what confirmation actually asks.
    d.rounded_rectangle((610,300,1280,820),28,fill=(7,20,35),outline=v6.BORDER,width=3)
    d.text((655,345),"INDEPENDENT CONFIRMATION",font=v6.font(22,True),fill=v6.TEXT)
    checks=[
        ("Calendar-year stability", "TEST"),
        ("SPY trend / volatility regimes", "TEST"),
        ("Transaction-cost stress", "TEST"),
        ("Predeclared acceptance gates", "NOT ALL SATISFIED"),
    ]
    for i,(lab,status) in enumerate(checks):
        yy=420+i*92
        d.ellipse((655,yy+8,675,yy+28),fill=v6.GREEN if i<3 else v6.RED)
        d.text((695,yy),lab,font=v6.font(20,True),fill=v6.TEXT)
        d.text((695,yy+35),status,font=v6.font(15,True),fill=v6.GREEN if i<3 else v6.RED)

    # Right: restrained outcome card.
    d.rounded_rectangle((1350,365,1810,755),28,fill=(24,7,12),outline=(110,40,50),width=3)
    d.text((1400,410),"OUTCOME",font=v6.font(18,True),fill=v6.MUTED)
    d.text((1400,465),"NOT",font=v6.font(50,True),fill=v6.RED)
    d.text((1400,530),"CONFIRMED",font=v6.font(50,True),fill=v6.RED)
    d.line((1400,615,1745,615),fill=(92,36,47),width=2)
    d.text((1400,650),"V8 stays frozen",font=v6.font(22,True),fill=v6.GREEN)
    d.text((1400,690),"No runner-up swap",font=v6.font(18,True),fill=v6.TEXT)

    d.text((370,900),"A FAILED CONFIRMATION IS A VALID SCIENTIFIC RESULT.",font=v6.font(30,True),fill=v6.CYAN)
    return im

v6.fail = confirmation_explainer

# Rewrite only the failed-confirmation narration to explain the logic more clearly.
for i, scene in enumerate(v6.SC):
    if scene[0] == 'fail':
        v6.SC[i] = (
            'fail', None,
            "The development winner was selected using the walk-forward research process, and then locked. Confirmation asked a different question: does that fixed winner remain acceptable across calendar years, market regimes, and transaction-cost stress? One or more of the predeclared confirmation gates were not satisfied. So the result was not confirmed. The model was rejected, there was no runner-up substitution, and frozen V8 remained the production reference."
        )
        break


def main():
    old = v6.OUT / "data_shepherd_showcase_v8_16x9.mp4"
    new = v6.OUT / "data_shepherd_showcase_v10_16x9.mp4"
    v8.main()
    if old.exists():
        shutil.move(str(old), str(new))
    print(f"\nV10 DONE: {new}\nopen \"{new}\"")

if __name__ == "__main__":
    main()
