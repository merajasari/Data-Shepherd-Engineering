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
    d.rounded_rectangle((108, 740, 975, 820), 18, fill=(4, 17, 31), outline=v6.CYAN, width=2)
    d.text((145, 764), "DEVELOPMENT & PROOF OF CONCEPT  →  AUTONOMOUS TRADING VISION", font=v6.font(19, True), fill=v6.GOLD)

    portrait_path = v6.fp()
    if portrait_path:
        d.rounded_rectangle((1550, 55, 1840, 345), 24, fill=(6, 20, 35), outline=v6.CYAN, width=3)
        portrait = v6.cover(v6.load(portrait_path), (254, 254), 1.04, .5, .22)
        mask = v6.Image.new("L", portrait.size, 0)
        v6.ImageDraw.Draw(mask).rounded_rectangle((0, 0, 253, 253), 18, fill=255)
        im.paste(portrait, (1568, 73), mask)
        d.text((1560, 366), "MERAJ ASARI  •  FOUNDER", font=v6.font(17, True), fill=v6.TEXT)
    return im


def track_card(im, d, box, title, status, colour, icon_kind, artwork=None):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, 28, fill=(8, 24, 42), outline=colour, width=4)
    cx, cy = (x0 + x1) // 2, y0 + 125
    if not artwork or not intro12.paste_reference_icon(im, artwork, cx, cy, 138):
        intro12.draw_tech_icon(d, icon_kind, cx, cy, 96, colour)
    center_text(d, (cx, y0 + 205), title, v6.font(27, True), v6.TEXT)
    center_text(d, (cx, y0 + 258), status, v6.font(17, True), colour)


def platform_tracks(t):
    im = v6.bg(); v6.head(im, "ONE PLATFORM. THREE GOVERNED TRACKS.", "Shared engineering discipline, separate frozen research contracts")
    d = v6.ImageDraw.Draw(im)
    cards = [
        ((110, 290, 610, 800), "STOCKS", "V8 ACTIVE REFERENCE", v6.GREEN, "chart", "prediction"),
        ((710, 290, 1210, 800), "CRYPTO 15M V2", "BTC / ALT / CASH • SHADOW", v6.CYAN, "regime", None),
        ((1310, 290, 1810, 800), "XRP V1", "SEPARATE RIDGE TRACK • SHADOW", (190, 116, 255), "network", "ai_brain"),
    ]
    for i, (box, title, status, colour, icon, artwork) in enumerate(cards):
        track_card(im, d, box, title, status, colour if i <= int(t * 3) else v6.BORDER, icon, artwork)
        x0, y0, x1, y1 = box
        if i == 1:
            # Purpose-built BTC / ALT / CASH orbit rather than a generic symbol.
            cx, cy = (x0 + x1) // 2, y0 + 125
            d.ellipse((cx - 92, cy - 92, cx + 92, cy + 92), outline=(28, 102, 130), width=3)
            for n, (label, angle, col) in enumerate((("B", -1.57, v6.GOLD), ("A", .52, v6.CYAN), ("$", 2.62, v6.GREEN))):
                px, py = cx + int(92 * math.cos(angle)), cy + int(92 * math.sin(angle))
                d.ellipse((px - 30, py - 30, px + 30, py + 30), fill=(6, 22, 38), outline=col, width=4)
                center_text(d, (px, py - 17), label, v6.font(27, True), col)
        details = [
            ["100-stock cross-sectional ranking", "Frozen model and feature contract", "Forward boundary: Sep 1, 2026"],
            ["44-feature HGB classifier", "Hourly confirm-2 execution policy", "Forward boundary: Sep 1, 2026"],
            ["XRP / BTC / CASH hysteresis", "Four-hour cadence; 24-hour hold", "No performance journal yet"],
        ][i]
        for j, line in enumerate(details):
            d.ellipse((x0 + 45, y0 + 322 + j * 55, x0 + 57, y0 + 334 + j * 55), fill=colour)
            d.text((x0 + 77, y0 + 313 + j * 55), line, font=v6.font(18, True), fill=v6.TEXT)
    d.text((405, 900), "SEPARATE CONTRACTS. SHARED GOVERNANCE. ONE AUTONOMOUS-TRADING VISION.", font=v6.font(25, True), fill=v6.GOLD)
    return im


