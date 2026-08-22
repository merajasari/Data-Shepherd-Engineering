#!/usr/bin/env python3
"""Data Shepherd Engineering showcase V9.

Audio polish pass over V8:
- slows narration slightly (default 205 wpm)
- prefers a British female voice, Serena first
- reshapes punctuation for more natural phrasing and breathing room
- adds warm broadcast EQ, compression, and gentle loudness mastering
- preserves all V8/V7 visual improvements
"""
from __future__ import annotations
import importlib.util, os, re, shutil, subprocess
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
    # Serena is the target: British, calm, polished and less announcer-like.
    for name in ("Serena", "Kate", "Martha", "Stephanie"):
        if re.search(rf"(?m)^{re.escape(name)}\s+", listing):
            return name
    for line in listing.splitlines():
        if "en_GB" in line:
            name = line.split()[0]
            if name not in {"Daniel", "Oliver", "Arthur", "Eddy", "Reed", "Rocko"}:
                return name
    return "Samantha"


def humanise_script(text: str) -> str:
    """Make Apple's TTS breathe more like spoken narration without changing meaning."""
    text = text.replace(" — ", ".  ")
    text = text.replace("; ", ".  ")
    text = re.sub(r"\.\s+", ".  ", text)
    text = re.sub(r",\s+(and|but|while|because|so)\s+", r",  \1 ", text, flags=re.I)
    # Give high-value beats a little room without using engine-specific speech markup.
    for phrase in (
        "Data Shepherd Engineering",
        "one hundred and one out of one hundred and one",
        "Data Shepherd rejected it",
        "No runner-up substitution",
        "No lower bar",
        "Frozen V8",
        "the second of November, twenty twenty-six",
        "Evidence over promises",
        "Reproducibility over hindsight",
    ):
        text = text.replace(phrase, phrase + ",")
    return text


def warm_british_voice(text, path):
    voice_name = choose_voice()
    # Slower than V8's 228 wpm. Override with DS_RATE if desired.
    rate = os.environ.get("DS_RATE", "205")
    raw = Path(str(path) + ".raw.aiff")
    spoken = humanise_script(text)
    subprocess.check_call(["say", "-v", voice_name, "-r", rate, "-o", str(raw), spoken])

    # Warmer, smoother broadcast mastering. The gentle 180 Hz lift and 3.2 kHz dip
    # reduce the thin/digital edge without making speech muddy.
    filters = (
        "highpass=f=65,"
        "lowpass=f=11800,"
        "equalizer=f=180:t=q:w=1.0:g=2.0,"
        "equalizer=f=3200:t=q:w=1.2:g=-1.6,"
        "equalizer=f=6200:t=q:w=1.1:g=-1.0,"
        "acompressor=threshold=-22dB:ratio=2.0:attack=22:release=180:makeup=1.5,"
        "loudnorm=I=-16:TP=-1.8:LRA=6"
    )
    try:
        subprocess.check_call([
            v6.ff(), "-y", "-i", str(raw), "-af", filters, str(path)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raw.unlink(missing_ok=True)
    except Exception:
        shutil.move(str(raw), str(path))
    print(f"Narration voice: {voice_name} (warm British female, {rate} wpm)")

# V6's rendering pipeline calls this directly.
v6.voice = warm_british_voice


def main():
    old = v6.OUT / "data_shepherd_showcase_v8_16x9.mp4"
    new = v6.OUT / "data_shepherd_showcase_v9_16x9.mp4"
    v8.main()
    if old.exists():
        shutil.move(str(old), str(new))
    print(f"\nV9 DONE: {new}\nopen \"{new}\"")


if __name__ == "__main__":
    main()
