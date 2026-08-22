#!/usr/bin/env python3
"""Data Shepherd Engineering V6 launch film.

Polish pass over V5:
- fixes founder portrait orientation with EXIF transpose
- uses the real site logo and real repository website imagery
- adds stronger camera moves, focus callouts, and visual rhythm
- shortens narration and scenes for a tighter launch-film pace
- emphasizes the V9 NOT_CONFIRMED beat and V10 holdout boundary
- uses Meraj Asari's portrait for founder opening/closing

Output: outputs/data_shepherd_showcase_v6_16x9.mp4
"""
from __future__ import annotations
import math, os, re, shutil, subprocess, sys, tempfile, textwrap
from pathlib import Path
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
    import imageio_ffmpeg
except Exception:
    subprocess.check_call([sys.executable,'-m','pip','install','pillow','imageio-ffmpeg'])
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
    import imageio_ffmpeg

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'; OUT.mkdir(exist_ok=True)
W,H,FPS=1920,1080,30
BG=(5,14,26); PANEL=(10,26,46); TEXT=(246,250,255); MUTED=(157,180,205)
CYAN=(54,216,255); GREEN=(57,227,161); GOLD=(242,194,88); RED=(255,82,99); BORDER=(39,73,108)
LOGO=ROOT/'webapp/static/images/data-shepherd-logo.png'
LANDING=ROOT/'webapp/static/images/landing'
ASSETS={
    'overview': LANDING/'platform-overview-2026.png',
    'dashboard': LANDING/'platform-dashboard.png',
    'architecture': LANDING/'platform-architecture.png',
    'pipeline': LANDING/'platform-pipeline.png',
    'engineering': LANDING/'platform-engineering.png',
}

def ff(): return imageio_ffmpeg.get_ffmpeg_exe()
def font(n,b=False):
    for p in ['/System/Library/Fonts/Supplemental/Arial Bold.ttf' if b else '/System/Library/Fonts/Supplemental/Arial.ttf','/System/Library/Fonts/Helvetica.ttc']:
        if Path(p).exists():
            try:return ImageFont.truetype(p,n)
            except:pass
    return ImageFont.load_default()
def wrap(s,n): return '\n'.join(textwrap.wrap(s,n))
def ease(t): return t*t*(3-2*t)

def founder_path():
    env=os.environ.get('FOUNDER_IMAGE')
    candidates=[env, ROOT/'assets/video/meraj-asari.jpg', ROOT/'Meraj Asari.jpg', Path.home()/'Downloads/Meraj Asari.jpg', Path.home()/'Desktop/Meraj Asari.jpg']
    for p in candidates:
        if p and Path(p).exists(): return Path(p)
    return None

def load_oriented(path):
    im=Image.open(path)
    im=ImageOps.exif_transpose(im)
    return im.convert('RGB')

def crop_cover_image(im,size,zoom=1.0,x_bias=.5,y_bias=.42):
    tw,th=size; sw,sh=im.size
    scale=max(tw/sw,th/sh)*zoom; nw,nh=max(tw,int(sw*scale)),max(th,int(sh*scale))
    im=im.resize((nw,nh),Image.Resampling.LANCZOS)
    x=max(0,min(nw-tw,int((nw-tw)*x_bias))); y=max(0,min(nh-th,int((nh-th)*y_bias)))
    return im.crop((x,y,x+tw,y+th))
def crop_cover(path,size,zoom=1.0,x_bias=.5,y_bias=.42): return crop_cover_image(load_oriented(path),size,zoom,x_bias,y_bias)

def add_logo(im,x=70,y=45,maxw=390,maxh=150):
    if not LOGO.exists(): return
    lg=Image.open(LOGO).convert('RGBA'); lg.thumbnail((maxw,maxh),Image.Resampling.LANCZOS)
    im.paste(lg,(x,y),lg)

def vignette(im,strength=110):
    ov=Image.new('L',(W,H),0); d=ImageDraw.Draw(ov)
    for i in range(18):
        a=int(strength*(i/17)**2); d.rectangle((i*18,i*12,W-i*18,H-i*12),outline=a,width=18)
    black=Image.new('RGB',(W,H),(0,0,0)); return Image.composite(black,im,ov)

