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


def prepare_overview_artwork(source, t):
    """Remove phone-build copy and turn the existing phone screen into a chart."""
    source = source.copy().convert("RGB")
    d = v6.ImageDraw.Draw(source)
    sw, sh = source.size

    # Replace the source artwork's phone-build sentence without introducing a
    # floating label or a new card over the platform image.
    d.rectangle(
        (0, int(sh * .449), int(sw * .285), int(sh * .493)),
        fill=(3, 13, 25),
    )
    d.text(
        (int(sw * .025), int(sh * .458)),
        "Governed engineering from market data to model evidence.",
        font=v6.font(max(11, int(sw * .0105)), True),
        fill=(165, 185, 207),
    )

    # The phone and bezel remain part of the original artwork. Only the inner
    # screen pixels are repainted, following its existing perspective.
    quad = [
        (int(sw * .258), int(sh * .593)),
        (int(sw * .313), int(sh * .602)),
        (int(sw * .297), int(sh * .791)),
        (int(sw * .244), int(sh * .784)),
    ]
    d.polygon(quad, fill=(3, 13, 23))

    def qpoint(u, v):
        tx = quad[0][0] + (quad[1][0] - quad[0][0]) * u
        ty = quad[0][1] + (quad[1][1] - quad[0][1]) * u
        bx = quad[3][0] + (quad[2][0] - quad[3][0]) * u
        by = quad[3][1] + (quad[2][1] - quad[3][1]) * u
        return int(tx + (bx - tx) * v), int(ty + (by - ty) * v)

    for v in (.24, .43, .62, .81):
        d.line((qpoint(.08, v), qpoint(.92, v)), fill=(18, 45, 62), width=max(1, sw // 1200))
    for u in (.18, .38, .58, .78):
        d.line((qpoint(u, .16), qpoint(u, .90)), fill=(12, 34, 50), width=max(1, sw // 1400))
    values = [.76, .69, .72, .58, .62, .47, .52, .36, .40, .25, .30, .16]
    points = [qpoint(.09 + i * .075, value) for i, value in enumerate(values)]
    d.line(points, fill=(20, 92, 111), width=max(4, sw // 310))
    d.line(points, fill=v6.GREEN, width=max(2, sw // 600))
    pulse = points[min(len(points) - 1, int(t * len(points)))]
    radius = max(3, sw // 420)
    d.ellipse((pulse[0] - radius, pulse[1] - radius, pulse[0] + radius, pulse[1] + radius), fill=v6.CYAN)
    for i, height in enumerate((.08, .13, .10, .18, .15, .22, .17, .27)):
        u0 = .10 + i * .105
        d.polygon(
            [qpoint(u0, .93 - height), qpoint(u0 + .05, .93 - height), qpoint(u0 + .05, .93), qpoint(u0, .93)],
            fill=(31, 119, 139),
        )
    return source


def cinematic_open(t):
    """Clean platform-first opening; copy never floats over the hero artwork."""
    im = v6.bg()
    d = v6.ImageDraw.Draw(im)
    # Quiet branded field on the left, real platform in its own browser surface.
    for x in range(0, v6.W, 96):
        d.line((x, 0, x, v6.H), fill=(5, 24, 39), width=1)
    for y in range(0, v6.H, 96):
        d.line((0, y, v6.W, y), fill=(5, 24, 39), width=1)
    v6.logo(im, 70, 44, 390, 148)
    d.text((92, 270), "DATA SHEPHERD", font=v6.font(60, True), fill=v6.TEXT)
    d.text((94, 344), "ENGINEERING", font=v6.font(60, True), fill=v6.GREEN)
    d.text((96, 450), "GOVERNED DATA", font=v6.font(22, True), fill=v6.CYAN)
    d.text((96, 494), "TESTABLE MACHINE LEARNING", font=v6.font(22, True), fill=(190, 116, 255))
    d.text((96, 538), "VISIBLE EVIDENCE", font=v6.font(22, True), fill=v6.GREEN)
    d.line((96, 600, 485, 600), fill=v6.CYAN, width=3)
    d.multiline_text(
        (96, 640),
        "Stocks, crypto, model governance\nand forward monitoring in one\nobservable engineering platform.",
        font=v6.font(25), fill=v6.MUTED, spacing=14,
    )

    source = prepare_overview_artwork(v6.load(v6.ASSETS["overview"]), t)
    panel = v6.cover(source, (1260, 715), 1.0 + .025 * v6.ease(t), .51, .47)
    d.rounded_rectangle((575, 245, 1860, 995), 30, fill=(5, 18, 31), outline=v6.CYAN, width=4)
    im.paste(panel, (588, 267))
    d.rounded_rectangle((588, 267, 1848, 315), 15, fill=(7, 20, 34))
    for n, colour in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        cx = 618 + n * 28
        d.ellipse((cx - 7, 284, cx + 7, 298), fill=colour)
    d.rounded_rectangle((720, 278, 1810, 305), 9, fill=(11, 31, 49))
    d.text((745, 279), "datashepherdengineering.com", font=v6.font(14, True), fill=v6.MUTED)

    portrait_path = v6.fp()
    if portrait_path:
        d.rounded_rectangle((1550, 45, 1845, 225), 22, fill=(6, 20, 35), outline=v6.CYAN, width=3)
        portrait = v6.cover(v6.load(portrait_path), (142, 142), 1.04, .5, .22)
        mask = v6.Image.new("L", portrait.size, 0)
        v6.ImageDraw.Draw(mask).rounded_rectangle((0, 0, 141, 141), 16, fill=255)
        im.paste(portrait, (1570, 64), mask)
        d.text((1730, 87), "MERAJ ASARI", font=v6.font(18, True), fill=v6.TEXT)
        d.text((1730, 128), "FOUNDER · CEO", font=v6.font(16, True), fill=v6.CYAN)
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
    im = v6.bg()
    d = v6.ImageDraw.Draw(im)
    # A large branded header replaces the inherited thumbnail-size logo.
    v6.logo(im, 48, 32, 330, 124)
    d.text((415, 48), "V10 CYCLE 3 — PREREGISTERED BEFORE EVALUATION", font=v6.font(38, True), fill=v6.TEXT)
    d.text((418, 112), "Three declared blends. Thirteen fixed gates. One selection rule.", font=v6.font(21), fill=v6.MUTED)
    d.line((415, 160, 1825, 160), fill=v6.BORDER, width=2)

    # Signal sources are rendered as dimensional research inputs.
    sources = [
        (250, 395, "V8 RANKED SIGNAL", "feature_table", v6.GREEN),
        (250, 690, "DEFENSIVE SIGNAL", "ai_brain", (190, 116, 255)),
    ]
    for cx, cy, label, art, colour in sources:
        d.ellipse((cx - 118, cy - 118, cx + 118, cy + 118), fill=(6, 23, 39), outline=colour, width=5)
        intro12.paste_reference_icon(im, art, cx, cy - 18, 125)
        center_text(d, (cx, cy + 78), label, v6.font(17, True), colour)

    candidates = [
        (365, "FULL DEFENSIVE", "0% V8  +  100% DEF", v6.CYAN),
        (565, "BLEND 50", "50% V8  +  50% DEF", v6.GREEN),
        (765, "BLEND 25", "75% V8  +  25% DEF", v6.CYAN),
    ]
    for i, (cy, name, formula, colour) in enumerate(candidates):
        active = i <= int(t * 3)
        d.line((370, 395, 565, cy), fill=(28, 105, 118), width=4)
        d.line((370, 690, 565, cy), fill=(85, 54, 125), width=4)
        d.rounded_rectangle((565, cy - 72, 1125, cy + 72), 25, fill=(7, 24, 42), outline=colour if active else v6.BORDER, width=5)
        intro12.draw_tech_icon(d, "network", 625, cy, 58, colour if active else v6.BORDER)
        d.text((690, cy - 39), name, font=v6.font(25, True), fill=colour if active else v6.MUTED)
        d.text((690, cy + 8), formula, font=v6.font(19, True), fill=v6.TEXT)

    d.rounded_rectangle((1275, 285, 1785, 845), 38, fill=(5, 27, 37), outline=v6.GREEN, width=6)
    intro12.draw_tech_icon(d, "gate", 1530, 430, 145, v6.GREEN)
    center_text(d, (1530, 545), "13 / 13", v6.font(56, True), v6.GREEN)
    center_text(d, (1530, 620), "FIXED GATES REQUIRED", v6.font(20, True), v6.TEXT)
    d.line((1340, 680, 1720, 680), fill=v6.BORDER, width=2)
    center_text(d, (1530, 715), "LOWEST TRANSITION NOTIONAL", v6.font(17, True), v6.CYAN)
    center_text(d, (1530, 758), "LEXICAL TIE-BREAK ONLY IF NEEDED", v6.font(15, True), v6.MUTED)
    for cy, _, _, _ in candidates:
        d.line((1135, cy, 1265, 565), fill=v6.GREEN, width=4)
    center_text(d, (960, 930), "CANDIDATES, WEIGHTS AND GATES WERE LOCKED BEFORE RESULTS.", v6.font(23, True), v6.GOLD)
    return im
def cycle3_winner(t):
    im = v6.bg(); v6.head(im, "V10 CYCLE 3 FREEZE AUDIT", "The selected challenger earned a fresh, separate future holdout")
    d = v6.ImageDraw.Draw(im)
    d.rounded_rectangle((105, 245, 1815, 905), 38, fill=(7, 23, 40), outline=v6.CYAN, width=4)
    d.text((175, 300), "c3_confirm2_blend50", font=v6.font(48, True), fill=v6.CYAN)
    d.text((177, 370), "FROZEN FRESH-HOLDOUT CANDIDATE", font=v6.font(21, True), fill=v6.GREEN)
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
    im = v6.bg(); v6.head(im, "FRESH FORWARD HOLDOUT", "A sealed evidence boundary protects genuinely unseen outcomes")
    d = v6.ImageDraw.Draw(im)
    # Large evidence vault and a two-zone timeline make the scientific boundary visible.
    d.rounded_rectangle((105, 255, 1815, 900), 34, fill=(6, 20, 35), outline=v6.BORDER, width=3)
    boundary = 1190
    d.rounded_rectangle((145, 300, 1135, 845), 28, fill=(5, 29, 35), outline=v6.GREEN, width=3)
    d.rounded_rectangle((1245, 300, 1775, 845), 28, fill=(28, 12, 28), outline=v6.RED, width=3)
    d.text((195, 340), "LOCKED RESEARCH HISTORY", font=v6.font(24, True), fill=v6.GREEN)
    d.text((1295, 340), "SEALED FUTURE EVIDENCE", font=v6.font(24, True), fill=v6.RED)

    stages = [
        (280, "PREREGISTER", "candidate + rule", "features"),
        (555, "EVALUATE", "13 fixed gates", "gate"),
        (830, "FREEZE AUDIT", "immutable SHA", "lock"),
    ]
    for i, (cx, label, detail, icon) in enumerate(stages):
        active = i <= int(t * 3)
        colour = v6.GREEN if active else v6.BORDER
        d.ellipse((cx - 75, 455, cx + 75, 605), fill=(7, 24, 40), outline=colour, width=5)
        intro12.draw_tech_icon(d, icon, cx, 530, 65, colour)
        center_text(d, (cx, 645), label, v6.font(18, True), colour)
        center_text(d, (cx, 685), detail.upper(), v6.font(14, True), v6.MUTED)
        if i < len(stages) - 1:
            d.line((cx + 82, 530, stages[i + 1][0] - 82, 530), fill=v6.GREEN, width=5)

    d.line((boundary, 275, boundary, 875), fill=v6.RED, width=7)
    d.polygon([(boundary - 12, 290), (boundary + 12, 290), (boundary, 315)], fill=v6.RED)
    center_text(d, (boundary, 215), "JANUARY 4, 2027", v6.font(30, True), v6.RED)
    intro12.draw_tech_icon(d, "lock", 1510, 525, 150, v6.RED)
    center_text(d, (1510, 645), "OUTCOMES REMAIN SEALED", v6.font(22, True), v6.TEXT)
    center_text(d, (1510, 690), "UNREAD  •  UNSCORED", v6.font(21, True), v6.RED)
    center_text(d, (1510, 755), "APPEND-ONLY JOURNAL", v6.font(16, True), v6.MUTED)
    center_text(d, (960, 940), "NO PEEKING  •  NO BACKFILLING  •  ONLY COMPLETED POST-BOUNDARY COHORTS COUNT", v6.font(22, True), v6.TEXT)
    return im
def monitoring13(t):
    im = v6.bg(); v6.head(im, "READ-ONLY OPERATIONS", "A production-style monitor for evidence, health and forward comparison")
    d = v6.ImageDraw.Draw(im)
    d.rounded_rectangle((90, 245, 1830, 925), 30, fill=(5, 18, 32), outline=v6.CYAN, width=3)
    d.rounded_rectangle((90, 245, 1830, 305), 18, fill=(8, 28, 47))
    for n, col in enumerate(((255,95,86),(255,189,46),(39,201,63))):
        x=128+n*30; d.ellipse((x-7,268,x+7,282),fill=col)
    d.text((230, 262), "V10 CYCLE 3  /  FORWARD EVIDENCE MONITOR", font=v6.font(18, True), fill=v6.TEXT)
    d.rounded_rectangle((1450, 257, 1785, 293), 10, fill=(5, 35, 34), outline=v6.GREEN, width=2)
    center_text(d, (1618, 265), "SYSTEM READY", v6.font(14, True), v6.GREEN)

    metrics=[("STATE","WAITING FOR HOLDOUT",v6.CYAN),("COHORTS","0 COMPLETED",v6.MUTED),("BOUNDARY","JAN 4, 2027",v6.RED),("HEALTH","READY",v6.GREEN)]
    for i,(label,value,col) in enumerate(metrics):
        x=135+i*420
        d.rounded_rectangle((x,335,x+385,445),17,fill=(8,27,46),outline=v6.BORDER,width=2)
        d.text((x+22,354),label,font=v6.font(13,True),fill=v6.MUTED)
        d.text((x+22,394),value,font=v6.font(20,True),fill=col)

    # Larger, more legible graph with axes, legend, glow and an honest empty state.
    gx0,gy0,gx1,gy1=145,490,1315,850
    d.rounded_rectangle((gx0,gy0,gx1,gy1),22,fill=(3,15,28),outline=(26,71,94),width=2)
    d.text((gx0+28,gy0+22),"FORWARD EQUITY VS SPY",font=v6.font(19,True),fill=v6.TEXT)
    d.text((gx0+28,gy0+58),"UI PREVIEW — HOLDOUT RESULTS NOT YET AVAILABLE",font=v6.font(13,True),fill=v6.RED)
    for j,label in enumerate(("1.10","1.05","1.00","0.95")):
        yy=gy0+115+j*64
        d.line((gx0+90,yy,gx1-30,yy),fill=(13,39,58),width=1)
        d.text((gx0+28,yy-10),label,font=v6.font(12),fill=v6.MUTED)
    for i,label in enumerate(("START","20","40","60","80","100")):
        xx=gx0+100+i*195
        d.line((xx,gy0+105,xx,gy1-38),fill=(10,31,48),width=1)
        center_text(d,(xx,gy1-28),label,v6.font(11),v6.MUTED)
    preview=[.58,.55,.60,.57,.66,.63,.72,.69,.77,.83,.80,.88]
    spy=[.56,.57,.59,.61,.62,.64,.66,.67,.69,.71,.73,.75]
    upto=max(2,min(len(preview),int(2+t*len(preview))))
    pts=[]; spypts=[]
    for i in range(upto):
        x=gx0+105+i*95
        pts.append((x,int(gy1-70-preview[i]*245)))
        spypts.append((x,int(gy1-70-spy[i]*245)))
    if len(pts)>1:
        glow=[(x,y+8) for x,y in pts]
        d.line(glow,fill=(6,45,58),width=12)
        d.line(pts,fill=v6.CYAN,width=6)
        d.line(spypts,fill=v6.GOLD,width=4)
        px,py=pts[-1]; d.ellipse((px-8,py-8,px+8,py+8),fill=v6.CYAN)
    d.line((gx1-340,gy0+34,gx1-285,gy0+34),fill=v6.CYAN,width=5)
    d.text((gx1-275,gy0+22),"CANDIDATE",font=v6.font(13,True),fill=v6.TEXT)
    d.line((gx1-170,gy0+34,gx1-115,gy0+34),fill=v6.GOLD,width=4)
    d.text((gx1-105,gy0+22),"SPY",font=v6.font(13,True),fill=v6.TEXT)

    side=[("STATUS.JSON","current state",v6.CYAN),("JOURNAL.JSONL","append-only evidence",v6.GREEN),("ALERT STATE","operational health",v6.GOLD),("API CACHE","10-second response",v6.CYAN)]
    for i,(label,detail,col) in enumerate(side):
        y=500+i*86
        d.rounded_rectangle((1365,y,1780,y+68),15,fill=(8,27,46),outline=col,width=2)
        d.text((1387,y+12),label,font=v6.font(14,True),fill=col)
        d.text((1535,y+12),detail,font=v6.font(14),fill=v6.TEXT)
    center_text(d, (960, 960), "OBSERVABILITY WITHOUT MUTATING THE RESEARCH CONTRACT", v6.font(21, True), v6.GOLD)
    return im
def close13(t):
    # Purpose-built closing tableau: no text is floated over a busy source image.
    im = v6.bg()
    d = v6.ImageDraw.Draw(im)
    for x in range(0, v6.W, 96):
        d.line((x, 0, x, v6.H), fill=(5, 24, 39), width=1)
    for y in range(0, v6.H, 96):
        d.line((0, y, v6.W, y), fill=(5, 24, 39), width=1)
    v6.logo(im, 690, 55, 540, 205)
    center_text(d, (960, 275), "FROM GOVERNED EVIDENCE TO AUTONOMOUS EXECUTION", v6.font(34, True), v6.TEXT)

    stages = [
        (250, "GOVERNED DATA", "cloud", v6.CYAN, "trusted inputs"),
        (720, "TESTABLE ML", "ai_brain", (190, 116, 255), "reproducible models"),
        (1200, "RISK CONTROL", "gate", v6.GREEN, "earned deployment"),
        (1670, "USER + SYSTEM", "prediction", v6.GOLD, "disciplined execution"),
    ]
    cy=585
    for i,(cx,label,art,colour,detail) in enumerate(stages):
        active=i<=int(t*4)
        d.ellipse((cx-125,cy-125,cx+125,cy+125),fill=(6,22,38),outline=colour if active else v6.BORDER,width=5)
        if art in ("cloud","ai_brain","prediction"):
            intro12.paste_reference_icon(im,art,cx,cy-18,135)
        else:
            intro12.draw_tech_icon(d,art,cx,cy-18,90,colour)
        center_text(d,(cx,cy+155),label,v6.font(20,True),colour)
        center_text(d,(cx,cy+198),detail.upper(),v6.font(14,True),v6.MUTED)
        if i<len(stages)-1:
            d.line((cx+132,cy,stages[i+1][0]-132,cy),fill=v6.GREEN,width=5)
            d.polygon([(stages[i+1][0]-148,cy-10),(stages[i+1][0]-148,cy+10),(stages[i+1][0]-130,cy)],fill=v6.GREEN)

    center_text(d, (960, 875), "EVIDENCE OVER PROMISES  •  REPRODUCIBILITY OVER HINDSIGHT", v6.font(24, True), v6.CYAN)
    center_text(d, (960, 945), "datashepherdengineering.com", v6.font(23, True), v6.GREEN)
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
    ("intro13", None, "Data Shepherd Engineering is a production-minded research platform founded by Meraj Asari. It connects governed market data, distributed processing, transparent machine learning and forward monitoring in one observable system. Today it is in development and proof-of-concept stages. The long-term vision is a secure autonomous trading system that works alongside the user, pursues substantial returns and earns real deployment through evidence and disciplined risk controls."),
    ("site", ("overview", "THE REAL PLATFORM", "Live product and engineering surfaces—not a notebook demonstration"), "The platform makes the complete system visible: stock and crypto research, model rankings, market context, operational health, protected holdouts and the evidence behind every frozen candidate."),
    ("site", ("engineering", "END-TO-END ENGINEERING", "Ingestion, medallion layers, features, models and prediction"), "Market observations move from ingestion through immutable Bronze storage, cleansed Silver data, curated Gold datasets and model-ready features. Python, PySpark, Pandas and Parquet support the path, while validation stops downstream work when the contract is incomplete."),
    ("tracks13", None, "Data Shepherd now contains three governed research tracks. Stocks use V8 as the frozen active reference. Shared Crypto Fifteen-Minute V2 evaluates BTC, ALT and CASH in shadow mode. XRP remains a separate Ridge-based exploratory track because its history and policy require independent treatment. Each track develops independently while contributing to one long-term autonomous-trading vision."),
    ("cycle3_selection13", None, "V10 Cycle Three began with exactly three preregistered candidates. Their negative-regime entry timing and defensive blend were declared before evaluation. The selection rule was also fixed in advance: a candidate had to pass all thirteen gates, then win on the lowest transition notional, with a lexical tie-break only if necessary."),
    ("cycle3_winner13", None, "The selected challenger is c three confirm two blend fifty. It waits for two completed negative decisions, then combines fifty percent ranked V8 signal with fifty percent defensive signal. On the first non-negative decision it returns immediately to exact V8 scoring. The candidate passed all thirteen gates and was independently frozen under an immutable SHA, creating a disciplined path from research toward earned deployment."),
    ("holdout13", None, "Cycle Three now waits for a fresh forward holdout beginning January fourth, twenty twenty-seven. Original V10 holdout outcomes were not used, and the new future outcomes remain unread and unscored. The journal is append-only, missed decisions are never backfilled, and only genuinely completed post-boundary cohorts may enter performance evidence."),
    ("monitoring13", None, "Operations are intentionally lightweight and read-only. The dashboard reads small status and journal files, caches the response, and displays decisions, entries, completed cohorts, returns, SPY comparison and health alerts. A web request never reads Parquet and never invokes a research or holdout runner."),
    ("site", ("dashboard", "ENGINEERING MADE OBSERVABLE", "Research state, model evidence and safeguards in the product"), "The result is more than a prediction. It is an inspectable engineering system with frozen contracts, verification hashes, service health, separate evidence boundaries and explicit no-order safeguards."),
    ("close13", None, "Data Shepherd Engineering is built around a simple standard: evidence over promises, and reproducibility over hindsight. The goal is to turn governed data and testable machine learning into a secure autonomous system that can trade alongside the user, pursue strong returns, manage risk and compound wealth over time. Engineered for the markets, and built for the future."),
]


def main():
    old = v6.OUT / "data_shepherd_showcase_v12_16x9.mp4"
    new = v6.OUT / "data_shepherd_intro_video_13_16x9.mp4"
    intro12.main()
    if old.exists(): shutil.move(str(old), str(new))
    print(f'\nINTROVIDEO13 DONE: {new}\nopen "{new}"')


if __name__ == "__main__":
    main()
