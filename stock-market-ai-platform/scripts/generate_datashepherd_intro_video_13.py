#!/usr/bin/env python3
"""Data Shepherd Engineering IntroVideo13.

Marketing-video revisions use the IntroVideo namespace so they cannot be
confused with stock/crypto model generations such as V8 and V10.
"""
from __future__ import annotations

import importlib.util
import math
import shutil
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "ds_intro_video_12", HERE / "generate_datashepherd_video_v12.py"
)
intro12 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(intro12)
v6 = intro12.v6


def center_text(d, xy, text, font, fill):
    box = d.textbbox((0, 0), text, font=font)
    d.text((xy[0] - (box[2] - box[0]) / 2, xy[1]), text, font=font, fill=fill)


def cinematic_open(t):
    """Platform-first opening with no generic AI orb or icon-card pipeline."""
    source = v6.load(v6.ASSETS["overview"])
    im = v6.cover(source, (v6.W, v6.H), 1.03 + .035 * v6.ease(t), .50, .45)
    overlay = v6.Image.new("RGBA", (v6.W, v6.H), (2, 10, 21, 0))
    od = v6.ImageDraw.Draw(overlay)
    od.rectangle((0, 0, v6.W, v6.H), fill=(2, 9, 20, 145))
    for x in range(0, 1280):
        alpha = int(205 * (1 - x / 1280))
        od.line((x, 0, x, v6.H), fill=(2, 9, 20, alpha))
    im = v6.Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
    d = v6.ImageDraw.Draw(im)
    v6.logo(im, 72, 44, 360, 140)
    d.text((105, 280), "DATA SHEPHERD", font=v6.font(68, True), fill=v6.TEXT)
    d.text((108, 362), "ENGINEERING", font=v6.font(68, True), fill=v6.GREEN)
    d.text((110, 470), "GOVERNED DATA  •  TESTABLE ML  •  VISIBLE EVIDENCE", font=v6.font(22, True), fill=v6.CYAN)
    d.multiline_text(
        (110, 540),
        "A production-minded research platform for stocks, crypto,\nmodel governance and forward paper monitoring.",
        font=v6.font(28), fill=v6.TEXT, spacing=14,
    )
    d.rounded_rectangle((108, 740, 905, 820), 18, fill=(4, 17, 31), outline=v6.CYAN, width=2)
    d.text((145, 764), "RESEARCH & SIMULATION ONLY  •  BROKERAGE ORDERS OFF", font=v6.font(20, True), fill=v6.GOLD)

    portrait_path = v6.fp()
    if portrait_path:
        d.rounded_rectangle((1550, 55, 1840, 345), 24, fill=(6, 20, 35), outline=v6.CYAN, width=3)
        portrait = v6.cover(v6.load(portrait_path), (254, 254), 1.04, .5, .22)
        mask = v6.Image.new("L", portrait.size, 0)
        v6.ImageDraw.Draw(mask).rounded_rectangle((0, 0, 253, 253), 18, fill=255)
        im.paste(portrait, (1568, 73), mask)
        d.text((1560, 366), "MERAJ ASARI  •  FOUNDER", font=v6.font(17, True), fill=v6.TEXT)
    return im


def track_card(d, box, title, status, colour, icon_kind):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, 28, fill=(8, 24, 42), outline=colour, width=4)
    cx, cy = (x0 + x1) // 2, y0 + 125
    intro12.draw_tech_icon(d, icon_kind, cx, cy, 82, colour)
    center_text(d, (cx, y0 + 205), title, v6.font(27, True), v6.TEXT)
    center_text(d, (cx, y0 + 258), status, v6.font(17, True), colour)


