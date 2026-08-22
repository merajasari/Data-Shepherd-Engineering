#!/usr/bin/env python3
"""Data Shepherd Engineering V5 video.

Uses the real site logo and real landing-page imagery from the repository.
Uses Meraj Asari's supplied portrait when provided via FOUNDER_IMAGE or when found
in common local locations. Narration is a separate British female presenter voice.
"""
from __future__ import annotations
import math, os, re, shutil, subprocess, sys, tempfile, textwrap
from pathlib import Path
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    import imageio_ffmpeg
except Exception:
    subprocess.check_call([sys.executable,'-m','pip','install','pillow','imageio-ffmpeg'])
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    import imageio_ffmpeg
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'; OUT.mkdir(exist_ok=True)
W,H,FPS=1920,1080,30
BG=(5,14,26); PANEL=(11,27,47); TEXT=(245,249,255); MUTED=(157,180,205); CYAN=(54,216,255); GREEN=(57,227,161); GOLD=(242,194,88); RED=(255,85,103); BORDER=(39,73,108)
LOGO=ROOT/'webapp/static/images/data-shepherd-logo.png'
LANDING=ROOT/'webapp/static/images/landing'
SITE_ASSETS=[LANDING/'platform-overview-2026.png',LANDING/'platform-dashboard.png',LANDING/'platform-architecture.png',LANDING/'platform-pipeline.png',LANDING/'platform-engineering.png']

def ff(): return imageio_ffmpeg.get_ffmpeg_exe()
def font(n,b=False):
    for p in ['/System/Library/Fonts/Supplemental/Arial Bold.ttf' if b else '/System/Library/Fonts/Supplemental/Arial.ttf','/System/Library/Fonts/Helvetica.ttc']:
        if Path(p).exists():
            try:return ImageFont.truetype(p,n)
            except:pass
    return ImageFont.load_default()
def wrap(s,n): return '\n'.join(textwrap.wrap(s,n))

def founder_path():
    env=os.environ.get('FOUNDER_IMAGE')
    candidates=[env, ROOT/'assets/video/meraj-asari.jpg', ROOT/'Meraj Asari.jpg', Path.home()/'Downloads/Meraj Asari.jpg', Path.home()/'Desktop/Meraj Asari.jpg']
    for p in candidates:
        if p and Path(p).exists(): return Path(p)
    return None

def crop_cover(src,size,zoom=1.0,x_bias=.5,y_bias=.42):
    im=Image.open(src).convert('RGB'); tw,th=size; sw,sh=im.size
    scale=max(tw/sw,th/sh)*zoom; nw,nh=int(sw*scale),int(sh*scale)
    im=im.resize((nw,nh),Image.Resampling.LANCZOS)
    x=max(0,min(nw-tw,int((nw-tw)*x_bias))); y=max(0,min(nh-th,int((nh-th)*y_bias)))
    return im.crop((x,y,x+tw,y+th))

def logo_layer(maxw=620,maxh=290):
    if not LOGO.exists(): return None
    im=Image.open(LOGO).convert('RGBA'); im.thumbnail((maxw,maxh),Image.Resampling.LANCZOS); return im

def add_logo(im,x=85,y=70,maxw=440,maxh=190):
    lg=logo_layer(maxw,maxh)
    if lg: im.paste(lg,(x,y),lg)

def grade(im):
    im=ImageEnhance.Contrast(im).enhance(1.08); im=ImageEnhance.Color(im).enhance(.92)
    overlay=Image.new('RGBA',im.size,(3,12,23,0)); od=ImageDraw.Draw(overlay); od.rectangle((0,0,W,H),fill=(2,10,20,75)); return Image.alpha_composite(im.convert('RGBA'),overlay).convert('RGB')

