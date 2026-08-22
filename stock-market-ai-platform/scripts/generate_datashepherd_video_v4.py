#!/usr/bin/env python3
"""Data Shepherd Engineering V4 cinematic showcase.

A shorter founder-led film with varied visual grammar: cinematic presenter moments,
animated pipeline/Spark validation, V8 frozen contract, V9 tuning laboratory,
NOT_CONFIRMED beat, Cycle 2, V10 holdout boundary, and dashboard-style close.
Runs locally with Pillow + imageio-ffmpeg + macOS `say`.
"""
from __future__ import annotations
import math, re, shutil, subprocess, sys, tempfile, textwrap
from pathlib import Path
try:
 from PIL import Image,ImageDraw,ImageFont,ImageFilter
 import imageio_ffmpeg
except Exception:
 subprocess.check_call([sys.executable,'-m','pip','install','pillow','imageio-ffmpeg'])
 from PIL import Image,ImageDraw,ImageFont,ImageFilter
 import imageio_ffmpeg
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'; OUT.mkdir(exist_ok=True)
W,H,FPS=1920,1080,30
BG=(4,11,22); PANEL=(9,24,43); TEXT=(245,249,255); MUTED=(153,177,205); CYAN=(52,218,255); GREEN=(60,231,164); GOLD=(246,194,83); RED=(255,77,93); PURPLE=(163,112,255); BORDER=(36,71,106)
def ff(): return imageio_ffmpeg.get_ffmpeg_exe()
def font(n,b=False):
 for p in ['/System/Library/Fonts/Supplemental/Arial Bold.ttf' if b else '/System/Library/Fonts/Supplemental/Arial.ttf','/System/Library/Fonts/Helvetica.ttc']:
  if Path(p).exists():
   try:return ImageFont.truetype(p,n)
   except:pass
 return ImageFont.load_default()
def wrap(s,n): return '\n'.join(textwrap.wrap(s,n))

SCENES=[
('founder','DATA SHEPHERD ENGINEERING','MERAJ ASARI','Founder • Developer • CEO',"I'm Meraj Asari. I founded, architected and developed Data Shepherd Engineering to explore a deceptively difficult question: what does it take to build a machine-learning platform you can actually trust?"),
('mission','NOT JUST A MODEL.','AN ENGINEERING SYSTEM.','Evidence has to survive the pipeline.',"A prediction is easy to display. Trust is harder. So I built Data Shepherd from the data layer upward, with explicit boundaries between data engineering, research, validation, production and evidence that belongs to the future."),
('pipeline','THE DATA PATH','MARKET DATA → BRONZE → SILVER → GOLD → FEATURES','Governed inputs before model inference.',"Market data enters a medallion-style pipeline. Raw observations are preserved, cleaned and standardised, curated into analytical data, and transformed into model-ready features. The model does not get to quietly redefine the data it is tested on."),
('spark','PYSPARK','DISTRIBUTED FEATURE PROCESSING','Pandas ↔ Spark parity • isolated Parquet • fail-closed gates',"As the platform grew, I added a PySpark feature backend alongside Pandas through a shared source contract. Spark can scale the feature path, but downstream model work only continues after validation proves the materialised universe is complete and consistent."),
('gate','VALIDATION GATE','101 / 101','PASS',"That gate currently checks the full materialised feature universe. One hundred and one out of one hundred and one checks must pass. If the data contract fails, the model pipeline stops. That is deliberate."),
('v8','V8','FROZEN PRODUCTION REFERENCE','100 stocks → rank → Top 10 → 5-session hold → forward evidence',"V8 is frozen on purpose. It ranks a one-hundred-stock universe, selects the top ten, uses a five-session holding period and a next-open execution assumption, with transaction costs fixed. Its forward evidence is append-only. It is not another tuning set."),
('lab','V9','AUTOMATIC TUNING — WITHOUT AUTOMATIC HINDSIGHT','27 predeclared challengers enter the laboratory.',"V9 adds automatic model research. Cycle One begins with twenty-seven deterministic challengers registered before evaluation. Candidate identity is immutable, because an automated search should never be allowed to rewrite its experiment after seeing the answer."),
('folds','V9','PURGED WALK-FORWARD','Five chronological folds • ten-session purge • turnover • costs',"The candidates move through five chronological walk-forward folds with a ten-session purge. Exits must remain inside their validation window, turnover is modelled, costs are charged, and the selection objective is declared in advance."),
('fail','THE WINNER FAILED.','NOT CONFIRMED','So Data Shepherd rejected it.',"And this is one of my favourite parts of the system. The development winner failed confirmation. So Data Shepherd rejected it. No runner-up substitution. No lowering the bar. V8 remained unchanged."),
('cycle2','V9 CYCLE 2','54 CANDIDATES','Risk-controlled tuning • active research',"The next cycle expands the research without relaxing the gate. Fifty-four deterministic candidates explore broader portfolio sizes, longer holding periods and explicit trend-based exposure controls. This is active research, not a production claim."),
('v10','V10','REGIME-CONDITIONED CHALLENGER','Discovery → robustness → fixed-contract simulation → pre-freeze gate',"V10 is a separate challenger track. It explores regime-conditioned ranking through staged discovery, robustness testing, fixed-contract simulation and a pre-freeze gate before prospective confirmation against frozen V8."),
('holdout','THE FUTURE IS RESERVED.','2 NOVEMBER 2026','V10 formal holdout begins here.',"Then comes the boundary the model cannot cross. V10's formal holdout begins on the second of November, twenty twenty-six. That data belongs to the future. Research and confirmation do not get to see it yet."),
('dashboard','EVERYTHING BECOMES OBSERVABLE.','DATA SHEPHERD — PRODUCTION & RESEARCH','Pipelines • model evidence • monitoring • governance',"All of that evidence ultimately surfaces as an observable engineering system: scheduled orchestration, model contracts, health monitoring, research artifacts and dashboards. Not a black-box prediction. A system you can inspect."),
('close','DATA SHEPHERD ENGINEERING','BUILT BY MERAJ ASARI','Evidence over promises. Reproducibility over hindsight.',"Data Shepherd Engineering is my attempt to bring distributed data engineering, machine learning, quantitative research and model governance into one coherent platform. Engineered for the markets. Built for the future. And every result has to earn its way through the pipeline.")]