def platform_tracks(t):
    im = v6.bg(); v6.head(im, "ONE PLATFORM. THREE GOVERNED TRACKS.", "Shared engineering discipline, separate frozen research contracts")
    d = v6.ImageDraw.Draw(im)
    cards = [
        ((110, 290, 610, 800), "STOCKS", "V8 ACTIVE REFERENCE", v6.GREEN, "chart"),
        ((710, 290, 1210, 800), "CRYPTO 15M V2", "BTC / ALT / CASH • SHADOW", v6.CYAN, "regime"),
        ((1310, 290, 1810, 800), "XRP V1", "SEPARATE RIDGE TRACK • SHADOW", (190, 116, 255), "network"),
    ]
    for i, (box, title, status, colour, icon) in enumerate(cards):
        track_card(d, box, title, status, colour if i <= int(t * 3) else v6.BORDER, icon)
        x0, y0, x1, y1 = box
        details = [
            ["100-stock cross-sectional ranking", "Frozen model and feature contract", "Forward boundary: Sep 1, 2026"],
            ["44-feature HGB classifier", "Hourly confirm-2 execution policy", "Forward boundary: Sep 1, 2026"],
            ["XRP / BTC / CASH hysteresis", "Four-hour cadence; 24-hour hold", "No performance journal yet"],
        ][i]
        for j, line in enumerate(details):
            d.ellipse((x0 + 45, y0 + 322 + j * 55, x0 + 57, y0 + 334 + j * 55), fill=colour)
            d.text((x0 + 77, y0 + 313 + j * 55), line, font=v6.font(18, True), fill=v6.TEXT)
    d.text((480, 900), "NO TRACK CAN RETUNE ITSELF FROM FUTURE EVIDENCE OR PLACE REAL ORDERS.", font=v6.font(25, True), fill=v6.GOLD)
    return im


def cycle3_selection(t):
    im = v6.bg(); v6.head(im, "V10 CYCLE 3 — PREREGISTERED BEFORE EVALUATION", "Three locked transition-efficiency candidates; one fixed selection rule")
    d = v6.ImageDraw.Draw(im)
    candidates = [
        ("FULL DEFENSIVE", "2-day negative confirmation", "100% defensive score"),
        ("BLEND 50", "2-day negative confirmation", "50% V8 + 50% defensive"),
        ("BLEND 25", "Immediate negative entry", "75% V8 + 25% defensive"),
    ]
    for i, (name, entry, score) in enumerate(candidates):
        x = 145 + i * 585; active = i <= int(t * 3)
        colour = v6.GREEN if i == 1 else v6.CYAN
        d.rounded_rectangle((x, 315, x + 500, 675), 28, fill=v6.PANEL, outline=colour if active else v6.BORDER, width=4)
        center_text(d, (x + 250, 355), name, v6.font(29, True), colour)
        intro12.draw_tech_icon(d, "network" if i == 1 else "regime", x + 250, 475, 78, colour, not active)
        center_text(d, (x + 250, 555), entry, v6.font(18, True), v6.TEXT)
        center_text(d, (x + 250, 602), score, v6.font(18, True), v6.MUTED)
    d.rounded_rectangle((325, 765, 1595, 930), 24, fill=(5, 27, 34), outline=v6.GREEN, width=3)
    d.text((390, 798), "SELECTION RULE", font=v6.font(20, True), fill=v6.CYAN)
    d.text((390, 842), "PASS ALL 13 GATES  →  LOWEST TRANSITION NOTIONAL  →  LEXICAL TIEBREAK", font=v6.font(24, True), fill=v6.TEXT)
    d.text((585, 945), "NO WEIGHTS, THRESHOLDS OR GATES CHANGED AFTER RESULTS.", font=v6.font(22, True), fill=v6.GOLD)
    return im


def cycle3_winner(t):
    im = v6.bg(); v6.head(im, "CYCLE 3 FREEZE AUDIT", "The selected challenger earned a fresh, separate future holdout")
    d = v6.ImageDraw.Draw(im)
    d.rounded_rectangle((130, 265, 1790, 885), 38, fill=(7, 23, 40), outline=v6.CYAN, width=4)
    d.text((205, 330), "c3_confirm2_blend50", font=v6.font(50, True), fill=v6.CYAN)
    d.text((207, 407), "FROZEN FRESH-HOLDOUT CANDIDATE", font=v6.font(22, True), fill=v6.GREEN)
    d.ellipse((250, 505, 560, 815), outline=v6.GREEN, width=8)
    center_text(d, (405, 565), "13 / 13", v6.font(68, True), v6.GREEN)
    center_text(d, (405, 665), "GATES PASSED", v6.font(19, True), v6.TEXT)
    items = [
        ("NEGATIVE REGIME", "Two completed negative decisions before entry"),
        ("NEGATIVE SCORE", "50% ranked V8 signal + 50% defensive signal"),
        ("POSITIVE RETURN", "Immediate return to exact V8 scoring"),
        ("FROZEN SHA", "2bf467eb…9388d38"),
    ]
    for i, (label, detail) in enumerate(items):
        y = 505 + i * 82
        d.text((690, y), label, font=v6.font(17, True), fill=v6.MUTED)
        d.text((965, y), detail, font=v6.font(20, True), fill=v6.TEXT)
    d.text((450, 932), "V8 UNCHANGED  •  PRODUCTION UNCHANGED  •  BROKERAGE ORDERS OFF", font=v6.font(24, True), fill=v6.GOLD)
    return im