def cycle3_selection(t):
    im = v6.bg(); v6.head(im, "V10 CYCLE 3 — PREREGISTERED BEFORE EVALUATION", "Three locked transition-efficiency candidates; one fixed selection rule")
    d = v6.ImageDraw.Draw(im)
    # Two locked signal sources fan into three preregistered blends.
    source_x = 240
    for y, label, art, colour in ((410, "V8 SIGNAL", "feature_table", v6.GREEN), (680, "DEFENSIVE SIGNAL", "ai_brain", (190, 116, 255))):
        d.rounded_rectangle((95, y - 100, 385, y + 100), 26, fill=v6.PANEL, outline=colour, width=4)
        intro12.paste_reference_icon(im, art, source_x, y - 20, 105)
        center_text(d, (source_x, y + 56), label, v6.font(18, True), colour)
    candidates = [
        ("FULL DEFENSIVE", "0% V8  +  100% DEF", v6.CYAN),
        ("BLEND 50", "50% V8  +  50% DEF", v6.GREEN),
        ("BLEND 25", "75% V8  +  25% DEF", v6.CYAN),
    ]
    for i, (name, formula, colour) in enumerate(candidates):
        y = 350 + i * 210; active = i <= int(t * 3)
        d.line((390, 410, 615, y), fill=(24, 87, 110), width=3)
        d.line((390, 680, 615, y), fill=(55, 64, 104), width=3)
        d.rounded_rectangle((615, y - 72, 1110, y + 72), 24, fill=(7, 24, 42), outline=colour if active else v6.BORDER, width=4)
        d.text((660, y - 40), name, font=v6.font(24, True), fill=colour)
        d.text((660, y + 5), formula, font=v6.font(19, True), fill=v6.TEXT)
        if active:
            for p in range(5):
                px = 780 + p * 48
                d.ellipse((px - 5, y + 48, px + 5, y + 58), fill=colour)
    # Fixed gate engine receives all candidates.
    d.rounded_rectangle((1270, 330, 1785, 805), 34, fill=(5, 28, 35), outline=v6.GREEN, width=5)
    intro12.draw_tech_icon(d, "gate", 1528, 470, 126, v6.GREEN)
    center_text(d, (1528, 570), "13 FIXED GATES", v6.font(32, True), v6.GREEN)
    center_text(d, (1528, 630), "Lowest transition notional", v6.font(19, True), v6.TEXT)
    center_text(d, (1528, 673), "Lexical tie-break", v6.font(19, True), v6.MUTED)
    for y in (350, 560, 770): d.line((1115, y, 1265, 520), fill=v6.GREEN, width=3)
    d.text((535, 925), "CANDIDATES, WEIGHTS AND GATES WERE LOCKED BEFORE RESULTS.", font=v6.font(24, True), fill=v6.GOLD)
    return im


