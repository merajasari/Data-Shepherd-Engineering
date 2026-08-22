#!/usr/bin/env python3
"""Data Shepherd Engineering V7 — richer motion treatment + 1.25x narration."""
from __future__ import annotations
import importlib.util, math, os, shutil, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("dsv6", HERE / "generate_datashepherd_video_v6.py")
v6 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v6)

# Keep immutable references to the original V6 renderers before monkey-patching.
# Without these, the richer wrappers call themselves recursively after assignment.
_old_diagram = v6.diagram
_old_gate = v6.gate
_old_fail = v6.fail
_old_hold = v6.hold
_old_site = v6.site

# Requested: narration 25% faster than V6 (182 -> 228 wpm).
def voice(text, path):
    try:
        voices = subprocess.check_output(["say", "-v", "?"], text=True)
    except Exception:
        voices = ""
    voice_name = "Serena" if "Serena" in voices else ("Kate" if "Kate" in voices else ("Daniel" if "Daniel" in voices else "Samantha"))
    subprocess.check_call(["say", "-v", voice_name, "-r", "228", "-o", str(path), text])
v6.voice = voice


def pulse(t, phase=0.0):
    return .5 + .5 * math.sin((t * 2 * math.pi) + phase)


def add_hud(im, t, label="LIVE ENGINEERING SYSTEM"):
    d = v6.ImageDraw.Draw(im)
    d.rounded_rectangle((1450, 42, 1840, 112), 18, fill=(7, 22, 39), outline=v6.BORDER, width=2)
    d.ellipse((1480, 67, 1498, 85), fill=v6.GREEN)
    d.text((1512, 59), label, font=v6.font(17, True), fill=v6.MUTED)
    x0, y0, x1 = 110, 1000, 1810
    d.line((x0, y0, x1, y0), fill=(24, 57, 82), width=2)
    for i in range(12):
        x = x0 + int(((t * 1.4 + i / 12) % 1.0) * (x1 - x0))
        r = 4 + int(3 * pulse(t, i))
        d.ellipse((x-r, y0-r, x+r, y0+r), fill=v6.CYAN if i % 3 else v6.GREEN)
    return im


def data_particles(im, t, y=590, start=350, end=1570, count=16, col=None):
    d = v6.ImageDraw.Draw(im); col = col or v6.CYAN
    for i in range(count):
        u = (t * 1.7 + i / count) % 1.0
        x = int(start + u * (end-start))
        r = 3 + (i % 3)
        d.ellipse((x-r, y-r, x+r, y+r), fill=col)


def richer_diagram(kind, t):
    im = _old_diagram(kind, t)
    d = v6.ImageDraw.Draw(im)
    if kind == "pipeline":
        data_particles(im, t, 590, 350, 1490, 20, v6.CYAN)
        pts=[]
        for i in range(150):
            x=170+i*5; y=300-int(22*math.sin(i*.17+t*5)-10*math.sin(i*.043)); pts.append((x,y))
        d.line(pts, fill=v6.GREEN, width=3)
        d.text((170,235), "LIVE MARKET INGEST", font=v6.font(17,True), fill=v6.MUTED)
        for i,n in enumerate(["RAW","CLEAN","CURATED","FEATURE"]):
            x=1050+i*185; h=int(35+70*pulse(t,i*.8)); d.rectangle((x,330-h,x+95,330),fill=(10,45+10*i,67+10*i)); d.text((x,345),n,font=v6.font(13,True),fill=v6.MUTED)
    elif kind == "spark":
        cx, cy = 920, 310
        for i in range(7):
            a=(i/7)*2*math.pi+t*.6; x=int(cx+250*math.cos(a)); y=int(cy+70*math.sin(a))
            d.line((cx,cy,x,y),fill=v6.BORDER,width=2); d.ellipse((x-13,y-13,x+13,y+13),fill=v6.GREEN if i<=int(t*7) else v6.BORDER)
        d.rounded_rectangle((cx-90,cy-35,cx+90,cy+35),15,fill=v6.PANEL,outline=v6.CYAN,width=3); d.text((cx-58,cy-13),"SPARK",font=v6.font(20,True),fill=v6.TEXT)
        data_particles(im,t,590,350,1490,22,v6.GREEN)
    elif kind == "v9":
        d.text((210,245),"CANDIDATE SCOREBOARD",font=v6.font(19,True),fill=v6.MUTED)
        for i in range(9):
            y=285+i*25; score=.35+.055*i+.03*math.sin(t*4+i); w=int(score*440)
            d.rectangle((210,y,210+w,y+10),fill=v6.GREEN if i==8 else v6.BORDER)
        d.text((665,290),"chronological folds",font=v6.font(17,True),fill=v6.CYAN)
        for i in range(5):
            x=665+i*85; d.rounded_rectangle((x,325,x+65,365),10,fill=v6.PANEL,outline=v6.GREEN if t>(i+1)/7 else v6.BORDER,width=2); d.text((x+22,337),str(i+1),font=v6.font(14,True),fill=v6.TEXT)
    elif kind == "cycle2":
        d.text((210,255),"SEARCH SPACE",font=v6.font(18,True),fill=v6.MUTED)
        for r in range(5):
            for c in range(11):
                x=210+c*31; y=300+r*31; active=((r*11+c)/54)<t
                d.rounded_rectangle((x,y,x+20,y+20),5,fill=v6.GREEN if active else v6.BORDER)
        d.text((210,470),f"{min(54,int(t*55)):02d} / 54 EVALUATED",font=v6.font(20,True),fill=v6.CYAN)
    elif kind == "v10":
        labels=[("TREND",.76),("VOL",.48),("BREADTH",.63),("LIQUIDITY",.84)]
        for i,(lab,val) in enumerate(labels):
            x=220+i*330; d.text((x,255),lab,font=v6.font(15,True),fill=v6.MUTED); d.rounded_rectangle((x,290,x+260,315),10,fill=(9,27,45)); d.rounded_rectangle((x,290,x+int(260*val*pulse(t*.25,i*.3)),315),10,fill=v6.CYAN if i<2 else v6.GREEN)
    return add_hud(im,t)