def holdout13(t):
    im = v6.bg(); v6.head(im, "FRESH FORWARD HOLDOUT", "Cycle 3 waits for genuinely unseen evidence by design")
    d = v6.ImageDraw.Draw(im); y = 600; boundary = 1240
    d.line((180, y, 1740, y), fill=v6.BORDER, width=8)
    d.line((180, y, boundary, y), fill=v6.GREEN, width=11)
    d.line((boundary, 330, boundary, 855), fill=v6.RED, width=7)
    for x, label in ((315, "PREREGISTER"), (640, "EVALUATE"), (930, "FREEZE AUDIT")):
        d.ellipse((x - 10, y - 10, x + 10, y + 10), fill=v6.GREEN)
        center_text(d, (x, y - 70), label, v6.font(16, True), v6.MUTED)
    d.text((1080, 355), "JANUARY 4, 2027", font=v6.font(38, True), fill=v6.RED)
    intro12.draw_tech_icon(d, "lock", 1485, 520, 120, v6.RED)
    center_text(d, (1485, 680), "FUTURE OUTCOMES", v6.font(21, True), v6.TEXT)
    center_text(d, (1485, 720), "UNREAD • UNSCORED", v6.font(21, True), v6.RED)
    d.text((205, 740), "DEVELOPMENT + IMMUTABLE FREEZE", font=v6.font(25, True), fill=v6.GREEN)
    d.text((410, 930), "NO PEEKING. NO BACKFILLING. ONLY COMPLETED POST-BOUNDARY COHORTS COUNT.", font=v6.font(25, True), fill=v6.TEXT)
    return im


def monitoring13(t):
    im = v6.bg(); v6.head(im, "READ-ONLY OPERATIONS", "Monitoring observes the frozen contract; dashboard requests never run research")
    d = v6.ImageDraw.Draw(im)
    rows = [
        ("STATUS.JSON", "Small current-state snapshot", v6.CYAN, "validated"),
        ("JOURNAL.JSONL", "Append-only decisions, entries and exits", v6.GREEN, "features"),
        ("HEALTH MONITOR", "Five-minute scheduler and alert state", v6.GOLD, "monitor"),
        ("DASHBOARD API", "Ten-second cache; read-only metrics", (190, 116, 255), "publish"),
    ]
    for i, (label, detail, colour, icon) in enumerate(rows):
        x = 140 + i * 440; active = i <= int(t * 4)
        d.rounded_rectangle((x, 350, x + 360, 745), 28, fill=v6.PANEL, outline=colour if active else v6.BORDER, width=4)
        intro12.draw_tech_icon(d, icon, x + 180, 470, 72, colour, not active)
        center_text(d, (x + 180, 555), label, v6.font(21, True), colour)
        center_text(d, (x + 180, 610), detail, v6.font(15, True), v6.TEXT)
    d.rounded_rectangle((300, 820, 1620, 925), 22, fill=(28, 9, 18), outline=v6.RED, width=3)
    center_text(d, (960, 848), "NEVER READ PARQUET OR INVOKE A RUNNER DURING A WEB REQUEST", v6.font(23, True), v6.RED)
    return im


def close13(t):
    source = v6.load(v6.ASSETS["engineering"])
    im = v6.cover(source, (v6.W, v6.H), 1.02 + .025 * v6.ease(t), .5, .45)
    shade = v6.Image.new("RGBA", (v6.W, v6.H), (2, 9, 20, 175))
    im = v6.Image.alpha_composite(im.convert("RGBA"), shade).convert("RGB")
    d = v6.ImageDraw.Draw(im); v6.logo(im, 690, 90, 540, 205)
    center_text(d, (960, 390), "DATA SHEPHERD ENGINEERING", v6.font(58, True), v6.TEXT)
    center_text(d, (960, 485), "EVIDENCE OVER PROMISES.", v6.font(36, True), v6.CYAN)
    center_text(d, (960, 545), "REPRODUCIBILITY OVER HINDSIGHT.", v6.font(36, True), v6.GREEN)
    d.rounded_rectangle((470, 685, 1450, 785), 20, fill=(4, 17, 31), outline=v6.CYAN, width=2)
    center_text(d, (960, 715), "STOCKS  •  CRYPTO  •  DATA ENGINEERING  •  MACHINE LEARNING", v6.font(21, True), v6.TEXT)
    center_text(d, (960, 900), "datashepherdengineering.com", v6.font(25, True), v6.GOLD)
    return im


