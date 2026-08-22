#!/usr/bin/env python3
"""Data Shepherd Engineering showcase V11.

Changes over V10:
- clearer explanation that V8, V9 and V10 are generations of ML/AI models
- dedicated model-lineage visual before the V9 research section
- warmer, less synthetic British-female narration with clause-level pacing variation
- retains the improved phone dashboard and evidence-led confirmation explainer
"""
from __future__ import annotations
import importlib.util, os, re, shutil, subprocess, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("dsv10", HERE / "generate_datashepherd_video_v10.py")
v10 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v10)
v9 = v10.v9
v8 = v10.v8
v7 = v10.v7
v6 = v10.v6


def choose_voice() -> str:
    requested = os.environ.get("DS_VOICE", "").strip()
    if requested:
        return requested
    try:
        listing = subprocess.check_output(["say", "-v", "?"], text=True)
    except Exception:
        listing = ""
    # Prefer newer/softer British female voices when present.
    for name in ("Martha", "Serena", "Kate", "Stephanie"):
        if re.search(rf"(?m)^{re.escape(name)}\s+", listing):
            return name
    for line in listing.splitlines():
        if "en_GB" in line:
            name = line.split()[0]
            if name not in {"Daniel", "Oliver", "Arthur", "Eddy", "Reed", "Rocko"}:
                return name
    return "Samantha"


def _clauses(text: str):
    # Smaller phrases give Apple's speech engine more natural resets and less robotic prosody.
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    out=[]
    for sentence in sentences:
        if not sentence.strip():
            continue
        bits = re.split(r"(?<=[,:;])\s+|\s+(?=but\b|so\b|while\b|because\b|and then\b)", sentence.strip(), flags=re.I)
        buf=""
        for bit in bits:
            bit=bit.strip()
            if not bit:
                continue
            candidate=(buf+" "+bit).strip() if buf else bit
            # Avoid over-fragmenting very short clauses.
            if len(candidate.split()) < 7:
                buf=candidate
            else:
                if buf:
                    out.append(buf)
                buf=bit
        if buf:
            out.append(buf)
    return out


