#!/usr/bin/env python3
"""Generate Data Shepherd Engineering V3 founder-led cinematic showcase.

Creates a polished 16:9 motion-graphics film with a human-style presenter treatment,
British narration via macOS voices, founder introduction, and the current platform story.
This generator intentionally describes V9 Cycle 2 as active research, not completed work.
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, textwrap
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except Exception:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pillow', 'imageio-ffmpeg'])
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
try:
    import imageio_ffmpeg
except Exception:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'imageio-ffmpeg'])
    import imageio_ffmpeg

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'; OUT.mkdir(exist_ok=True)
BG=(5,13,25); PANEL=(10,25,44); TEXT=(245,248,255); MUTED=(159,179,204); CYAN=(57,218,255); GREEN=(63,228,165); GOLD=(244,194,91); RED=(255,90,105); BORDER=(38,70,103)
W,H=1920,1080; FPS=30

def fnt(n,b=False):
    paths=['/System/Library/Fonts/Supplemental/Arial Bold.ttf' if b else '/System/Library/Fonts/Supplemental/Arial.ttf','/System/Library/Fonts/Helvetica.ttc']
    for p in paths:
        if Path(p).exists():
            try:return ImageFont.truetype(p,n)
            except:pass
    return ImageFont.load_default()

def wrap(s,n): return '\n'.join(textwrap.wrap(s,n))
def ffmpeg(): return imageio_ffmpeg.get_ffmpeg_exe()

SCENES=[
('FOUNDER • DEVELOPER • CEO','DATA SHEPHERD ENGINEERING','Founded, designed and developed by Meraj Asari.','Data Shepherd Engineering was founded, designed and developed by Meraj Asari, Founder, Developer and CEO. What began as an engineering project has evolved into a production-minded platform combining data engineering, distributed processing, machine learning, quantitative research and model governance.'),
('THE VISION','ENGINEERING BEFORE PREDICTION','Build evidence that is reproducible, inspectable and deliberately difficult to fool.','The idea behind Data Shepherd is simple. A model result is only as trustworthy as the system around it. So the platform is engineered from the data layer upward, with explicit contracts between research, validation, production and untouched future evidence.'),
('THE DATA PLATFORM','MARKET DATA → BRONZE → SILVER → GOLD → FEATURES','Validated transformations come before model inference.','Market data moves through a medallion-style pipeline. Raw observations are preserved, cleaned and standardised, curated into analytical data, and then transformed into model-ready features. Models consume governed inputs rather than quietly redefining the data they are tested on.'),
('DISTRIBUTED PROCESSING','PYSPARK IN THE PRODUCTION DATA PATH','Shared Pandas/Spark contracts • Parquet • fail-closed validation • 101/101 materialisation gate','As the platform grew, the feature layer grew with it. A PySpark backend now runs alongside the Pandas implementation through a shared source contract. Before downstream model work can continue, fail-closed validation checks the materialised universe for completeness and consistency.'),
('PRODUCTION REFERENCE','V8 — FROZEN ON PURPOSE','100-stock universe • Top 10 • 5-session hold • next-open assumption • 10 bps','V8 is the frozen production reference model. It ranks a one-hundred-stock universe, selects the top ten, uses a five-session holding period and a next-open execution assumption, with the transaction-cost contract fixed. Its forward evidence is append-only. It is not another tuning dataset.'),
('AUTOMATIC RESEARCH','V9 — BOUNDED AUTO-TUNING','Predeclared candidates → immutable registry → evaluation → fixed winner → confirmation','V9 introduces automatic model research, but not uncontrolled optimisation. Candidate configurations are declared first and given immutable identities. That matters because an automated search should not be allowed to rewrite its own experiment after seeing the answer.'),
('TEMPORAL VALIDATION','PURGED WALK-FORWARD EVALUATION','5 chronological folds • 10-session purge • turnover • costs • risk-adjusted objective','Each V9 candidate is evaluated chronologically through purged walk-forward folds. Exits must remain inside their validation window, turnover is modelled, costs are charged, and the ranking objective is predeclared. The design is intentionally hostile to hindsight.'),
('SCIENTIFIC DISCIPLINE','THE WINNER IS LOCKED BEFORE CONFIRMATION','No runner-up substitution. NOT_CONFIRMED is a valid result. V8 remains unchanged.','Then the development winner is locked before confirmation. If it fails the predeclared stability and cost-stress gates, the system accepts the failure. It does not quietly substitute the runner-up. In Cycle One, not confirmed was an acceptable scientific outcome.'),
('ACTIVE RESEARCH','V9 CYCLE 2 — RISK-CONTROLLED TUNING','54 deterministic candidates • Top 10/15/20 • 10/20-session holds • SPY SMA200 exposure rules','The next V9 cycle expands the research without lowering the bar. Fifty-four deterministic candidates explore broader portfolio sizes, longer holding periods and explicit trend-based exposure controls, while leverage and shorting remain forbidden. This cycle is active research, not a production claim.'),
('NEXT-GENERATION CHALLENGER','V10 — REGIME-CONDITIONED RESEARCH','Discovery → robustness → fixed-contract simulation → pre-freeze gate → prospective confirmation','V10 is a separate challenger track. It explores regime-conditioned ranking through staged development, robustness testing, fixed-contract portfolio simulation and a pre-freeze gate before prospective confirmation against frozen V8.'),
('EVIDENCE BOUNDARY','V10 FORMAL HOLDOUT — RESERVED FOR THE FUTURE','Formal holdout begins 2 November 2026. Research and confirmation cannot score through it.','And V10 preserves a separate formal holdout beginning on the second of November, twenty twenty-six. The future is reserved before the result is known. Research, confirmation and formal holdout evidence remain distinct by design.'),
('OPERATIONS & GOVERNANCE','ONE SYSTEM. EXPLICIT BOUNDARIES.','Scheduled orchestration • health monitoring • model contracts • audit trails • dashboards • fail-closed design','Around the models sits the operational system: scheduled orchestration, health monitoring, model contracts, evidence artifacts, dashboards and fail-closed controls. The objective is not merely to produce predictions. It is to make the entire decision process observable.'),
('DATA SHEPHERD ENGINEERING','BUILT DIFFERENT. BUILT TO LAST.','Data engineering • distributed processing • machine learning • quantitative research • governance','Data Shepherd Engineering brings distributed data engineering, machine learning, quantitative research, governance and production operations together in one evolving platform. Built by Meraj Asari, it is an engineering project first. Evidence over promises. Reproducibility over hindsight. And every result has to earn its way through the pipeline.')]

def presenter(img, frame, phase):
    d=ImageDraw.Draw(img); x0,y0,x1,y1=1390,190,1835,930
    d.rounded_rectangle((x0-6,y0-6,x1+6,y1+6),30,fill=(6,17,31),outline=CYAN,width=2)
    # photoreal-style painted presenter with subtle frame-by-frame movement/blink/mouth animation
    bob=int(4*__import__('math').sin(phase*6.283)); cx=(x0+x1)//2; cy=y0+215+bob
    # hair silhouette
    d.ellipse((cx-145,cy-190,cx+145,cy+175),fill=(57,35,25)); d.rounded_rectangle((cx-155,cy-15,cx+155,y1-90),55,fill=(57,35,25))
    # face/neck
    skin=(222,174,142); d.ellipse((cx-105,cy-150,cx+105,cy+120),fill=skin); d.rectangle((cx-43,cy+95,cx+43,cy+180),fill=skin)
    # eyes blink periodically
    blink=(frame%95 in range(0,5))
    if blink:
        d.line((cx-63,cy-38,cx-28,cy-38),fill=(50,35,31),width=5); d.line((cx+28,cy-38,cx+63,cy-38),fill=(50,35,31),width=5)
    else:
        d.ellipse((cx-62,cy-45,cx-30,cy-20),fill=(245,245,240)); d.ellipse((cx+30,cy-45,cx+62,cy-20),fill=(245,245,240)); d.ellipse((cx-50,cy-41,cx-38,cy-25),fill=(47,72,64)); d.ellipse((cx+38,cy-41,cx+50,cy-25),fill=(47,72,64))
    # brows/nose
    d.arc((cx-70,cy-67,cx-22,cy-37),190,345,fill=(72,45,33),width=4); d.arc((cx+22,cy-67,cx+70,cy-37),195,350,fill=(72,45,33),width=4)
    d.line((cx,cy-20,cx-8,cy+32),fill=(181,127,105),width=3)
    # talking mouth changes
    m=frame%18
    if m<7:d.ellipse((cx-38,cy+55,cx+38,cy+76),fill=(137,61,67))
    elif m<13:d.ellipse((cx-32,cy+51,cx+32,cy+83),fill=(112,47,54))
    else:d.arc((cx-39,cy+45,cx+39,cy+78),5,175,fill=(142,62,66),width=5)
    # jacket/body, slight hand gesture
    d.polygon([(x0+35,y1),(cx-92,cy+145),(cx+92,cy+145),(x1-35,y1)],fill=(15,28,43)); d.polygon([(cx-92,cy+145),(cx,cy+275),(cx+92,cy+145)],fill=(25,42,57))
    hand_y=730+int(18*__import__('math').sin(phase*3.1415)); d.ellipse((x0+62,hand_y,x0+122,hand_y+88),fill=skin); d.ellipse((x1-122,hand_y+15,x1-62,hand_y+103),fill=skin)
    d.text((x0+30,y1-55),'YOUR GUIDE THROUGH THE PLATFORM',font=fnt(19,True),fill=CYAN)

def base_frame(scene, frame, frames):
    eye,title,body,_=scene; img=Image.new('RGB',(W,H),BG); d=ImageDraw.Draw(img)
    # animated grid/data particles
    for x in range(0,W,120): d.line((x,0,x,H),fill=(10,27,45),width=1)
    for y in range(0,H,90): d.line((0,y,W,y),fill=(10,27,45),width=1)
    phase=frame/max(1,frames-1)
    for i in range(28):
        xx=int((i*173+frame*2.1)%W); yy=(i*97)%H; d.ellipse((xx,yy,xx+3,yy+3),fill=(22,88,112))
    d.text((80,75),eye,font=fnt(24,True),fill=CYAN)
    d.multiline_text((80,125),wrap(title,30),font=fnt(61,True),fill=TEXT,spacing=8)
    d.multiline_text((80,305),wrap(body,55),font=fnt(31),fill=MUTED,spacing=12)
    # architecture motif changes per scene
    labels=[]
    if 'DATA PLATFORM' in eye: labels=['INGEST','BRONZE','SILVER','GOLD','FEATURES']
    elif 'DISTRIBUTED' in eye: labels=['RAW DATA','PYSPARK','VALIDATE','101 / 101','MODELS']
    elif 'AUTOMATIC' in eye: labels=['REGISTER','27 CANDIDATES','EVALUATE','LOCK','CONFIRM']
    elif 'TEMPORAL' in eye: labels=['FOLD 1','FOLD 2','FOLD 3','FOLD 4','FOLD 5']
    elif 'ACTIVE' in eye: labels=['54 CANDIDATES','TOP 10/15/20','10/20 HOLD','RISK CONTROL']
    elif 'NEXT-GENERATION' in eye: labels=['PHASE 1','PHASE 2','PHASE 3','PHASE 4','CONFIRM']
    elif 'EVIDENCE' in eye: labels=['RESEARCH','CONFIRMATION','2 NOV 2026','FORMAL HOLDOUT']
    else: labels=['DATA','PROCESSING','MODELS','EVIDENCE','OPERATIONS']
    y=610; avail=1220; gap=18; bw=(avail-gap*(len(labels)-1))//len(labels)
    for i,l in enumerate(labels):
        x=80+i*(bw+gap); col=GREEN if i<=int(phase*len(labels)) else BORDER
        d.rounded_rectangle((x,y,x+bw,y+110),18,fill=PANEL,outline=col,width=3); tw=d.textbbox((0,0),l,font=fnt(21,True))[2]; d.text((x+(bw-tw)//2,y+39),l,font=fnt(21,True),fill=TEXT)
        if i<len(labels)-1:d.line((x+bw,y+55,x+bw+gap,y+55),fill=CYAN,width=3)
    # founder special
    if eye.startswith('FOUNDER'):
        d.text((80,560),'MERAJ ASARI',font=fnt(72,True),fill=CYAN); d.text((82,650),'FOUNDER  •  DEVELOPER  •  CEO',font=fnt(31,True),fill=TEXT)
    if 'SCIENTIFIC' in eye:
        d.rounded_rectangle((90,600,720,735),24,fill=(35,10,18),outline=RED,width=3); d.text((160,640),'NOT CONFIRMED',font=fnt(42,True),fill=RED)
    presenter(img,frame,phase)
    d.text((80,1010),'DATA SHEPHERD ENGINEERING',font=fnt(19,True),fill=(92,125,156)); d.text((1530,1010),'EXPERIMENTAL RESEARCH PLATFORM',font=fnt(17),fill=(92,125,156))
    return img

def voice_for(text,path):
    voices=[]
    try:
        out=subprocess.check_output(['say','-v','?'],text=True)
        for preferred in ['Serena','Daniel','Kate','Oliver']:
            if preferred in out: voices.append(preferred)
    except:pass
    voice=os.environ.get('DS_VOICE') or (voices[0] if voices else 'Daniel')
    # deliberate punctuation and modest rate improves macOS narration
    subprocess.check_call(['say','-v',voice,'-r',os.environ.get('DS_RATE','168'),'-o',str(path),text])

def duration(path):
    p=subprocess.run([ffmpeg(),'-i',str(path)],stderr=subprocess.PIPE,stdout=subprocess.DEVNULL,text=True)
    import re
    m=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',p.stderr)
    return int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3)) if m else 8

def main():
    tmp=Path(tempfile.mkdtemp(prefix='ds_v3_')); clips=[]
    try:
        for idx,scene in enumerate(SCENES):
            audio=tmp/f'a{idx:02}.aiff'; voice_for(scene[3],audio); dur=duration(audio)+0.8; frames=max(1,int(dur*FPS))
            raw=tmp/f'raw{idx:02}.mp4'
            proc=subprocess.Popen([ffmpeg(),'-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-an','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p',str(raw)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for fr in range(frames): proc.stdin.write(base_frame(scene,fr,frames).tobytes())
            proc.stdin.close(); proc.wait()
            clip=tmp/f'clip{idx:02}.mp4'; subprocess.check_call([ffmpeg(),'-y','-i',str(raw),'-i',str(audio),'-c:v','copy','-c:a','aac','-b:a','192k','-shortest',str(clip)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); clips.append(clip)
        lst=tmp/'concat.txt'; lst.write_text(''.join(f"file '{c}'\n" for c in clips))
        out=OUT/'data_shepherd_showcase_v3_16x9.mp4'; subprocess.check_call([ffmpeg(),'-y','-f','concat','-safe','0','-i',str(lst),'-c','copy',str(out)])
        print(f'\nDONE: {out}\nOpen with: open "{out}"')
    finally:
        import shutil; shutil.rmtree(tmp,ignore_errors=True)
if __name__=='__main__': main()