base_frame = v6.frame


def frame13(scene, t):
    kind = scene[0]
    if kind == "intro13": return cinematic_open(t)
    if kind == "tracks13": return platform_tracks(t)
    if kind == "cycle3_selection13": return cycle3_selection(t)
    if kind == "cycle3_winner13": return cycle3_winner(t)
    if kind == "holdout13": return holdout13(t)
    if kind == "monitoring13": return monitoring13(t)
    if kind == "close13": return close13(t)
    return base_frame(scene, t)


v6.frame = frame13
v6.SC[:] = [
    ("intro13", None, "Data Shepherd Engineering is a production-minded research platform built by Meraj Asari. It connects governed market data, distributed processing, transparent machine learning and forward paper monitoring in one observable system. Every result must earn its way through a fixed contract, and the platform places no brokerage orders."),
    ("site", ("overview", "THE REAL PLATFORM", "Live product and engineering surfaces—not a notebook demonstration"), "The platform makes the complete system visible: stock and crypto research, model rankings, market context, operational health, protected holdouts and the evidence behind every frozen candidate."),
    ("site", ("engineering", "END-TO-END ENGINEERING", "Ingestion, medallion layers, features, models and prediction"), "Market observations move from ingestion through immutable Bronze storage, cleansed Silver data, curated Gold datasets and model-ready features. Python, PySpark, Pandas and Parquet support the path, while validation stops downstream work when the contract is incomplete."),
    ("tracks13", None, "Data Shepherd now contains three governed research tracks. Stocks use V8 as the frozen active reference. Shared Crypto Fifteen-Minute V2 evaluates BTC, ALT and CASH in shadow mode. XRP remains a separate Ridge-based exploratory track because its history and policy require independent treatment. All three keep real brokerage execution disabled."),
    ("cycle3_selection13", None, "V10 Cycle Three began with exactly three preregistered candidates. Their negative-regime entry timing and defensive blend were declared before evaluation. The selection rule was also fixed in advance: a candidate had to pass all thirteen gates, then win on the lowest transition notional, with a lexical tie-break only if necessary."),
    ("cycle3_winner13", None, "The selected challenger is c three confirm two blend fifty. It waits for two completed negative decisions, then combines fifty percent ranked V8 signal with fifty percent defensive signal. On the first non-negative decision it returns immediately to exact V8 scoring. The candidate passed all thirteen gates and was independently frozen under an immutable SHA. V8 and production remain unchanged."),
    ("holdout13", None, "Cycle Three now waits for a fresh forward holdout beginning January fourth, twenty twenty-seven. Original V10 holdout outcomes were not used, and the new future outcomes remain unread and unscored. The journal is append-only, missed decisions are never backfilled, and only genuinely completed post-boundary cohorts may enter performance evidence."),
    ("monitoring13", None, "Operations are intentionally lightweight and read-only. The dashboard reads small status and journal files, caches the response, and displays decisions, entries, completed cohorts, returns, SPY comparison and health alerts. A web request never reads Parquet and never invokes a research or holdout runner."),
    ("site", ("dashboard", "ENGINEERING MADE OBSERVABLE", "Research state, model evidence and safeguards in the product"), "The result is more than a prediction. It is an inspectable engineering system with frozen contracts, verification hashes, service health, separate evidence boundaries and explicit no-order safeguards."),
    ("close13", None, "Data Shepherd Engineering is built around a simple standard: evidence over promises, and reproducibility over hindsight. Governed data, testable machine learning, and visible safeguards—engineered for the markets, and built for the future."),
]


def main():
    old = v6.OUT / "data_shepherd_showcase_v12_16x9.mp4"
    new = v6.OUT / "data_shepherd_intro_video_13_16x9.mp4"
    intro12.main()
    if old.exists(): shutil.move(str(old), str(new))
    print(f'\nINTROVIDEO13 DONE: {new}\nopen "{new}"')


if __name__ == "__main__":
    main()