def natural_british_voice(text, path):
    voice_name = choose_voice()
    base = int(os.environ.get("DS_RATE", "188"))
    tmp = Path(tempfile.mkdtemp(prefix="ds_voice11_"))
    try:
        clauses = _clauses(text)
        files=[]
        # Gentle pace variation around a calmer base. Important phrases slow slightly.
        for i, clause in enumerate(clauses):
            lower=clause.lower()
            emphasis = any(k in lower for k in (
                "machine-learning", "machine learning", "artificial intelligence", "ai model",
                "v8", "v9", "v10", "not confirmed", "formal holdout", "rejected"
            ))
            rate = base - 5 if emphasis else base + (2 if i % 4 == 1 else (-2 if i % 4 == 3 else 0))
            seg=tmp/f"seg_{i:03d}.aiff"
            # Punctuation and ellipses encourage more human cadence without changing meaning.
            spoken=clause
            if emphasis and not spoken.endswith(('.', '!', '?')):
                spoken += "."
            subprocess.check_call(["say","-v",voice_name,"-r",str(rate),"-o",str(seg),spoken])
            files.append(seg)
            if i < len(clauses)-1:
                pause=0.10
                if clause.endswith(('.', '!', '?')):
                    pause=0.22
                if any(k in lower for k in ("not confirmed","rejected","formal holdout")):
                    pause=0.30
                sil=tmp/f"sil_{i:03d}.aiff"
                subprocess.check_call([v6.ff(),"-y","-f","lavfi","-i","anullsrc=r=22050:cl=mono","-t",str(pause),"-c:a","pcm_s16be",str(sil)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                files.append(sil)
        concat=tmp/'list.txt'; concat.write_text(''.join(f"file '{p}'\n" for p in files))
        raw=tmp/'joined.aiff'
        subprocess.check_call([v6.ff(),"-y","-f","concat","-safe","0","-i",str(concat),"-ar","22050","-ac","1","-c:a","pcm_s16be",str(raw)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        # Minimal mastering: retain natural dynamics and reduce the synthetic 'radio' sheen.
        filters=(
            "highpass=f=60,lowpass=f=14000,"
            "equalizer=f=190:t=q:w=1.0:g=0.8,"
            "equalizer=f=2800:t=q:w=1.3:g=-0.5,"
            "acompressor=threshold=-18dB:ratio=1.25:attack=35:release=260:makeup=0.5,"
            "loudnorm=I=-17:TP=-1.8:LRA=10"
        )
        subprocess.check_call([v6.ff(),"-y","-i",str(raw),"-af",filters,str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    finally:
        shutil.rmtree(tmp,ignore_errors=True)
    print(f"Narration voice: {voice_name} (natural British female, ~{base} wpm)")

v6.voice = natural_british_voice


# Dedicated explainer so viewers understand V8/V9/V10 are ML/AI model generations.
def model_lineage_frame(t):
    im=v6.bg(); v6.head(im,"THE MODEL GENERATIONS","V8, V9 and V10 are successive machine-learning / AI model systems")
    d=v6.ImageDraw.Draw(im)
    cols=[
        (120,330,600,820,"V8","FROZEN ML MODEL","Production reference","Ranks the stock universe\nand produces portfolio signals",v6.GREEN),
        (720,330,1200,820,"V9","AUTO-TUNING ML RESEARCH","Challenger generation","Searches bounded candidate\nconfigurations and validates them",v6.CYAN),
        (1320,330,1800,820,"V10","REGIME-AWARE ML CHALLENGER","Next-generation research","Explores regime-conditioned\nranking under a separate protocol",v6.GOLD),
    ]
    active=min(2,int(t*3))
    for i,(x0,y0,x1,y1,ver,label,sub,body,col) in enumerate(cols):
        outline=col if i<=active else v6.BORDER
        d.rounded_rectangle((x0,y0,x1,y1),30,fill=v6.PANEL,outline=outline,width=5)
        d.text((x0+40,y0+40),ver,font=v6.font(76,True),fill=col)
        d.text((x0+40,y0+145),label,font=v6.font(22,True),fill=v6.TEXT)
        d.text((x0+40,y0+198),sub,font=v6.font(18,True),fill=v6.MUTED)
        d.line((x0+40,y0+245,x1-40,y0+245),fill=v6.BORDER,width=2)
        d.multiline_text((x0+40,y0+285),body,font=v6.font(24),fill=v6.TEXT,spacing=10)
        d.rounded_rectangle((x0+40,y1-92,x1-40,y1-42),15,fill=(6,20,34),outline=outline,width=2)
        d.text((x0+70,y1-78),"MACHINE LEARNING / AI",font=v6.font(18,True),fill=col)
    d.text((430,900),"THE VERSION NUMBER DESCRIBES THE MODEL GENERATION — NOT A SOFTWARE RELEASE.",font=v6.font(27,True),fill=v6.CYAN)
    return im


# Preserve the V10 frame renderer before wrapping it.
_frame_base=v6.frame

def frame_v11(scene,t):
    if scene[0]=='model_lineage':
        return model_lineage_frame(t)
    return _frame_base(scene,t)
v6.frame=frame_v11


# Insert the model explainer immediately before V9 tuning.
insert_at=None
for i,scene in enumerate(v6.SC):
    if scene[0]=='diagram' and scene[1]=='v9':
        insert_at=i
        break
if insert_at is not None:
    v6.SC.insert(insert_at,(
        'model_lineage',None,
        "Before we go further, V8, V9 and V10 are not website versions. They are successive generations of Data Shepherd's machine-learning and artificial-intelligence model systems. V8 is the frozen production reference model. V9 is the automatic-tuning research generation that searches and validates bounded challenger configurations. V10 is a separate, regime-aware machine-learning challenger with its own validation and future holdout protocol."
    ))

# Make later references self-explanatory too.
for i,scene in enumerate(v6.SC):
    if scene[0]=='diagram' and scene[1]=='v9':
        v6.SC[i]=('diagram','v9',"V9, the automatic-tuning machine-learning research model, begins with candidate configurations declared before evaluation. Those AI model candidates are tested chronologically, and the development winner is locked before independent confirmation.")
    elif scene[0]=='diagram' and scene[1]=='cycle2':
        v6.SC[i]=('diagram','cycle2',"V9 Cycle Two expands that machine-learning search to fifty-four deterministic candidate model configurations, exploring broader portfolio sizes, longer holds and risk-controlled exposure while preserving the same confirmation standard.")
    elif scene[0]=='diagram' and scene[1]=='v10':
        v6.SC[i]=('diagram','v10',"V10 is the next regime-conditioned machine-learning challenger. This AI model generation moves through discovery, robustness testing, fixed-contract simulation and a pre-freeze gate before prospective confirmation against frozen V8.")
    elif scene[0]=='fail':
        v6.SC[i]=('fail',None,"The V9 machine-learning development winner was selected using the walk-forward research process, and then locked. Confirmation asked a different question: does that fixed AI model remain acceptable across calendar years, market regimes and transaction-cost stress? One or more of the predeclared confirmation gates were not satisfied. So V9 was not confirmed. The challenger model was rejected, there was no runner-up substitution, and V8 remained the frozen production machine-learning reference model.")


def main():
    old=v6.OUT/'data_shepherd_showcase_v10_16x9.mp4'
    new=v6.OUT/'data_shepherd_showcase_v11_16x9.mp4'
    v10.main()
    if old.exists(): shutil.move(str(old),str(new))
    print(f"\nV11 DONE: {new}\nopen \"{new}\"")

if __name__=='__main__': main()