def founder_frame(t,closing=False):
    im=Image.new('RGB',(W,H),BG); p=founder_path()
    if p:
        photo=load_oriented(p)
        photo=ImageEnhance.Contrast(photo).enhance(1.05); photo=ImageEnhance.Color(photo).enhance(.92)
        z=1.02+.055*ease(t); panel=crop_cover_image(photo,(900,1080),zoom=z,x_bias=.5,y_bias=.22)
        shade=Image.new('RGBA',panel.size,(0,0,0,0)); sd=ImageDraw.Draw(shade); sd.rectangle((0,0,panel.width,panel.height),fill=(2,10,20,42)); panel=Image.alpha_composite(panel.convert('RGBA'),shade).convert('RGB')
        im.paste(panel,(1020,0))
        grad=Image.new('RGBA',(W,H),(0,0,0,0)); gd=ImageDraw.Draw(grad)
        for x in range(790,1240):
            a=int(255*max(0,min(1,(1240-x)/450))); gd.line((x,0,x,H),fill=(5,14,26,a))
        im=Image.alpha_composite(im.convert('RGBA'),grad).convert('RGB')
    add_logo(im,80,55,560,210); d=ImageDraw.Draw(im)
    d.text((95,320),'MERAJ ASARI',font=font(74,True),fill=CYAN)
    d.text((98,408),'FOUNDER  •  DEVELOPER  •  CEO',font=font(31,True),fill=TEXT)
    if closing:
        d.multiline_text((98,535),'Evidence over promises.\nReproducibility over hindsight.',font=font(48,True),fill=TEXT,spacing=14)
        d.text((100,820),'ENGINEERED FOR THE MARKETS. BUILT FOR THE FUTURE.',font=font(28,True),fill=GREEN)
    else:
        d.multiline_text((98,535),'Founder of\nData Shepherd Engineering',font=font(50,True),fill=TEXT,spacing=12)
        d.multiline_text((100,715),'Data engineering • distributed processing •\nmachine learning • model governance',font=font(28),fill=MUTED,spacing=10)
    return im

def site_frame(path,t,title,subtitle,focus=None):
    im=Image.new('RGB',(W,H),BG); add_logo(im,60,28,300,112); d=ImageDraw.Draw(im)
    d.text((405,48),title,font=font(46,True),fill=TEXT); d.text((407,110),subtitle,font=font(24),fill=MUTED)
    area=(70,200,1850,1015); aw,ah=area[2]-area[0],area[3]-area[1]
    if path.exists():
        src=load_oriented(path)
        zoom=1.0+.10*ease(t); xb=.50+.06*math.sin(t*math.pi); yb=.48-.03*math.sin(t*math.pi)
        shot=crop_cover_image(src,(aw,ah),zoom=zoom,x_bias=xb,y_bias=yb)
        im.paste(shot,(area[0],area[1]))
    d.rounded_rectangle(area,26,outline=BORDER,width=3)
    if focus:
        x0,y0,x1,y1,label=focus; fx0=area[0]+int(x0*aw); fy0=area[1]+int(y0*ah); fx1=area[0]+int(x1*aw); fy1=area[1]+int(y1*ah)
        pulse=2+int(2*abs(math.sin(t*math.pi*3))); d.rounded_rectangle((fx0,fy0,fx1,fy1),18,outline=CYAN,width=4+pulse)
        tw=d.textbbox((0,0),label,font=font(20,True))[2]; d.rounded_rectangle((fx0,fy0-42,fx0+tw+34,fy0-8),12,fill=(5,18,31),outline=CYAN,width=2); d.text((fx0+16,fy0-37),label,font=font(20,True),fill=CYAN)
    return im