def background(frame):
 im=Image.new('RGB',(W,H),BG); d=ImageDraw.Draw(im)
 for i in range(45):
  x=int((i*227+frame*2.7)%W); y=(i*149)%H; d.ellipse((x,y,x+3,y+3),fill=(20,69,94))
 return im

def title(d,a,b,c):
 d.text((100,90),a,font=font(25,True),fill=CYAN); d.multiline_text((100,145),wrap(b,27),font=font(68,True),fill=TEXT,spacing=8); d.multiline_text((100,315),wrap(c,48),font=font(32),fill=MUTED,spacing=8)
def presenter(d,phase,founder=False):
 # intentionally cinematic silhouette/portrait treatment rather than fake lip-sync
 x0,y0,x1,y1=1300,95,1815,995; d.rounded_rectangle((x0,y0,x1,y1),38,fill=(8,20,35),outline=(26,69,96),width=2)
 cx=1558+int(5*math.sin(phase*math.pi)); cy=355
 d.ellipse((cx-155,cy-205,cx+155,cy+205),fill=(51,31,23)); d.ellipse((cx-108,cy-160,cx+108,cy+135),fill=(224,177,145)); d.rectangle((cx-42,cy+110,cx+42,cy+190),fill=(224,177,145))
 d.ellipse((cx-65,cy-45,cx-30,cy-18),fill=(245,245,240)); d.ellipse((cx+30,cy-45,cx+65,cy-18),fill=(245,245,240)); d.ellipse((cx-52,cy-40,cx-39,cy-23),fill=(53,78,68)); d.ellipse((cx+39,cy-40,cx+52,cy-23),fill=(53,78,68)); d.arc((cx-38,cy+40,cx+38,cy+87),5,175,fill=(145,65,68),width=5)
 d.polygon([(x0+40,y1),(cx-110,cy+165),(cx+110,cy+165),(x1-40,y1)],fill=(14,27,43));
 label='FOUNDER • DEVELOPER • CEO' if founder else 'DATA SHEPHERD'
 d.text((x0+35,y1-65),label,font=font(21,True),fill=CYAN)
