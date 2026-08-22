#!/usr/bin/env python3
"""Data Shepherd Engineering V6 launch film — cinematic technical edition."""
from __future__ import annotations
import math,os,re,shutil,subprocess,sys,tempfile
from pathlib import Path
try:
 from PIL import Image,ImageDraw,ImageFont,ImageEnhance,ImageOps
 import imageio_ffmpeg
except Exception:
 subprocess.check_call([sys.executable,'-m','pip','install','pillow','imageio-ffmpeg']); from PIL import Image,ImageDraw,ImageFont,ImageEnhance,ImageOps; import imageio_ffmpeg
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'; OUT.mkdir(exist_ok=True); W,H,FPS=1920,1080,30
BG=(5,14,26); PANEL=(10,26,46); TEXT=(246,250,255); MUTED=(157,180,205); CYAN=(54,216,255); GREEN=(57,227,161); GOLD=(242,194,88); RED=(255,82,99); BORDER=(39,73,108)
LOGO=ROOT/'webapp/static/images/data-shepherd-logo.png'; LANDING=ROOT/'webapp/static/images/landing'; ASSETS={'overview':LANDING/'platform-overview-2026.png','dashboard':LANDING/'platform-dashboard.png','engineering':LANDING/'platform-engineering.png'}
def ff():return imageio_ffmpeg.get_ffmpeg_exe()
def font(n,b=False):
 for p in ['/System/Library/Fonts/Supplemental/Arial Bold.ttf' if b else '/System/Library/Fonts/Supplemental/Arial.ttf','/System/Library/Fonts/Helvetica.ttc']:
  if Path(p).exists():
   try:return ImageFont.truetype(p,n)
   except:pass
 return ImageFont.load_default()
def ease(t):return t*t*(3-2*t)
def fp():
 for p in [os.environ.get('FOUNDER_IMAGE'),ROOT/'assets/video/meraj-asari.jpg',Path.home()/'Downloads/Meraj Asari.jpg',Path.home()/'Desktop/Meraj Asari.jpg']:
  if p and Path(p).exists():return Path(p)
def load(p):return ImageOps.exif_transpose(Image.open(p)).convert('RGB')
def cover(im,size,z=1,x=.5,y=.42):
 tw,th=size; sw,sh=im.size;s=max(tw/sw,th/sh)*z;im=im.resize((int(sw*s),int(sh*s)),Image.Resampling.LANCZOS);nw,nh=im.size;xx=max(0,min(nw-tw,int((nw-tw)*x)));yy=max(0,min(nh-th,int((nh-th)*y)));return im.crop((xx,yy,xx+tw,yy+th))
def logo(im,x=60,y=32,mw=310,mh=120):
 if LOGO.exists():lg=Image.open(LOGO).convert('RGBA');lg.thumbnail((mw,mh),Image.Resampling.LANCZOS);im.paste(lg,(x,y),lg)
def bg():
 im=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(im)
 for x in range(0,W,80):d.line((x,0,x,H),fill=(7,24,40))
 for y in range(0,H,80):d.line((0,y,W,y),fill=(7,24,40))
 return im
def head(im,a,b):logo(im);d=ImageDraw.Draw(im);d.text((390,52),a,font=font(49,True),fill=TEXT);d.text((392,118),b,font=font(25),fill=MUTED)
def founder(t,close=False):
 im=Image.new('RGB',(W,H),BG);p=fp()
 if p:
  ph=ImageEnhance.Color(ImageEnhance.Contrast(load(p)).enhance(1.05)).enhance(.92);im.paste(cover(ph,(900,H),1.02+.05*ease(t),.5,.22),(1020,0));ov=Image.new('RGBA',(W,H),(0,0,0,0));od=ImageDraw.Draw(ov)
  for x in range(760,1250):od.line((x,0,x,H),fill=(5,14,26,int(255*max(0,min(1,(1250-x)/490)))))
  im=Image.alpha_composite(im.convert('RGBA'),ov).convert('RGB')
 logo(im,75,50,560,210);d=ImageDraw.Draw(im);d.text((95,325),'MERAJ ASARI',font=font(73,True),fill=CYAN);d.text((98,415),'FOUNDER  •  DEVELOPER  •  CEO',font=font(30,True),fill=TEXT)
 if close:d.multiline_text((98,545),'Evidence over promises.\nReproducibility over hindsight.',font=font(47,True),fill=TEXT,spacing=15);d.text((100,825),'ENGINEERED FOR THE MARKETS. BUILT FOR THE FUTURE.',font=font(27,True),fill=GREEN)
 else:d.multiline_text((98,545),'Founder of\nData Shepherd Engineering',font=font(49,True),fill=TEXT,spacing=12);d.multiline_text((100,720),'Data engineering • distributed processing •\nmachine learning • model governance',font=font(27),fill=MUTED,spacing=10)
 return im
