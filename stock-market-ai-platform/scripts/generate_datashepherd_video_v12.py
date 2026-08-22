#!/usr/bin/env python3
"""Data Shepherd Engineering showcase V12.

Changes over V11:
- presents only V8 and V10 as model generations
- folds the retained V9 auto-tuning and Cycle 2 capabilities into V10
- removes the rejected-winner explanation scene
- removes the two lower-right dashboard panels so the architecture background remains visible
"""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("dsv11", HERE / "generate_datashepherd_video_v11.py")
v11 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v11)
v10 = v11.v10
v6 = v11.v6


# The dashboard source image contains two lower panels labelled
# "10. Boot & Environment" and "11. Logging & State".  Remove those panels
# before the normal animated crop is applied, revealing a clean architecture
# background instead of placing additional rectangles over the product view.
_site_base = v6.site


def cleaned_dashboard_site(path, t, title, subtitle):
    if path != v6.ASSETS["dashboard"]:
        return _site_base(path, t, title, subtitle)

    im = v6.bg()
    v6.head(im, title, subtitle)
    d = v6.ImageDraw.Draw(im)
    area = (70, 200, 1850, 1015)
    if path.exists():
        source = v6.load(path)
        sd = v6.ImageDraw.Draw(source)
        sw, sh = source.size
        # Coordinates are proportional so the cleanup remains correct if the
        # source asset is regenerated at a different resolution.
        x0, y0 = int(sw * 0.522), int(sh * 0.842)
        x1, y1 = int(sw * 0.997), int(sh * 0.997)
        sd.rectangle((x0, y0, x1, y1), fill=(6, 18, 29))
        # Preserve the subtle architecture-grid feel without recreating cards.
        for x in range(x0 + 34, x1, 88):
            sd.line((x, y0, x, y1), fill=(7, 25, 40), width=1)
        for y in range(y0 + 34, y1, 70):
            sd.line((x0, y, x1, y), fill=(7, 25, 40), width=1)
        im.paste(
            v6.cover(source, (1780, 815), 1 + 0.09 * v6.ease(t), 0.5 + 0.05 * v6.math.sin(t * v6.math.pi), 0.47),
            (70, 200),
        )
    d.rounded_rectangle(area, 26, outline=v6.CYAN, width=3)
    return im


v6.site = cleaned_dashboard_site


def two_generation_frame(t):
    im = v6.bg()
    v6.head(im, "THE MODEL GENERATIONS", "Two model systems: frozen V8 and the integrated V10 research challenger")
    d = v6.ImageDraw.Draw(im)
    cards = [
        (
            170, 310, 870, 845, "V8", "FROZEN PRODUCTION MODEL", "Production reference",
            ["100-stock ranking", "Portfolio signals", "Frozen model contract", "Website + scheduler integration"], v6.GREEN,
        ),
        (
            1050, 310, 1750, 845, "V10", "INTEGRATED ML RESEARCH", "Next-generation challenger",
            ["Bounded auto-tuning engine", "Cycle 2 expanded search", "Regime-conditioned ranking", "Independent confirmation + holdout"], v6.CYAN,
        ),
    ]
    active = min(1, int(t * 2))
    for i, (x0, y0, x1, y1, version, label, sub, bullets, colour) in enumerate(cards):
        outline = colour if i <= active else v6.BORDER
        d.rounded_rectangle((x0, y0, x1, y1), 32, fill=v6.PANEL, outline=outline, width=5)
        d.text((x0 + 46, y0 + 38), version, font=v6.font(82, True), fill=colour)
        d.text((x0 + 46, y0 + 150), label, font=v6.font(25, True), fill=v6.TEXT)
        d.text((x0 + 46, y0 + 202), sub, font=v6.font(20, True), fill=v6.MUTED)
        d.line((x0 + 46, y0 + 255, x1 - 46, y0 + 255), fill=v6.BORDER, width=2)
        for n, bullet in enumerate(bullets):
            yy = y0 + 305 + n * 58
            d.ellipse((x0 + 48, yy + 7, x0 + 64, yy + 23), fill=colour)
            d.text((x0 + 86, yy), bullet, font=v6.font(22, True), fill=v6.TEXT)
        d.rounded_rectangle((x0 + 46, y1 - 82, x1 - 46, y1 - 34), 14, fill=(6, 20, 34), outline=outline, width=2)
        d.text((x0 + 80, y1 - 69), "MACHINE LEARNING / AI", font=v6.font(18, True), fill=colour)
    d.text((470, 920), "V10 INHERITS EVERY RETAINED CHALLENGER CAPABILITY.", font=v6.font(28, True), fill=v6.GOLD)
    return im