def pipe(d,labels,phase,y=650):
 left=100; total=1120; gap=22; bw=(total-gap*(len(labels)-1))//len(labels)
 active=min(len(labels)-1,int(phase*len(labels)))
 for i,l in enumerate(labels):
  x=left+i*(bw+gap); col=GREEN if i<=active else BORDER
  d.rounded_rectangle((x,y,x+bw,y+120),20,fill=PANEL,outline=col,width=3); box=d.textbbox((0,0),l,font=font(22,True)); d.text((x+(bw-(box[2]-box[0]))//2,y+45),l,font=font(22,True),fill=TEXT)
  if i<len(labels)-1:
   d.line((x+bw,y+60,x+bw+gap,y+60),fill=CYAN,width=4); pos=x+bw+int((phase*4%1)*gap); d.ellipse((pos-5,y+55,pos+5,y+65),fill=GREEN)
def dashboard(d,frame):
 d.rounded_rectangle((95,520,1770,950),28,fill=(6,20,36),outline=BORDER,width=2)
 # chart
 pts=[]
 for i in range(100):
  x=145+i*11; y=840-int(i*2.2)-int(55*math.sin(i/8))-int(20*math.sin(i/2.8)); pts.append((x,y))
 d.line(pts,fill=GREEN,width=5); d.line((145,860,1240,860),fill=(35,65,91),width=2)
 for j,(lab,val) in enumerate([('V8','LIVE'),('SPARK','101/101'),('V9','RESEARCH'),('V10','CHALLENGER')]):
  x=1300; y=555+j*88; d.rounded_rectangle((x,y,1695,y+65),15,fill=PANEL,outline=GREEN if j<2 else CYAN,width=2); d.text((x+20,y+18),lab,font=font(20,True),fill=TEXT); d.text((x+220,y+18),val,font=font(20,True),fill=GREEN if j<2 else CYAN)
def frame_for(kind,a,b,c,fr,n):
 phase=fr/max(1,n-1); im=background(fr); d=ImageDraw.Draw(im); title(d,a,b,c)
 if kind in ('founder','mission'): presenter(d,phase,founder=kind=='founder')
 elif kind=='pipeline': pipe(d,['MARKET','BRONZE','SILVER','GOLD','FEATURES'],phase)
 elif kind=='spark':
  pipe(d,['RAW DATA','PYSPARK','PARQUET','VALIDATE','MODELS'],phase); d.text((120,835),'DISTRIBUTED',font=font(31,True),fill=CYAN); d.text((410,835),'•',font=font(31),fill=MUTED); d.text((450,835),'PARALLEL',font=font(31,True),fill=GREEN); d.text((670,835),'•',font=font(31),fill=MUTED); d.text((710,835),'FAIL-CLOSED',font=font(31,True),fill=GOLD)
 elif kind=='gate':
  d.rounded_rectangle((360,520,1120,860),40,fill=(7,30,28),outline=GREEN,width=5); d.text((505,575),'101 / 101',font=font(92,True),fill=GREEN); d.text((610,715),'PASS',font=font(62,True),fill=TEXT); d.ellipse((1220,550,1540,870),outline=GREEN,width=12); d.line((1300,710,1370,780),fill=GREEN,width=18); d.line((1370,780,1490,625),fill=GREEN,width=18)
 elif kind=='v8':
  d.rounded_rectangle((180,530,760,900),35,fill=(8,25,42),outline=CYAN,width=3); d.text((350,570),'V8',font=font(140,True),fill=CYAN); d.text((270,760),'FROZEN',font=font(46,True),fill=TEXT); d.text((295,820),'MODEL CONTRACT',font=font(24,True),fill=MUTED); pipe(d,['100 STOCKS','RANK','TOP 10','HOLD 5','EVIDENCE'],phase,y=590)
 elif kind=='lab':
  for i in range(27):
   x=120+(i%9)*115; y=560+(i//9)*105; col=[GREEN,GOLD,CYAN][i%3]; r=18+int(3*math.sin(fr/8+i)); d.ellipse((x-r,y-r,x+r,y+r),fill=col); d.text((x-16,y+28),f'{i+1:02}',font=font(14,True),fill=MUTED)
  d.text((120,885),'27 PREDECLARED CHALLENGERS',font=font(32,True),fill=TEXT)
 elif kind=='folds': pipe(d,['FOLD 1','FOLD 2','FOLD 3','FOLD 4','FOLD 5'],phase,y=630)
 elif kind=='fail':
  d.rounded_rectangle((280,560,1280,790),30,fill=(38,8,16),outline=RED,width=4); d.text((415,610),'NOT CONFIRMED',font=font(74,True),fill=RED); d.text((410,830),'NO SWAP.  NO EXCEPTIONS.  V8 UNCHANGED.',font=font(27,True),fill=TEXT)
 elif kind=='cycle2':
  d.ellipse((350,500,850,1000),outline=CYAN,width=7); d.text((480,585),'54',font=font(150,True),fill=CYAN); d.text((435,770),'CANDIDATES',font=font(37,True),fill=TEXT); pipe(d,['TOP 10/15/20','10/20 HOLD','RISK CONTROL'],phase,y=650)
 elif kind=='v10':
  d.ellipse((350,520,820,990),outline=CYAN,width=8); d.text((455,630),'V10',font=font(115,True),fill=CYAN); pipe(d,['DISCOVER','ROBUST','SIMULATE','PRE-FREEZE','CONFIRM'],phase,y=650)
 elif kind=='holdout':
  y=690; d.line((180,y,1680,y),fill=(73,92,112),width=5); bx=1050; d.line((180,y,bx,y),fill=GREEN,width=8); d.line((bx,y-120,bx,y+150),fill=RED,width=5); d.text((850,535),'2 NOV 2026',font=font(34,True),fill=RED); d.text((250,745),'RESEARCH + CONFIRMATION',font=font(27,True),fill=GREEN); d.text((1140,745),'FORMAL HOLDOUT',font=font(27,True),fill=MUTED)
 elif kind=='dashboard': dashboard(d,fr)
 elif kind=='close': presenter(d,phase,founder=True); d.text((100,600),'EVIDENCE',font=font(48,True),fill=GREEN); d.text((100,670),'OVER PROMISES.',font=font(48,True),fill=TEXT); d.text((100,780),'REPRODUCIBILITY',font=font(38,True),fill=CYAN); d.text((100,840),'OVER HINDSIGHT.',font=font(38,True),fill=TEXT)
 d.text((100,1020),'DATA SHEPHERD ENGINEERING',font=font(18,True),fill=(87,119,149)); return im

def voice(text,path):
 out='';
 try: out=subprocess.check_output(['say','-v','?'],text=True)
 except: pass
 voice='Serena' if 'Serena' in out else ('Kate' if 'Kate' in out else ('Daniel' if 'Daniel' in out else 'Samantha'))
 subprocess.check_call(['say','-v',voice,'-r','174','-o',str(path),text])
def dur(path):
 p=subprocess.run([ff(),'-i',str(path)],stderr=subprocess.PIPE,stdout=subprocess.DEVNULL,text=True); m=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',p.stderr); return int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3)) if m else 8

def main():
 tmp=Path(tempfile.mkdtemp(prefix='dsv4_')); clips=[]
 try:
  for i,s in enumerate(SCENES):
   audio=tmp/f'a{i}.aiff'; voice(s[4],audio); seconds=dur(audio)+.45; n=int(seconds*FPS); raw=tmp/f'r{i}.mp4'
   proc=subprocess.Popen([ff(),'-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-an','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p',str(raw)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   for fr in range(n): proc.stdin.write(frame_for(*s[:4],fr,n).tobytes())
   proc.stdin.close(); proc.wait(); clip=tmp/f'c{i}.mp4'; subprocess.check_call([ff(),'-y','-i',str(raw),'-i',str(audio),'-c:v','copy','-c:a','aac','-b:a','192k','-shortest',str(clip)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); clips.append(clip)
  lst=tmp/'list.txt'; lst.write_text(''.join(f"file '{x}'\n" for x in clips)); target=OUT/'data_shepherd_showcase_v4_16x9.mp4'; subprocess.check_call([ff(),'-y','-f','concat','-safe','0','-i',str(lst),'-c','copy',str(target)]); print(f'\nDONE: {target}\nopen "{target}"')
 finally: shutil.rmtree(tmp,ignore_errors=True)
if __name__=='__main__': main()