def site(path,t,a,b):
 im=bg();head(im,a,b);d=ImageDraw.Draw(im);area=(70,200,1850,1015)
 if path.exists():im.paste(cover(load(path),(1780,815),1+.09*ease(t),.5+.05*math.sin(t*math.pi),.47),(70,200))
 d.rounded_rectangle(area,26,outline=CYAN,width=3);return im
def node(d,x,y,label,icon,col,on):
 d.rounded_rectangle((x-125,y-85,x+125,y+85),24,fill=PANEL,outline=col if on else BORDER,width=4);d.text((x-40,y-34),icon,font=font(50,True),fill=col if on else MUTED);bb=d.textbbox((0,0),label,font=font(18,True));d.text((x-(bb[2]-bb[0])/2,y+43),label,font=font(18,True),fill=TEXT)
def diagram(k,t):
 meta={'pipeline':('END-TO-END DATA ARCHITECTURE','Governed model inputs from ingestion to features'),'spark':('PYSPARK IN PRODUCTION','Distributed feature processing with fail-closed validation'),'v9':('V9 AUTOMATIC TUNING ENGINE','Bounded search. Chronological evidence. Locked confirmation.'),'cycle2':('V9 CYCLE 2 — ACTIVE RESEARCH','A wider search under the same scientific constraints'),'v10':('V10 — REGIME-CONDITIONED CHALLENGER','A separate staged challenger track')};im=bg();head(im,*meta[k]);d=ImageDraw.Draw(im)
 if k in ('pipeline','spark'):
  labs=[('INGEST','↓'),('BRONZE','●'),('SILVER','●'),('GOLD','●'),('FEATURES','◇')] if k=='pipeline' else [('MARKET','◉'),('PYSPARK','✦'),('PARQUET','▤'),('101 / 101','✓'),('MODELS','◆')];xs=[220,570,920,1270,1620]
  for i,(a,ic) in enumerate(labs):node(d,xs[i],590,a,ic,GREEN if (k=='spark' and i==3) else CYAN,i<=int(t*5));
  for i in range(4):d.line((xs[i]+130,590,xs[i+1]-130,590),fill=GREEN if k=='spark' else CYAN,width=4)
  if k=='pipeline':
   for x,s in zip(xs,['LIVE MARKET','RAW IMMUTABLE','CLEANSED','CURATED','ML READY']):d.text((x-70,715),s,font=font(16,True),fill=MUTED)
   d.text((500,855),'PRESERVE  →  STANDARDISE  →  CURATE  →  MODEL',font=font(30,True),fill=GREEN)
  else:d.rounded_rectangle((430,790,1490,930),24,fill=(6,26,34),outline=GREEN,width=3);d.text((510,825),'DISTRIBUTED  •  PARALLEL  •  VALIDATED  •  FAIL-CLOSED',font=font(27,True),fill=TEXT);d.text((650,875),'NO DOWNSTREAM WORK UNTIL THE CONTRACT PASSES',font=font(20,True),fill=GREEN)
 elif k=='v9':
  d.ellipse((250,410,610,770),outline=CYAN,width=6);d.text((350,500),'27',font=font(115,True),fill=CYAN);d.text((315,635),'CANDIDATES',font=font(24,True),fill=TEXT)
  for i,(a,x) in enumerate([('REGISTER',800),('5 FOLDS',1080),('LOCK',1360),('CONFIRM',1640)]):node(d,x,590,a,'✓' if i<3 else '?',GREEN if i<3 else GOLD,i<=int(t*5))
  d.text((660,850),'DECLARE FIRST  →  EVALUATE  →  LOCK  →  CONFIRM',font=font(29,True),fill=GREEN)
 elif k=='cycle2':
  d.ellipse((205,405,575,775),outline=CYAN,width=6);d.text((300,500),'54',font=font(120,True),fill=CYAN);d.text((270,640),'CANDIDATES',font=font(24,True),fill=TEXT)
  for i,(a,b) in enumerate([('TOP N','10 / 15 / 20'),('HOLD','10 / 20 sessions'),('EXPOSURE','trend controlled'),('COST','10 / 30 bps')]):x=700+(i%2)*460;y=405+(i//2)*250;d.rounded_rectangle((x,y,x+400,y+190),25,fill=PANEL,outline=GREEN if i<int(t*5) else BORDER,width=4);d.text((x+28,y+28),a,font=font(22,True),fill=CYAN);d.text((x+28,y+88),b,font=font(30,True),fill=TEXT)
  d.text((560,900),'WIDER SEARCH. SAME RULES. HIGHER STANDARDS.',font=font(29,True),fill=GREEN)
 else:
  d.ellipse((180,420,540,780),outline=CYAN,width=7);d.text((245,525),'V10',font=font(100,True),fill=CYAN)
  for i,(a,b) in enumerate([('1  DISCOVERY','regime ranking'),('2  ROBUSTNESS','validation'),('3  SIMULATION','fixed contract'),('4  PRE-FREEZE','challenger gate')]):x=690+(i%2)*500;y=390+(i//2)*245;d.rounded_rectangle((x,y,x+440,y+190),24,fill=PANEL,outline=GREEN if i<int(t*5) else BORDER,width=4);d.text((x+25,y+30),a,font=font(25,True),fill=TEXT);d.text((x+25,y+92),b,font=font(21),fill=MUTED)
  d.text((735,885),'PROSPECTIVE CONFIRMATION  VS  FROZEN V8',font=font(28,True),fill=GOLD)
 return im
def gate(t):
 im=bg();head(im,'FAIL-CLOSED VALIDATION GATE','Spark materialised-output parity protects downstream model work');d=ImageDraw.Draw(im);d.rounded_rectangle((300,360,1170,830),42,fill=(5,32,28),outline=GREEN,width=6);d.text((445,440),'101 / 101',font=font(110,True),fill=GREEN);d.text((580,605),'PASS',font=font(78,True),fill=TEXT);d.text((420,750),'FEATURE CONTRACT VERIFIED',font=font(27,True),fill=MUTED);d.ellipse((1320,390,1660,730),outline=GREEN,width=13);d.line((1395,560,1470,635),fill=GREEN,width=20);d.line((1470,635,1600,475),fill=GREEN,width=20);d.text((1240,790),'DOWNSTREAM UNLOCKED',font=font(25,True),fill=GREEN);return im
def fail(t):
 im=Image.new('RGB',(W,H),(14,2,7));logo(im);d=ImageDraw.Draw(im);d.text((190,245),'THE DEVELOPMENT WINNER',font=font(36,True),fill=MUTED);d.text((190,305),'FAILED CONFIRMATION.',font=font(68,True),fill=TEXT)
 if t>.15:d.rounded_rectangle((190,465,1510,730),34,fill=(50,4,13),outline=RED,width=7);d.text((385,535),'NOT CONFIRMED',font=font(94,True),fill=RED)
 if t>.43:d.text((205,800),'NO SWAP.  NO LOWER BAR.  NO EXCEPTIONS.',font=font(32,True),fill=TEXT)
 if t>.62:d.text((205,858),'V8 REMAINS THE FROZEN PRODUCTION REFERENCE.',font=font(27,True),fill=GREEN)
 return im
def hold(t):
 im=bg();head(im,'V10 HOLDOUT PROTECTION','The future is reserved by design');d=ImageDraw.Draw(im);y=590;sep=1100;d.line((180,y,1730,y),fill=(65,88,110),width=7);d.line((180,y,sep,y),fill=GREEN,width=11)
 for x,lab in [(320,'SEP 1'),(700,'RESEARCH'),(1000,'CONFIRM')]:d.ellipse((x-9,y-9,x+9,y+9),fill=GREEN);d.text((x-35,y-62),lab,font=font(16,True),fill=MUTED)
 d.line((sep,y-160,sep,y+210),fill=RED,width=7);d.text((920,380),'2 NOV 2026',font=font(42,True),fill=RED);d.text((275,680),'RESEARCH + CONFIRMATION',font=font(29,True),fill=GREEN);d.text((1260,680),'FORMAL HOLDOUT',font=font(29,True),fill=MUTED);dark=Image.new('RGBA',(W,H),(0,0,0,0));ImageDraw.Draw(dark).rectangle((sep,230,W,H),fill=(0,0,0,int(130+110*ease(t))));im=Image.alpha_composite(im.convert('RGBA'),dark).convert('RGB');ImageDraw.Draw(im).text((525,865),'NO PEEKING.  NO LEAKAGE.  THE MODEL WAITS.',font=font(33,True),fill=TEXT);return im
SC=[('founder',None,"This is Meraj Asari — Founder, Developer and CEO of Data Shepherd Engineering. He built the platform around one question: what does it take to create a machine-learning system you can actually trust?"),('site',('overview','THE REAL PLATFORM','A live engineering system, not a notebook demo'),"Data Shepherd brings production data pipelines, distributed processing, machine learning, quantitative research and model governance into one observable system."),('diagram','pipeline',"Market data moves through a medallion-style path: raw observations are preserved, cleaned, curated and transformed into model-ready features before inference begins."),('diagram','spark',"PySpark now runs alongside Pandas through a shared feature contract. Distributed processing can scale the path, but validation protects the meaning of every downstream feature."),('gate',None,"Before model work continues, the materialised feature universe has to pass its validation gate. One hundred and one out of one hundred and one checks. If the contract breaks, the pipeline stops."),('site',('dashboard','THE PRODUCT','Actual Data Shepherd dashboard imagery'),"That engineering ultimately surfaces in the product itself: model rankings, portfolio evidence, holdout monitoring and operational state are visible instead of hidden behind a black box."),('diagram','v9',"V9 adds bounded automatic tuning. Candidate configurations are declared before evaluation, tested chronologically, and the development winner is locked before confirmation."),('fail',None,"Then the winner failed confirmation. Data Shepherd rejected it. No runner-up substitution. No lower bar. Frozen V8 stayed exactly where it was."),('diagram','cycle2',"Cycle Two expands the search to fifty-four deterministic candidates, exploring broader portfolio sizes, longer holds and risk-controlled exposure while preserving the same confirmation standard."),('diagram','v10',"V10 is a separate regime-conditioned challenger. Discovery, robustness testing, fixed-contract simulation and a pre-freeze gate all come before prospective confirmation against V8."),('hold',None,"And the most important line is the one the model cannot cross. V10's formal holdout begins on the second of November, twenty twenty-six. That future evidence stays untouched until the protocol allows it."),('site',('engineering','ENGINEERING, MADE OBSERVABLE','Real platform architecture and operating surfaces'),"The result is not a single prediction. It is an engineering system you can inspect: pipelines, validation, research artifacts, model contracts, monitoring and production state."),('close',None,"Data Shepherd Engineering is Meraj Asari's attempt to make every result earn its way through the pipeline. Evidence over promises. Reproducibility over hindsight. Engineered for the markets. Built for the future.")]
def frame(s,t):
 typ,arg,_=s
 if typ=='founder':return founder(t)
 if typ=='close':return founder(t,True)
 if typ=='site':return site(ASSETS[arg[0]],t,arg[1],arg[2])
 if typ=='diagram':return diagram(arg,t)
 if typ=='gate':return gate(t)
 if typ=='fail':return fail(t)
 return hold(t)
def voice(text,path):
 try:vlist=subprocess.check_output(['say','-v','?'],text=True)
 except:vlist=''
 v='Serena' if 'Serena' in vlist else ('Kate' if 'Kate' in vlist else ('Daniel' if 'Daniel' in vlist else 'Samantha'));subprocess.check_call(['say','-v',v,'-r','182','-o',str(path),text])
def dur(p):
 q=subprocess.run([ff(),'-i',str(p)],stderr=subprocess.PIPE,stdout=subprocess.DEVNULL,text=True);m=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',q.stderr);return int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3)) if m else 8
def main():
 tmp=Path(tempfile.mkdtemp(prefix='dsv6_'));clips=[]
 try:
  for i,s in enumerate(SC):
   a=tmp/f'a{i}.aiff';voice(s[2],a);sec=dur(a)+.32;n=int(sec*FPS);raw=tmp/f'r{i}.mp4';p=subprocess.Popen([ff(),'-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-an','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p',str(raw)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   for fr in range(n):p.stdin.write(frame(s,fr/max(1,n-1)).tobytes())
   p.stdin.close();p.wait();c=tmp/f'c{i}.mp4';subprocess.check_call([ff(),'-y','-i',str(raw),'-i',str(a),'-c:v','copy','-c:a','aac','-b:a','192k','-shortest',str(c)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);clips.append(c)
  lst=tmp/'list.txt';lst.write_text(''.join(f"file '{x}'\n" for x in clips));target=OUT/'data_shepherd_showcase_v6_16x9.mp4';subprocess.check_call([ff(),'-y','-f','concat','-safe','0','-i',str(lst),'-c','copy',str(target)]);print(f'\nDONE: {target}\nopen "{target}"')
 finally:shutil.rmtree(tmp,ignore_errors=True)
if __name__=='__main__':main()