def integrated_v10_frame(mode, t):
    im = v6.bg()
    d = v6.ImageDraw.Draw(im)
    if mode == "autotune":
        v6.head(im, "V10 AUTOMATIC-TUNING ENGINE", "Bounded search, chronological evidence and locked confirmation")
        d.ellipse((175, 395, 535, 755), outline=v6.CYAN, width=7)
        d.text((275, 485), "27", font=v6.font(116, True), fill=v6.CYAN)
        d.text((235, 625), "INITIAL CANDIDATES", font=v6.font(20, True), fill=v6.TEXT)
        steps = [("REGISTER", "declared first"), ("5 FOLDS", "chronological"), ("LOCK", "no retuning"), ("CONFIRM", "independent")]
        for i, (label, detail) in enumerate(steps):
            x = 660 + i * 295
            on = i <= int(t * 4)
            v6.node(d, x, 565, label, "✓" if i < 3 else "?", v6.GREEN if i < 3 else v6.GOLD, on)
            d.text((x - 62, 685), detail.upper(), font=v6.font(14, True), fill=v6.MUTED)
        d.text((565, 855), "DECLARE  →  EVALUATE  →  LOCK  →  CONFIRM", font=v6.font(30, True), fill=v6.GREEN)
    else:
        v6.head(im, "V10 CYCLE 2 + REGIME RESEARCH", "Expanded deterministic search under the same scientific constraints")
        d.ellipse((150, 395, 500, 745), outline=v6.CYAN, width=7)
        d.text((242, 485), "54", font=v6.font(116, True), fill=v6.CYAN)
        d.text((215, 625), "CANDIDATES", font=v6.font(22, True), fill=v6.TEXT)
        cards = [
            ("TOP N", "10 / 15 / 20"), ("HOLD", "10 / 20 sessions"),
            ("EXPOSURE", "trend controlled"), ("COST", "10 / 30 bps"),
            ("REGIMES", "conditioned ranking"), ("GATE", "frozen V8 comparison"),
        ]
        for i, (label, detail) in enumerate(cards):
            x = 620 + (i % 3) * 390
            y = 340 + (i // 3) * 245
            d.rounded_rectangle((x, y, x + 340, y + 185), 24, fill=v6.PANEL, outline=v6.GREEN if i <= int(t * 6) else v6.BORDER, width=4)
            d.text((x + 26, y + 28), label, font=v6.font(21, True), fill=v6.CYAN)
            d.text((x + 26, y + 88), detail, font=v6.font(25, True), fill=v6.TEXT)
        d.text((540, 895), "WIDER SEARCH. SAME RULES. HIGHER STANDARDS.", font=v6.font(29, True), fill=v6.GREEN)
    return im


_frame_base = v6.frame


def frame_v12(scene, t):
    if scene[0] == "model_lineage_v12":
        return two_generation_frame(t)
    if scene[0] == "v10_integrated":
        return integrated_v10_frame(scene[1], t)
    return _frame_base(scene, t)


v6.frame = frame_v12


# Replace the prior three-generation section with a V8/V10-only story.  The
# rejection explainer is removed even if an older imported generator restores it.
rebuilt = []
inserted = False
for scene in v6.SC:
    old_model_scene = scene[0] == "model_lineage" or (scene[0] == "diagram" and scene[1] in {"v9", "cycle2", "v10"})
    if old_model_scene:
        if not inserted:
            rebuilt.extend([
                (
                    "model_lineage_v12", None,
                    "V8 and V10 are the two machine-learning model systems shown here. V8 is the frozen production reference. V10 is the integrated research challenger, carrying forward every retained capability from the earlier research generation, including the automatic-tuning engine, the expanded Cycle Two search, regime-aware ranking, independent confirmation and formal holdout protection.",
                ),
                (
                    "v10_integrated", "autotune",
                    "V10 includes the bounded automatic-tuning engine. Candidate configurations are declared before evaluation, tested across five chronological folds, and the development winner is locked before independent confirmation. The process can search, but it cannot rewrite its rules after seeing the result.",
                ),
                (
                    "v10_integrated", "cycle2",
                    "V10 also includes the expanded Cycle Two research design: fifty-four deterministic candidate configurations across portfolio size, holding period, trend-controlled exposure and transaction-cost assumptions, together with regime-conditioned ranking and a fixed comparison against frozen V8.",
                ),
            ])
            inserted = True
        continue
    if scene[0] == "fail":
        continue
    rebuilt.append(scene)

v6.SC[:] = rebuilt


def main():
    old = v6.OUT / "data_shepherd_showcase_v11_16x9.mp4"
    new = v6.OUT / "data_shepherd_showcase_v12_16x9.mp4"
    v11.main()
    if old.exists():
        shutil.move(str(old), str(new))
    print(f"\nV12 DONE: {new}\nopen \"{new}\"")


if __name__ == "__main__":
    main()