def diagram_frame(kind,t):
    titles={
      'pipeline':('THE DATA PATH','Market data becomes governed model input'),
      'spark':('PYSPARK IN PRODUCTION','Distributed processing with fail-closed validation'),
      'v9':('V9 AUTOMATIC TUNING','Bounded search without automatic hindsight'),
      'cycle2':('V9 CYCLE 2','54 deterministic candidates • active research'),
      'v10':('V10 CHALLENGER','Regime-conditioned research track')}
    labels={
      'pipeline':['MARKET','BRONZE','SILVER','GOLD','FEATURES'],
      'spark':['RAW DATA','PYSPARK','PARQUET','VALIDATE','MODELS'],
      'v9':['REGISTER','27 CANDIDATES','5 FOLDS','LOCK','CONFIRM'],
      'cycle2':['54 CANDIDATES','TOP 10/15/20','10/20 HOLD','RISK CONTROL'],
      'v10':['DISCOVERY','ROBUSTNESS','SIMULATION','PRE-FREEZE','CONFIRM']}
    im=Image.new('RGB',(W,H),BG); add_logo(im,60,35,300,112); d=ImageDraw.Draw(im)
    title,sub=titles[kind]; d.text((405,54),title,font=font(50,True),fill=TEXT); d.text((407,122),sub,font=font(26),fill=MUTED)
    labs=labels[kind]; left=110; top=560; gap=22; total=1700; bw=(total-gap*(len(labs)-1))//len(labs); active=min(len(labs)-1,int(t*len(labs)))
    for i,l in enumerate(labs):
        x=left+i*(bw+gap); col=GREEN if i<=active else BORDER
        d.rounded_rectangle((x,top,x+bw,top+150),24,fill=PANEL,outline=col,width=4)
        bb=d.textbbox((0,0),l,font=font(23,True)); d.text((x+(bw-(bb[2]-bb[0]))//2,top+58),l,font=font(23,True),fill=TEXT)
        if i<len(labs)-1:
            d.line((x+bw,top+75,x+bw+gap,top+75),fill=CYAN,width=4)
            dotx=x+bw+int((t*4%1)*gap); d.ellipse((dotx-5,top+70,dotx+5,top+80),fill=GREEN)
    if kind=='v9': d.text((112,810),'DECLARED FIRST  →  EVALUATED SECOND',font=font(32,True),fill=CYAN)
    if kind=='cycle2': d.text((112,810),'NO LOWER BAR.  NO LEVERAGE.  NO SHORTING.',font=font(30,True),fill=TEXT)
    return im

def gate_frame(t):
    im=Image.new('RGB',(W,H),BG); add_logo(im,60,35,300,112); d=ImageDraw.Draw(im)
    d.text((405,54),'VALIDATION GATE',font=font(50,True),fill=TEXT); d.text((407,122),'Downstream model work waits for data quality',font=font(26),fill=MUTED)
    d.rounded_rectangle((350,375,1200,830),42,fill=(7,31,28),outline=GREEN,width=5)
    d.text((505,455),'101 / 101',font=font(108,True),fill=GREEN); d.text((650,610),'PASS',font=font(72,True),fill=TEXT)
    d.ellipse((1320,405,1640,725),outline=GREEN,width=12); d.line((1395,560,1465,630),fill=GREEN,width=18); d.line((1465,630,1595,475),fill=GREEN,width=18)
    d.text((385,865),'FAIL CLOSED IF THE CONTRACT BREAKS',font=font(30,True),fill=CYAN)
    return im

def fail_frame(t):
    im=Image.new('RGB',(W,H),(16,3,9)); add_logo(im,60,40,300,112); d=ImageDraw.Draw(im)
    d.text((190,270),'THE WINNER FAILED.',font=font(68,True),fill=TEXT)
    if t>.18:
        glow=int(80+80*abs(math.sin(t*math.pi*3))); d.rounded_rectangle((190,430,1450,720),34,fill=(45,5,14),outline=RED,width=6)
        d.text((360,515),'NOT CONFIRMED',font=font(98,True),fill=RED)
    if t>.48: d.text((200,800),'NO SWAP.  NO LOWER BAR.  V8 UNCHANGED.',font=font(33,True),fill=TEXT)
    return im

def holdout_frame(t):
    im=Image.new('RGB',(W,H),BG); add_logo(im,60,35,300,112); d=ImageDraw.Draw(im)
    d.text((405,54),'THE FUTURE IS RESERVED',font=font(50,True),fill=TEXT); d.text((407,122),'V10 formal holdout begins 2 November 2026',font=font(26),fill=MUTED)
    y=610; x0,x1=180,1720; b=1090; d.line((x0,y,x1,y),fill=(72,94,116),width=6); d.line((x0,y,b,y),fill=GREEN,width=10)
    d.line((b,y-145,b,y+180),fill=RED,width=6); d.text((900,420),'2 NOV 2026',font=font(40,True),fill=RED)
    d.text((260,680),'RESEARCH + CONFIRMATION',font=font(29,True),fill=GREEN); d.text((1210,680),'FORMAL HOLDOUT',font=font(29,True),fill=MUTED)
    darkness=Image.new('RGBA',(W,H),(0,0,0,0)); dd=ImageDraw.Draw(darkness); alpha=int(115+100*ease(t)); dd.rectangle((b,250,W,H),fill=(0,0,0,alpha)); im=Image.alpha_composite(im.convert('RGBA'),darkness).convert('RGB'); d=ImageDraw.Draw(im)
    d.text((545,865),'THE MODEL DOES NOT GET TO SEE THIS YET.',font=font(34,True),fill=TEXT)
    return im

SCENES=[
('founder',None,"This is Meraj Asari — Founder, Developer and CEO of Data Shepherd Engineering. He built the platform around one question: what does it take to create a machine-learning system you can actually trust?"),
('site',('overview','THE REAL PLATFORM','A live engineering system, not a notebook demo',(0.05,0.08,0.47,0.48,'PLATFORM OVERVIEW')),"Data Shepherd brings production data pipelines, distributed processing, machine learning, quantitative research and model governance into one observable system."),
('diagram','pipeline',"Market data moves through a medallion-style path: raw observations are preserved, cleaned, curated and transformed into model-ready features before inference begins."),
('diagram','spark',"PySpark now runs alongside Pandas through a shared feature contract. Distributed processing can scale the path, but validation protects the meaning of every downstream feature."),
('gate',None,"Before model work continues, the materialised feature universe has to pass its validation gate. One hundred and one out of one hundred and one checks. If the contract breaks, the pipeline stops."),
('site',('dashboard','THE PRODUCT','Actual Data Shepherd dashboard imagery',(0.05,0.06,0.95,0.55,'MODEL & PORTFOLIO EVIDENCE')),"That engineering ultimately surfaces in the product itself: model rankings, portfolio evidence, holdout monitoring and operational state are visible instead of hidden behind a black box."),
('diagram','v9',"V9 adds bounded automatic tuning. Candidate configurations are declared before evaluation, tested chronologically, and the development winner is locked before confirmation."),
('fail',None,"Then the winner failed confirmation. Data Shepherd rejected it. No runner-up substitution. No lower bar. Frozen V8 stayed exactly where it was."),
('diagram','cycle2',"Cycle Two expands the search to fifty-four deterministic candidates with broader portfolio sizes, longer holding periods and explicit risk controls. It remains research, not a production claim."),
('diagram','v10',"V10 is a separate regime-conditioned challenger, moving through discovery, robustness testing, fixed-contract simulation and a pre-freeze gate before prospective confirmation."),
('holdout',None,"Then comes the boundary the model cannot cross. V10's formal holdout begins on the second of November, twenty twenty-six. That data belongs to the future."),
('site',('engineering','OPERATIONS & GOVERNANCE','The engineering around the models',(0.08,0.10,0.92,0.90,'OBSERVABLE SYSTEM')),"Scheduled orchestration, health monitoring, model contracts, evidence artifacts and dashboards make the entire process inspectable. The goal is not just prediction. It is trustworthy engineering."),
('close',None,"Data Shepherd Engineering is the work of Meraj Asari: one developer building a platform where every result has to earn its way through the pipeline. Evidence over promises. Reproducibility over hindsight. Engineered for the markets. Built for the future.")]

def voice(text,path):
    out=''
    try: out=subprocess.check_output(['say','-v','?'],text=True)
    except: pass
    preferred=os.environ.get('DS_VOICE') or ('Serena' if 'Serena' in out else ('Kate' if 'Kate' in out else ('Daniel' if 'Daniel' in out else 'Samantha')))
    subprocess.check_call(['say','-v',preferred,'-r',os.environ.get('DS_RATE','177'),'-o',str(path),text])
def duration(path):
    p=subprocess.run([ff(),'-i',str(path)],stderr=subprocess.PIPE,stdout=subprocess.DEVNULL,text=True); m=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',p.stderr); return int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3)) if m else 8

def render(scene,fr,n):
    kind,arg,_=scene; t=fr/max(1,n-1)
    if kind=='founder': return founder_frame(t,False)
    if kind=='close': return founder_frame(t,True)
    if kind=='diagram': return diagram_frame(arg,t)
    if kind=='gate': return gate_frame(t)
    if kind=='fail': return fail_frame(t)
    if kind=='holdout': return holdout_frame(t)
    if kind=='site':
        key,title,sub,focus=arg; return site_frame(ASSETS[key],t,title,sub,focus)
    raise ValueError(kind)

def main():
    fp=founder_path()
    if fp is None:
        print('NOTE: Founder photo not found. Save "Meraj Asari.jpg" in ~/Downloads or set FOUNDER_IMAGE=/absolute/path/photo.jpg')
    else:
        print('Founder portrait:',fp)
    tmp=Path(tempfile.mkdtemp(prefix='dsv6_')); clips=[]
    try:
        for i,s in enumerate(SCENES):
            audio=tmp/f'a{i}.aiff'; voice(s[2],audio); sec=duration(audio)+.28; n=max(1,int(sec*FPS)); raw=tmp/f'r{i}.mp4'
            p=subprocess.Popen([ff(),'-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-an','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p',str(raw)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for fr in range(n): p.stdin.write(render(s,fr,n).tobytes())
            p.stdin.close(); p.wait()
            clip=tmp/f'c{i}.mp4'; subprocess.check_call([ff(),'-y','-i',str(raw),'-i',str(audio),'-c:v','copy','-c:a','aac','-b:a','192k','-shortest',str(clip)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); clips.append(clip)
        lst=tmp/'list.txt'; lst.write_text(''.join(f"file '{x}'\n" for x in clips))
        target=OUT/'data_shepherd_showcase_v6_16x9.mp4'; subprocess.check_call([ff(),'-y','-f','concat','-safe','0','-i',str(lst),'-c','copy',str(target)])
        print(f'\nDONE: {target}\nOpen with: open "{target}"')
    finally:
        shutil.rmtree(tmp,ignore_errors=True)
if __name__=='__main__': main()