v6.diagram = richer_diagram


def richer_gate(t):
    im=_old_gate(t); d=v6.ImageDraw.Draw(im)
    for i in range(8):
        y=250+i*35; done=t>(i+1)/10
        d.text((120,y),f"feature_contract_{i+1:02d}",font=v6.font(14),fill=v6.MUTED)
        d.text((360,y),"PASS" if done else "CHECK",font=v6.font(14,True),fill=v6.GREEN if done else v6.GOLD)
    return add_hud(im,t,"VALIDATION ACTIVE")
v6.gate=richer_gate


def richer_fail(t):
    im=_old_fail(t); d=v6.ImageDraw.Draw(im)
    d.rounded_rectangle((1515,315,1810,760),24,fill=(22,6,12),outline=(105,30,42),width=3)
    d.text((1550,350),"CONFIRMATION",font=v6.font(18,True),fill=v6.MUTED)
    for i,(lab,status) in enumerate([("WINNER LOCKED","YES"),("GATE PASSED","NO"),("RUNNER-UP SWAP","NO"),("V8 STATUS","FROZEN")]):
        y=410+i*78; d.text((1550,y),lab,font=v6.font(14,True),fill=v6.MUTED); d.text((1550,y+28),status,font=v6.font(22,True),fill=v6.RED if status=="NO" and i==1 else v6.GREEN)
    return im
v6.fail=richer_fail


def richer_hold(t):
    im=_old_hold(t); d=v6.ImageDraw.Draw(im)
    sep=1100
    for i in range(9):
        u=(t*1.3+i/9)%1; x=int(190+u*(sep-220)); y=535+(i%3)*28
        d.ellipse((x-6,y-6,x+6,y+6),fill=v6.GREEN)
    d.rounded_rectangle((1390,330,1550,470),24,fill=(7,15,25),outline=v6.RED,width=4)
    d.arc((1430,345,1510,425),180,360,fill=v6.RED,width=7); d.rectangle((1425,390,1515,455),fill=(25,5,10),outline=v6.RED,width=4)
    d.text((1457,407),"X",font=v6.font(24,True),fill=v6.RED)
    return add_hud(im,t,"HOLDOUT PROTECTED")
v6.hold=richer_hold


def richer_site(path,t,a,b):
    im=_old_site(path,t,a,b)
    d=v6.ImageDraw.Draw(im)
    d.rounded_rectangle((1435,145,1815,190),12,fill=(4,18,31),outline=v6.BORDER,width=2)
    d.text((1460,157),"ACTUAL DATA SHEPHERD PLATFORM",font=v6.font(15,True),fill=v6.GREEN)
    return im
v6.site=richer_site


def main():
    old=v6.OUT/'data_shepherd_showcase_v6_16x9.mp4'
    new=v6.OUT/'data_shepherd_showcase_v7_16x9.mp4'
    v6.main()
    if old.exists():
        shutil.move(str(old),str(new))
    print(f"\nV7 DONE: {new}\nopen \"{new}\"")

if __name__=='__main__':
    main()