def founder_frame(phase,closing=False):
    p=founder_path(); bg=Image.new('RGB',(W,H),BG)
    if p:
        # cinematic founder portrait: slow push-in, site palette overlay
        photo=crop_cover(p,(850,1080),zoom=1.02+phase*.06,x_bias=.5,y_bias=.28)
        photo=grade(photo)
        bg.paste(photo,(1070,0))
        glow=Image.new('RGBA',(W,H),(0,0,0,0)); gd=ImageDraw.Draw(glow); gd.rectangle((930,0,1300,H),fill=(5,14,26,0)); glow=glow.filter(ImageFilter.GaussianBlur(80)); bg=Image.alpha_composite(bg.convert('RGBA'),glow).convert('RGB')
    d=ImageDraw.Draw(bg); add_logo(bg,85,55,520,210)
    d.text((95,315),'MERAJ ASARI',font=font(72,True),fill=CYAN)
    d.text((98,400),'FOUNDER  •  DEVELOPER  •  CEO',font=font(30,True),fill=TEXT)
    if closing:
        d.multiline_text((98,515),'Evidence over promises.\nReproducibility over hindsight.',font=font(46,True),fill=TEXT,spacing=14)
        d.text((100,805),'ENGINEERED FOR THE MARKETS. BUILT FOR THE FUTURE.',font=font(28,True),fill=GREEN)
    else:
        d.multiline_text((98,515),'The founder behind\nData Shepherd Engineering',font=font(48,True),fill=TEXT,spacing=12)
        d.multiline_text((100,695),'An end-to-end data, ML and model-governance\nplatform built to make evidence observable.',font=font(29),fill=MUTED,spacing=10)
    return bg

def site_frame(asset,phase,title,subtitle):
    im=Image.new('RGB',(W,H),BG); d=ImageDraw.Draw(im); add_logo(im,70,38,360,135)
    d.text((510,70),title,font=font(46,True),fill=TEXT); d.text((512,132),subtitle,font=font(25),fill=MUTED)
    if asset.exists():
        src=Image.open(asset).convert('RGB'); sw,sh=src.size; area=(110,230,1810,980); aw,ah=area[2]-area[0],area[3]-area[1]
        zoom=1.0+.08*phase; scaled=crop_cover(asset,(aw,ah),zoom=zoom,x_bias=.5+.10*math.sin(phase*math.pi),y_bias=.45)
        im.paste(scaled,(area[0],area[1])); d.rounded_rectangle(area,26,outline=BORDER,width=3)
    return im