def cycle3_winner(t):
    im = v6.bg(); v6.head(im, "CYCLE 3 FREEZE AUDIT", "The selected challenger earned a fresh, separate future holdout")
    d = v6.ImageDraw.Draw(im)
    d.rounded_rectangle((105, 245, 1815, 905), 38, fill=(7, 23, 40), outline=v6.CYAN, width=4)
    d.text((175, 300), "c3_confirm2_blend50", font=v6.font(48, True), fill=v6.CYAN)
    d.text((177, 370), "FROZEN FRESH-HOLDOUT CANDIDATE", font=v6.font(21, True), fill=v6.GREEN)
    # Selected ML artifact and gate result dominate the composition.
    intro12.paste_reference_icon(im, "ai_brain", 355, 590, 230)
    d.ellipse((205, 440, 505, 740), outline=(190, 116, 255), width=5)
    d.ellipse((520, 430, 820, 730), outline=v6.GREEN, width=8)
    center_text(d, (670, 505), "13 / 13", v6.font(64, True), v6.GREEN)
    center_text(d, (670, 605), "GATES PASSED", v6.font(19, True), v6.TEXT)
    d.line((505, 590, 520, 590), fill=v6.GREEN, width=7)
    items = [
        ("NEGATIVE REGIME", "Two completed negative decisions before entry"),
        ("NEGATIVE SCORE", "50% ranked V8 signal + 50% defensive signal"),
        ("POSITIVE RETURN", "Immediate return to exact V8 scoring"),
        ("FROZEN SHA", "2bf467eb…9388d38"),
    ]
    for i, (label, detail) in enumerate(items):
        y = 455 + i * 88
        d.text((900, y), label, font=v6.font(17, True), fill=v6.MUTED)
        d.text((1165, y), detail, font=v6.font(19, True), fill=v6.TEXT)
    d.rounded_rectangle((265, 790, 1655, 865), 18, fill=(5, 28, 35), outline=v6.GREEN, width=2)
    center_text(d, (960, 814), "IMMUTABLE CONTRACT  →  FRESH EVIDENCE  →  EARNED DEPLOYMENT", v6.font(23, True), v6.GOLD)
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
    # A realistic monitoring surface replaces the four generic icon cards.
    d.rounded_rectangle((110, 270, 1810, 900), 28, fill=(6, 19, 34), outline=v6.CYAN, width=3)
    d.rounded_rectangle((110, 270, 1810, 325), 18, fill=(8, 27, 46))
    for n, col in enumerate(((255,95,86),(255,189,46),(39,201,63))):
        x=145+n*30; d.ellipse((x-7,291,x+7,305),fill=col)
    d.text((245, 286), "V10 CYCLE 3  •  FRESH FORWARD HOLDOUT MONITOR", font=v6.font(17, True), fill=v6.TEXT)
    metrics=[("STATE","WAITING FOR HOLDOUT",v6.CYAN),("EVIDENCE","NO COMPLETED COHORTS",v6.MUTED),("SCHEDULER","5 MINUTES",v6.GREEN),("HEALTH","READY",v6.GREEN)]
    for i,(label,value,col) in enumerate(metrics):
        x=155+i*405
        d.rounded_rectangle((x,365,x+360,485),18,fill=(8,26,44),outline=v6.BORDER,width=2)
        d.text((x+22,385),label,font=v6.font(13,True),fill=v6.MUTED)
        d.text((x+22,425),value,font=v6.font(19,True),fill=col)
    # Animated diagnostic curve area.
    d.rounded_rectangle((155,525,1250,825),20,fill=(4,16,29),outline=v6.BORDER,width=2)
    d.text((185,548),"FORWARD EQUITY VS SPY",font=v6.font(15,True),fill=v6.MUTED)
    for yy in range(610,800,55): d.line((185,yy,1220,yy),fill=(12,35,54),width=1)
    values=[.52,.49,.54,.51,.59,.57,.65,.62,.70,.76,.73,.82]
    spy=[.50,.51,.52,.54,.55,.56,.58,.59,.60,.62,.64,.65]
    upto=max(2,min(len(values),int(2+t*len(values))))
    pts=[]; spypts=[]
    for i in range(upto):
        x=205+i*88; pts.append((x,int(790-values[i]*230))); spypts.append((x,int(790-spy[i]*230)))
    d.line(pts,fill=v6.CYAN,width=5); d.line(spypts,fill=v6.GOLD,width=3)
    side=[("STATUS.JSON","current state"),("JOURNAL.JSONL","append-only evidence"),("ALERT STATE","operational health"),("API CACHE","10 seconds")]
    for i,(label,detail) in enumerate(side):
        y=535+i*72
        d.rounded_rectangle((1310,y,1765,y+55),13,fill=(8,26,44),outline=v6.BORDER,width=2)
        d.text((1330,y+10),label,font=v6.font(14,True),fill=v6.GREEN)
        d.text((1510,y+10),detail,font=v6.font(14),fill=v6.TEXT)
    d.text((410, 940), "LIGHTWEIGHT OBSERVABILITY • IMMUTABLE RESEARCH • DEPLOYMENT READINESS", font=v6.font(22, True), fill=v6.GOLD)
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
    center_text(d, (960, 865), "VISION: AUTONOMOUS, EVIDENCE-DRIVEN TRADING", v6.font(27, True), v6.GOLD)
    center_text(d, (960, 915), "PURSUE STRONG RETURNS  •  CONTROL RISK  •  COMPOUND OVER TIME", v6.font(20, True), v6.TEXT)
    center_text(d, (960, 980), "datashepherdengineering.com", v6.font(22, True), v6.CYAN)
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
    ("intro13", None, "Data Shepherd Engineering is a production-minded research platform built by Meraj Asari. It connects governed market data, distributed processing, transparent machine learning and forward monitoring in one observable system. Today it is in development and proof-of-concept stages. The long-term vision is a secure autonomous trading system that works alongside Meraj, pursues substantial returns and earns real deployment through evidence and disciplined risk controls."),
    ("site", ("overview", "THE REAL PLATFORM", "Live product and engineering surfaces—not a notebook demonstration"), "The platform makes the complete system visible: stock and crypto research, model rankings, market context, operational health, protected holdouts and the evidence behind every frozen candidate."),
    ("site", ("engineering", "END-TO-END ENGINEERING", "Ingestion, medallion layers, features, models and prediction"), "Market observations move from ingestion through immutable Bronze storage, cleansed Silver data, curated Gold datasets and model-ready features. Python, PySpark, Pandas and Parquet support the path, while validation stops downstream work when the contract is incomplete."),
    ("tracks13", None, "Data Shepherd now contains three governed research tracks. Stocks use V8 as the frozen active reference. Shared Crypto Fifteen-Minute V2 evaluates BTC, ALT and CASH in shadow mode. XRP remains a separate Ridge-based exploratory track because its history and policy require independent treatment. Each track develops independently while contributing to one long-term autonomous-trading vision."),
    ("cycle3_selection13", None, "V10 Cycle Three began with exactly three preregistered candidates. Their negative-regime entry timing and defensive blend were declared before evaluation. The selection rule was also fixed in advance: a candidate had to pass all thirteen gates, then win on the lowest transition notional, with a lexical tie-break only if necessary."),
    ("cycle3_winner13", None, "The selected challenger is c three confirm two blend fifty. It waits for two completed negative decisions, then combines fifty percent ranked V8 signal with fifty percent defensive signal. On the first non-negative decision it returns immediately to exact V8 scoring. The candidate passed all thirteen gates and was independently frozen under an immutable SHA, creating a disciplined path from research toward earned deployment."),
    ("holdout13", None, "Cycle Three now waits for a fresh forward holdout beginning January fourth, twenty twenty-seven. Original V10 holdout outcomes were not used, and the new future outcomes remain unread and unscored. The journal is append-only, missed decisions are never backfilled, and only genuinely completed post-boundary cohorts may enter performance evidence."),
    ("monitoring13", None, "Operations are intentionally lightweight and read-only. The dashboard reads small status and journal files, caches the response, and displays decisions, entries, completed cohorts, returns, SPY comparison and health alerts. A web request never reads Parquet and never invokes a research or holdout runner."),
    ("site", ("dashboard", "ENGINEERING MADE OBSERVABLE", "Research state, model evidence and safeguards in the product"), "The result is more than a prediction. It is an inspectable engineering system with frozen contracts, verification hashes, service health, separate evidence boundaries and explicit no-order safeguards."),
    ("close13", None, "Data Shepherd Engineering is built around a simple standard: evidence over promises, and reproducibility over hindsight. The goal is to turn governed data and testable machine learning into a secure autonomous system that can trade alongside Meraj, pursue strong returns, manage risk and compound wealth over time. Engineered for the markets, and built for the future."),
]


def main():
    old = v6.OUT / "data_shepherd_showcase_v12_16x9.mp4"
    new = v6.OUT / "data_shepherd_intro_video_13_16x9.mp4"
    intro12.main()
    if old.exists(): shutil.move(str(old), str(new))
    print(f'\nINTROVIDEO13 DONE: {new}\nopen "{new}"')


if __name__ == "__main__":
    main()