def diagram_frame(kind,phase,title,subtitle):
    im=Image.new('RGB',(W,H),BG); d=ImageDraw.Draw(im); add_logo(im,65,45,330,125)
    d.text((470,62),title,font=font(50,True),fill=TEXT); d.text((472,128),subtitle,font=font(26),fill=MUTED)
    if kind=='spark': labels=['RAW DATA','PYSPARK','PARQUET','VALIDATE','MODELS']; active=int(phase*len(labels))
    elif kind=='v9': labels=['REGISTER','27 CANDIDATES','5 FOLDS','LOCK WINNER','CONFIRM']; active=int(phase*len(labels))
    elif kind=='cycle2': labels=['54 CANDIDATES','TOP 10/15/20','10/20 HOLD','RISK CONTROL']; active=int(phase*len(labels))
    elif kind=='v10': labels=['DISCOVERY','ROBUSTNESS','SIMULATION','PRE-FREEZE','CONFIRM']; active=int(phase*len(labels))
    else: labels=['MARKET','BRONZE','SILVER','GOLD','FEATURES']; active=int(phase*len(labels))
    left=105; top=560; gap=20; total=1700; bw=(total-gap*(len(labels)-1))//len(labels)
    for i,l in enumerate(labels):
        x=left+i*(bw+gap); col=GREEN if i<=active else BORDER; d.rounded_rectangle((x,top,x+bw,top+140),24,fill=PANEL,outline=col,width=4)
        bb=d.textbbox((0,0),l,font=font(23,True)); d.text((x+(bw-(bb[2]-bb[0]))//2,top+54),l,font=font(23,True),fill=TEXT)
        if i<len(labels)-1: d.line((x+bw,top+70,x+bw+gap,top+70),fill=CYAN,width=4)
    if kind=='gate': pass
    return im

def dramatic_frame(phase):
    im=Image.new('RGB',(W,H),(19,4,10)); d=ImageDraw.Draw(im); add_logo(im,70,55,330,125)
    d.text((170,310),'THE WINNER FAILED.',font=font(64,True),fill=TEXT); d.rounded_rectangle((170,455,1330,690),30,fill=(45,5,14),outline=RED,width=5); d.text((315,515),'NOT CONFIRMED',font=font(92,True),fill=RED)
    d.text((174,770),'No runner-up substitution.  No lower bar.  V8 unchanged.',font=font(31,True),fill=TEXT)
    return im

def holdout_frame(phase):
    im=Image.new('RGB',(W,H),BG); d=ImageDraw.Draw(im); add_logo(im,70,45,330,125)
    d.text((470,65),'THE FUTURE IS RESERVED',font=font(52,True),fill=TEXT); d.text((472,135),'V10 formal holdout begins 2 November 2026',font=font(27),fill=MUTED)
    y=610; x0,x1=180,1720; boundary=1090; d.line((x0,y,x1,y),fill=(72,94,116),width=6); d.line((x0,y,boundary,y),fill=GREEN,width=10); d.line((boundary,y-140,boundary,y+170),fill=RED,width=5); d.text((905,420),'2 NOV 2026',font=font(38,True),fill=RED); d.text((280,675),'RESEARCH + CONFIRMATION',font=font(29,True),fill=GREEN); d.text((1200,675),'FORMAL HOLDOUT',font=font(29,True),fill=MUTED); d.text((630,850),'THE MODEL DOES NOT GET TO SEE THIS YET.',font=font(34,True),fill=TEXT)
    return im

SCENES=[
('founder',None,"This is Meraj Asari — Founder, Developer and CEO of Data Shepherd Engineering. What began as an engineering project has evolved into an end-to-end platform combining production data pipelines, distributed processing, machine learning, quantitative research and model governance."),
('site',SITE_ASSETS[0],"The platform is designed around a simple idea: a model result is only as trustworthy as the engineering system around it. Data Shepherd keeps the data path, research process, validation gates and production evidence explicit and observable."),
('diagram','pipeline',"Market data moves through a medallion-style architecture: raw observations are preserved, cleaned and standardised, curated into analytical data, and transformed into model-ready features before any model is allowed to consume them."),
('diagram','spark',"As the platform scaled, a PySpark feature backend was introduced alongside Pandas through a shared contract. Spark provides distributed processing, while parity and fail-closed validation protect the meaning of the features downstream models receive."),
('site',SITE_ASSETS[2],"The production architecture is not hidden behind a notebook. It is surfaced, documented and monitored as an engineering system — with data flows, operational boundaries and production components that can be inspected."),
('site',SITE_ASSETS[1],"The same principle carries through to the live platform. The website surfaces model outputs, portfolio evidence and system state so research does not disappear into an opaque black box."),
('diagram','v9',"V9 introduces bounded automatic tuning. Candidates are registered before evaluation, tested through purged chronological walk-forward folds, and the development winner is locked before confirmation."),
('dramatic',None,"And this is one of the most important parts of the system: the first development winner failed confirmation. Data Shepherd rejected it. No runner-up substitution. No lowering the bar. Frozen V8 remained unchanged."),
('diagram','cycle2',"Cycle Two expands the research with fifty-four deterministic candidates, broader portfolio sizes, longer holding periods and explicit risk controls. It is active research, not a production claim."),
('diagram','v10',"V10 is a separate regime-conditioned challenger track, moving through discovery, robustness testing, fixed-contract simulation and a pre-freeze gate before prospective confirmation against frozen V8."),
('holdout',None,"Then comes the boundary the model cannot cross. V10's formal holdout begins on the second of November, twenty twenty-six. That data belongs to the future. Research and confirmation do not get to see it yet."),
('site',SITE_ASSETS[4],"Taken together, Data Shepherd is meant to demonstrate more than prediction: distributed data engineering, reproducible experimentation, model governance, forward evidence and operational monitoring working as one system."),
('close',None,"Data Shepherd Engineering is the work of Meraj Asari — one developer building a platform where every result has to earn its way through the pipeline. Evidence over promises. Reproducibility over hindsight. Engineered for the markets. Built for the future.")]

def voice(text,path):
    out=''
    try: out=subprocess.check_output(['say','-v','?'],text=True)
    except: pass
    preferred=os.environ.get('DS_VOICE') or ('Serena' if 'Serena' in out else ('Kate' if 'Kate' in out else ('Daniel' if 'Daniel' in out else 'Samantha')))
    subprocess.check_call(['say','-v',preferred,'-r',os.environ.get('DS_RATE','171'),'-o',str(path),text])
def duration(path):
    p=subprocess.run([ff(),'-i',str(path)],stderr=subprocess.PIPE,stdout=subprocess.DEVNULL,text=True); m=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',p.stderr); return int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3)) if m else 8

def render_frame(scene,fr,n):
    kind,arg,_=scene; phase=fr/max(1,n-1)
    if kind=='founder': return founder_frame(phase,False)
    if kind=='close': return founder_frame(phase,True)
    if kind=='site':
        idx=SITE_ASSETS.index(arg) if arg in SITE_ASSETS else 0
        titles=[('THE PLATFORM','The real Data Shepherd website and visual system'),('LIVE PLATFORM','Actual site imagery from Data Shepherd'),('ARCHITECTURE','The engineering system behind the models'),('PIPELINE','From data to governed features'),('OPERATIONS','Engineering made observable')]
        return site_frame(arg,phase,*titles[idx])
    if kind=='dramatic': return dramatic_frame(phase)
    if kind=='holdout': return holdout_frame(phase)
    names={'pipeline':('THE DATA PATH','Market data → Bronze → Silver → Gold → Features'),'spark':('PYSPARK IN THE DATA PATH','Distributed processing with parity and fail-closed validation'),'v9':('V9 AUTOMATIC TUNING','Bounded search without automatic hindsight'),'cycle2':('V9 CYCLE 2','54 deterministic candidates • active research'),'v10':('V10 CHALLENGER','Regime-conditioned research track')}
    return diagram_frame(arg,phase,*names[arg])

def main():
    if founder_path() is None:
        print('NOTE: founder portrait not found. Set FOUNDER_IMAGE=/absolute/path/to/photo.jpg or save Meraj Asari.jpg in ~/Downloads.')
    tmp=Path(tempfile.mkdtemp(prefix='dsv5_')); clips=[]
    try:
        for i,s in enumerate(SCENES):
            audio=tmp/f'a{i}.aiff'; voice(s[2],audio); sec=duration(audio)+.45; n=max(1,int(sec*FPS)); raw=tmp/f'r{i}.mp4'
            p=subprocess.Popen([ff(),'-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-an','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p',str(raw)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for fr in range(n): p.stdin.write(render_frame(s,fr,n).tobytes())
            p.stdin.close(); p.wait(); clip=tmp/f'c{i}.mp4'; subprocess.check_call([ff(),'-y','-i',str(raw),'-i',str(audio),'-c:v','copy','-c:a','aac','-b:a','192k','-shortest',str(clip)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); clips.append(clip)
        lst=tmp/'list.txt'; lst.write_text(''.join(f"file '{x}'\n" for x in clips)); target=OUT/'data_shepherd_showcase_v5_16x9.mp4'; subprocess.check_call([ff(),'-y','-f','concat','-safe','0','-i',str(lst),'-c','copy',str(target)]); print(f'\nDONE: {target}\nopen "{target}"')
    finally: shutil.rmtree(tmp,ignore_errors=True)
if __name__=='__main__': main()
