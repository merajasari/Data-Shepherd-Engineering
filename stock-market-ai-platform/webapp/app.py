from webapp.services.v8_holdout_service import get_v8_holdout_dashboard
from webapp.services.v10_cycle3_holdout_service import get_v10_cycle3_holdout_dashboard
from webapp.services.v10_cycle3_accelerated_v2_service import get_v10_cycle3_accelerated_dashboard
from webapp.services.v14_ml_ai_service import get_v14_ml_ai_dashboard
from webapp.services.v15_intraday_v7_service import get_v15_intraday_v7_dashboard
from webapp.services.v11_phase2_service import get_v11_phase2_dashboard
from webapp.services.v13_regime_overlay_service import get_v13_regime_overlay_dashboard
"""Data Shepherd Engineering presentation layer."""
import os, sys, time
from collections import defaultdict, deque
import requests
from datetime import datetime, timedelta, timezone
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash
load_dotenv(); sys.path.append("data-ingestion")
from v5_symbols import get_v5_company_name, get_v5_sector, get_v5_symbol_options, get_v5_symbols  # noqa: E402
from webapp.services.account_service import authenticate_account, begin_signup, change_password, complete_account_setup, get_account_setup_context, initialize_account_store, send_verification_email, verify_email_token  # noqa: E402
# Dashboard research/data services are intentionally imported on first use.
# This keeps health and lightweight holdout requests from loading Pandas/PyArrow
# into a fresh Gunicorn worker and avoids multiplying startup memory.
def _lazy(module,name,*args,**kwargs):
    from importlib import import_module
    return getattr(import_module(module),name)(*args,**kwargs)

def get_crypto_dashboard_payload(*a,**k):return _lazy("webapp.services.crypto_dashboard_service","get_crypto_dashboard_payload",*a,**k)
def get_all_live_quotes(*a,**k):return _lazy("webapp.services.live_market_service","get_all_live_quotes",*a,**k)
def get_live_quote(*a,**k):return _lazy("webapp.services.live_market_service","get_live_quote",*a,**k)
def get_stock_stream_health(*a,**k):return _lazy("webapp.services.stock_stream_health_service","get_stock_stream_health",*a,**k)
def get_all_crypto_live_tickers(*a,**k):return _lazy("webapp.services.crypto_live_market_service","get_all_crypto_live_tickers",*a,**k)
def get_crypto_history_payload(*a,**k):return _lazy("webapp.services.crypto_history_service","get_crypto_history_payload",*a,**k)
def get_crypto_history_cache_path(*a,**k):return _lazy("webapp.services.crypto_history_web_cache_service","get_crypto_history_cache_path",*a,**k)
def normalize_history_range(*a,**k):return _lazy("webapp.services.crypto_history_web_cache_service","normalize_history_range",*a,**k)
def get_market_summary(*a,**k):return _lazy("webapp.services.market_service","get_market_summary",*a,**k)
def get_recent_prices(*a,**k):return _lazy("webapp.services.market_service","get_recent_prices",*a,**k)
def get_recent_prices_local(*a,**k):return _lazy("webapp.services.fast_market_history_service","get_recent_prices_local",*a,**k)
def get_bulk_local_history(*a,**k):return _lazy("webapp.services.bulk_local_history_service","get_bulk_local_history",*a,**k)
def get_symbol_24h_intraday(*a,**k):return _lazy("webapp.services.today_intraday_service","get_symbol_24h_intraday",*a,**k)
def get_today_top10_intraday(*a,**k):return _lazy("webapp.services.today_intraday_service","get_today_top10_intraday",*a,**k)
def get_latest_prediction(*a,**k):return _lazy("webapp.services.prediction_service","get_latest_prediction",*a,**k)
def get_v8_rankings(*a,**k):return _lazy("webapp.services.prediction_service","get_v8_rankings",*a,**k)
def get_pnl_attribution(*a,**k):return _lazy("webapp.services.paper_trading_service","get_pnl_attribution",*a,**k)
def get_portfolio_summary(*a,**k):return _lazy("webapp.services.paper_trading_service","get_portfolio_summary",*a,**k)
def summarize_journal(*a,**k):return _lazy("webapp.services.paper_journal_reader","summarize_journal",*a,**k)
def get_v5_shadow_comparison(*a,**k):return _lazy("webapp.services.v5_shadow_portfolio_service","get_v5_shadow_comparison",*a,**k)
def get_v5_shadow_history(*a,**k):return _lazy("webapp.services.v5_shadow_history_service","get_v5_shadow_history",*a,**k)
def get_v4_realtime_equity_history(*a,**k):return _lazy("webapp.services.v4_realtime_equity_journal_service","get_v4_realtime_equity_history",*a,**k)
def get_v4_reconstructed_history(*a,**k):return _lazy("webapp.services.v4_reconstructed_history_service","get_v4_reconstructed_history",*a,**k)
app=Flask(__name__); app.secret_key=os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key: raise RuntimeError("FLASK_SECRET_KEY is not configured")
app.config.update(SESSION_COOKIE_SECURE=True,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",PERMANENT_SESSION_LIFETIME=timedelta(hours=12)); initialize_account_store()
IDLE_TIMEOUT_SECONDS=300
_REQUEST_TIMINGS=defaultdict(lambda:deque(maxlen=200))
@app.before_request
def begin_request_timing():
    g.request_started_monotonic=time.perf_counter()

@app.after_request
def inject_dashboard_modules(response):
    if response.mimetype=="text/html" and response.status_code==200:
        html=response.get_data(as_text=True); marker="</body>"; scripts=[]
        if request.path=="/dashboard" and request.args.get("view")=="live":
            head_marker="</head>"
            prelayout='''<style id="ds-live-prelayout-style">html.ds-live-prelayout .card:has(#stock-select){display:none!important}html.ds-live-prelayout .card.ds-live-viewer-card:has(#stock-select){display:block!important}</style><script>document.documentElement.classList.add("ds-live-prelayout")</script>'''
            if head_marker in html and 'ds-live-prelayout-style' not in html:
                html=html.replace(head_marker,prelayout+"\n"+head_marker,1)
        if request.path in {"/","/dashboard","/crypto","/crypto-visual","/trading-readiness"}:
            scripts.extend(['<script src="/static/js/signup_button.js" defer></script>','<script src="/static/js/customer_ai_chat.js" defer></script>'])
        if request.path in {"/dashboard","/crypto","/crypto-visual","/trading-readiness"}:
            scripts.extend(['<script src="/static/js/session_idle_timeout.js" defer></script>','<script src="/static/js/trading_readiness_nav.js" defer></script>'])
        if request.path in {"/dashboard","/crypto"}: scripts.append('<script src="/static/js/realtime_market_refresh.js" defer></script>')
        if request.path=="/dashboard":
            shared=['<script src="/static/js/v8_holdout_snapshot.js" defer></script>','<script src="/static/js/dashboard_layout.js" defer></script>','<script src="/static/js/market_history_chart.js" defer></script>','<script src="/static/js/primary_stock_spotlight.js" defer></script>','<script src="/static/js/top_live_stock_comparison.js" defer></script>','<script src="/static/js/company_name_tooltip_enhancer.js" defer></script>']
            scripts.extend(shared)
            if request.args.get("view")!="live":
                scripts.extend(['<script src="/static/js/v4_equity_chart.js" defer></script>','<script src="/static/js/v4_pnl_attribution.js" defer></script>','<script src="/static/js/v10_confirmation_dashboard.js" defer></script>','<script src="/static/js/v10_cycle3_accelerated_v2_dashboard.js" defer></script>','<script src="/static/js/v10_cycle3_holdout_monitor.js" defer></script>','<script src="/static/js/model_research_tabs.js" defer></script>','<script src="/static/js/overview_live_paper_dashboard.js" defer></script>','<script src="/static/js/v14_ml_ai_dashboard.js" defer></script>','<script src="/static/js/v15_intraday_v7_dashboard.js" defer></script>','<script src="/static/js/v13_regime_overlay_status.js" defer></script>','<script src="/static/js/v8_stream_health_visual.js" defer></script>'])
        if marker in html:
            for script in scripts:
                if script not in html: html=html.replace(marker,script+"\n"+marker,1)
            response.set_data(html)
    started=getattr(g,"request_started_monotonic",None)
    if started is not None:
        elapsed_ms=(time.perf_counter()-started)*1000.0
        endpoint=request.url_rule.endpoint if request.url_rule else request.path
        _REQUEST_TIMINGS[endpoint].append(elapsed_ms)
        response.headers["Server-Timing"]=f"app;dur={elapsed_ms:.2f}"
        response.headers["X-Response-Time-Ms"]=f"{elapsed_ms:.2f}"
    return response
V5_SYMBOLS=get_v5_symbols(); V5_SYMBOL_OPTIONS=get_v5_symbol_options(); DEFAULT_SYMBOL="AAPL"
def _session_idle_expired():
    raw=session.get("last_activity_utc")
    if not raw:
        session["last_activity_utc"]=datetime.now(timezone.utc).isoformat()
        return False
    try: last=datetime.fromisoformat(str(raw).replace("Z","+00:00")).astimezone(timezone.utc)
    except (TypeError,ValueError): return True
    return (datetime.now(timezone.utc)-last).total_seconds()>=IDLE_TIMEOUT_SECONDS

def login_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not session.get("authenticated"): return (jsonify({"error":"authentication required"}),401) if request.path.startswith("/api/") else redirect(url_for("home"))
        if _session_idle_expired():
            session.clear()
            return (jsonify({"error":"session expired due to inactivity"}),401) if request.path.startswith("/api/") else redirect(url_for("home",reason="inactive"))
        if session.get("must_change_password"): return redirect(url_for("change_member_password"))
        return view(*args,**kwargs)
    return wrapped
def valid_legacy_member_credentials(username,password):
    u=os.environ.get("MEMBER_USERNAME",""); h=os.environ.get("MEMBER_PASSWORD_HASH",""); return bool(u and h and username==u and check_password_hash(h,password))
def build_stock_dashboard(symbol):
    market=get_market_summary(symbol); prediction=get_latest_prediction(symbol); live=get_live_quote(symbol); display_price=live["reference_price"] if live["available"] else market["close"]
    return {"symbol":symbol,"company_name":get_v5_company_name(symbol),"timestamp":market["timestamp"],"close":market["close"],"display_price":display_price,"price_source":"LIVE IEX" if live["available"] else "LATEST EOD","price_change":market["price_change"],"price_change_pct":market["price_change_pct"],"rsi_14":market["rsi_14"],"sma_20":market["sma_20"],"sma_50":market["sma_50"],"sma_200":market["sma_200"],"volatility_20d":market["volatility_20d"],"volume_ratio":market["volume_ratio"],**prediction}
def build_v4_dashboard_payload():
    forward=dict(summarize_journal()); portfolio=dict(get_portfolio_summary()); portfolio["pnl_attribution"]=get_pnl_attribution(); forward["observations"]=forward.get("observation_count",0); portfolio["open_positions"]=portfolio.get("open_position_count",0); portfolio["top_five"]=forward.get("latest_top_five",[])
    starting_cash=float(portfolio.get("starting_cash") or 100000.0); equity=float(portfolio.get("equity") or starting_cash); portfolio["net_change"]=equity-starting_cash; portfolio["net_change_pct"]=(equity/starting_cash-1.0) if starting_cash else 0.0; portfolio["top_five_details"]=[{"symbol":s,"company_name":get_v5_company_name(s)} for s in portfolio["top_five"]]
    reconstructed=list(get_v4_reconstructed_history()); history=list(reconstructed); history.extend(forward.get("equity_history",[])); history.extend(get_v4_realtime_equity_history()); history.sort(key=lambda r:str(r.get("timestamp") or "")); reconstructed_start=reconstructed[0].get("timestamp") if reconstructed else forward.get("start_timestamp")
    chart_history=[{"timestamp":reconstructed_start,"label":"Start","equity":starting_cash,"synthetic_baseline":True,"history_type":"reconstruction_baseline" if reconstructed else "paper_baseline"}, *[{**r,"label":None,"synthetic_baseline":False} for r in history]]; current_timestamp=datetime.now(timezone.utc).isoformat()
    if not chart_history or abs(float(chart_history[-1]["equity"])-equity)>1e-9: chart_history.append({"timestamp":current_timestamp,"label":"Current","equity":equity,"synthetic_baseline":False,"current_mark":True})
    elif chart_history: chart_history[-1]={**chart_history[-1],"label":"Current","current_mark":True}
    forward["chart_history"]=chart_history; forward["reconstructed_observations"]=len(reconstructed); forward["reconstructed_start_timestamp"]=reconstructed_start; return {"forward":forward,"portfolio":portfolio}
def enrich_ranking_rows(rows): return [{**dict(r),"company_name":get_v5_company_name(r["symbol"]),"sector":get_v5_sector(r["symbol"])} for r in rows]
@app.route("/")
def home(): return render_template("landing.html",authenticated=session.get("authenticated",False),login_error=None)
@app.route("/signup",methods=["GET","POST"])
def signup():
    if request.method=="GET": return render_template("signup.html",error=None,success=None)
    full_name=request.form.get("full_name","").strip(); email=request.form.get("email","").strip()
    try:
        token=begin_signup(full_name,email); verification_url=url_for("verify_email",token=token,_external=True,_scheme="https"); send_verification_email(email,full_name,verification_url); return render_template("signup.html",error=None,success="Verification email sent. Check your inbox and open the link within 30 minutes.",full_name=full_name,email=email)
    except (ValueError,RuntimeError) as exc: return render_template("signup.html",error=str(exc),success=None,full_name=full_name,email=email),400
@app.route("/verify-email/<token>")
def verify_email(token):
    try:
        setup=verify_email_token(token); session["verified_setup_account_id"]=setup["account_id"]; return render_template("verified_account.html",mode="choose_username",setup=setup,credentials=None,error=None)
    except ValueError as exc: return render_template("verified_account.html",mode="error",setup=None,credentials=None,error=str(exc)),400
@app.route("/complete-account",methods=["POST"])
def complete_account():
    account_id=session.get("verified_setup_account_id")
    if not account_id:return redirect(url_for("signup"))
    requested_username=request.form.get("username","").strip()
    try:
        credentials=complete_account_setup(account_id,requested_username); session.pop("verified_setup_account_id",None); return render_template("verified_account.html",mode="credentials",setup=None,error=None,credentials=credentials)
    except ValueError as exc:
        try: setup=get_account_setup_context(account_id,requested_username)
        except ValueError: session.pop("verified_setup_account_id",None); return redirect(url_for("signup"))
        return render_template("verified_account.html",mode="choose_username",setup=setup,credentials=None,error=str(exc)),400
@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="GET":return redirect(url_for("dashboard" if session.get("authenticated") else "home"))
    username=request.form.get("username","").strip(); password=request.form.get("password","")
    if valid_legacy_member_credentials(username,password): session.clear();session.permanent=True;session["authenticated"]=True;session["username"]=username;session["legacy_member"]=True;session["last_activity_utc"]=datetime.now(timezone.utc).isoformat();return redirect(url_for("dashboard"))
    account=authenticate_account(username,password)
    if account:
        session.clear();session.permanent=True;session["authenticated"]=True;session["username"]=account["username"];session["account_id"]=account["id"];session["must_change_password"]=bool(account["must_change_password"]);session["last_activity_utc"]=datetime.now(timezone.utc).isoformat(); return redirect(url_for("change_member_password" if session["must_change_password"] else "dashboard"))
    return render_template("landing.html",authenticated=False,login_error="Invalid username or password."),401
@app.route("/change-password",methods=["GET","POST"])
def change_member_password():
    if not session.get("authenticated") or not session.get("account_id"):return redirect(url_for("home"))
    if not session.get("must_change_password"):return redirect(url_for("dashboard"))
    if request.method=="GET":return render_template("change_password.html",error=None)
    current_password=request.form.get("current_password","");new_password=request.form.get("new_password","");confirm_password=request.form.get("confirm_password","")
    if new_password!=confirm_password:return render_template("change_password.html",error="New passwords do not match."),400
    try: change_password(session["account_id"],current_password,new_password);session["must_change_password"]=False;return redirect(url_for("dashboard"))
    except ValueError as exc:return render_template("change_password.html",error=str(exc)),400
@app.route("/logout")
def logout():session.clear();return redirect(url_for("home"))
@app.post("/api/session/activity")
@login_required
def api_session_activity():
    session["last_activity_utc"]=datetime.now(timezone.utc).isoformat()
    return jsonify({"status":"active","idle_timeout_seconds":IDLE_TIMEOUT_SECONDS})

CUSTOMER_CHAT_PAGES={"landing":"landing page","research":"Model Research","live":"Live Stock Viewer","crypto":"Crypto dashboard","crypto_visual":"Crypto Visual","platform":"platform"}
CUSTOMER_CHAT_ADVICE_PHRASES=("should i buy","should i sell","what should i buy","what stock should","recommend a stock","recommend stocks","good investment","price target","guaranteed return","tell me what to trade","invest my money")

def _customer_chat_page(raw):
    return str(raw or "").strip().lower() if str(raw or "").strip().lower() in CUSTOMER_CHAT_PAGES else "platform"

def _customer_chat_is_advice_request(message):
    text=" ".join(str(message or "").lower().split())
    return any(phrase in text for phrase in CUSTOMER_CHAT_ADVICE_PHRASES)

def _customer_chat_fallback(message,page="platform"):
    text=message.lower();location=CUSTOMER_CHAT_PAGES[_customer_chat_page(page)]
    if _customer_chat_is_advice_request(message):
        return "I can explain Data Shepherd's research evidence, rankings, and risk labels, but I cannot recommend buying or selling an asset, set a price target, or provide personalized financial advice. You can ask me how a model score or chart should be interpreted."
    if "v10" in text:return "V10 Cycle 3 is the frozen c3_confirm2_blend50 candidate. Its reconstructed chart line, accelerated paper-forward evidence beginning September 8, 2026, and independent January 4, 2027 confirmation are three separate evidence streams. Automatic promotion is disabled and brokerage orders remain off."
    if "v15" in text or "intraday ml" in text:return "V15 V7 is the platform's preregistered intraday machine-learning paper shadow. It combines completed V11 five-minute features with prior-close V14 context, uses an immutable ridge-return model, caps exposure at 60%, holds for 120 minutes with a gap-aware 2% protective stop and 10-bps modeled cost, and begins prospective evidence on September 21, 2026. Brokerage orders and automatic promotion are disabled."
    if "v14" in text or "logistic" in text or "machine learning" in text:return "V14 is the platform's trained machine-learning candidate. It retrains logistic regression with a five-session purge gap, records every learned coefficient and model snapshot, ranks the frozen 100-stock universe by predicted five-session up probability, and collects isolated paper-forward evidence beginning September 11, 2026. Brokerage orders and automatic promotion are disabled."
    if "v8" in text or "holdout" in text:return "V8 is the sole frozen near-term forward model. Its formal holdout begins September 1, 2026 using Top 10 equal weights, next-open entry, a five-session hold, and 10-bps modeled trading cost."
    if "comparison" in text or "chart" in text:return "The Model Performance Comparison places V4, V5, frozen V8, frozen V10 Cycle 3 reconstruction, and SPY on the same hypothetical $100,000 basis. It excludes live balances and genuine forward evidence."
    if "rank" in text or "signal" in text:return "The ranking score orders stocks cross-sectionally. It is not a probability, guaranteed return, price forecast, or individualized trade recommendation."
    if "provisional" in text or "live data" in text:return "A provisional live value uses the newest intraday reference price and can change before the session closes. Completed-session indicators remain labeled separately so live and finalized evidence are not mixed."
    return f"I can explain the {location}, model comparisons, frozen holdouts, ranking signals, forward evidence, dashboard controls, and platform terminology. Please ask about one of those areas."

@app.post("/api/customer-chat")
def api_customer_chat():
    now=datetime.now(timezone.utc).timestamp()
    recent=[float(stamp) for stamp in session.get("customer_chat_requests",[]) if now-float(stamp)<60]
    if len(recent)>=10:return jsonify({"error":"Please wait a moment before sending another message."}),429
    recent.append(now);session["customer_chat_requests"]=recent
    body=request.get_json(silent=True) or {};message=str(body.get("message") or "").strip();page=_customer_chat_page(body.get("page"))
    if not message:return jsonify({"error":"message is required"}),400
    if len(message)>2000:return jsonify({"error":"message is too long"}),400
    if _customer_chat_is_advice_request(message):return jsonify({"reply":_customer_chat_fallback(message,page),"mode":"safety_guide"})
    key=os.environ.get("OPENAI_API_KEY","").strip()
    if not key:return jsonify({"reply":_customer_chat_fallback(message,page),"mode":"platform_guide"})
    instructions=("You are the Data Shepherd Engineering customer platform guide. Explain only the dashboard, data pipeline, model research, frozen holdouts, and terminology. "
                  "Never give personalized financial advice, tell users to buy or sell, promise returns, or describe reconstructed results as live performance. "
                  "Do not provide current prices, price targets, forecasts, or claims outside the supplied platform context. Explain that ranking scores are ordering signals, not probabilities. "
                  "Be concise and clearly distinguish development reconstruction from genuine forward evidence.")
    try:
        response=requests.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json={"model":os.environ.get("DS_CHAT_MODEL","gpt-5-mini"),"instructions":instructions,"input":f"Current page: {page}\\nCustomer: {message}","max_output_tokens":500},timeout=25)
        response.raise_for_status();data=response.json();reply=data.get("output_text")
        if not reply:
            reply="".join(item.get("text","") for output in data.get("output",[]) for item in output.get("content",[]) if item.get("type")=="output_text")
        if not reply:raise RuntimeError("empty assistant response")
        return jsonify({"reply":reply,"mode":"ai"})
    except Exception as exc:
        print(f"[CUSTOMER CHAT ERROR] {type(exc).__name__}: {exc}")
        return jsonify({"reply":_customer_chat_fallback(message,page),"mode":"platform_guide"})
@app.route("/dashboard")
@login_required
def dashboard():
    selected_symbol=request.args.get("symbol",DEFAULT_SYMBOL).upper().strip()
    if selected_symbol not in V5_SYMBOLS:return redirect(url_for("dashboard",symbol=DEFAULT_SYMBOL))
    live_view=request.args.get("view")=="live"; selected=build_stock_dashboard(selected_symbol); recent_prices=get_recent_prices_local(selected_symbol,limit=60) if live_view else get_recent_prices(selected_symbol,limit=60); rankings_payload=get_v8_rankings();rankings=enrich_ranking_rows(rankings_payload["rankings"]);top10=rankings[:10];top10_rows=[]
    if not live_view:
        for row in rankings[:10]:
            try:
                market=get_market_summary(row["symbol"]);live=get_live_quote(row["symbol"]);row=dict(row);row["display_price"]=live["reference_price"] if live["available"] else market["close"];row["eod_change_pct"]=market["price_change_pct"];row["rsi_14"]=market["rsi_14"];top10_rows.append(row)
            except Exception as exc:print(f"[V8 TOP10 ERROR] {row['symbol']}: {exc}")
    return render_template("index.html",selected=selected,recent_prices=recent_prices,rankings=rankings,top10=top10,top10_rows=top10_rows,stock_symbols=V5_SYMBOL_OPTIONS,v8=rankings_payload,live_view=live_view)
@app.route("/trading-readiness")
@login_required
def trading_readiness():
    from webapp.services.trading_readiness_service import get_trading_readiness
    return render_template("trading_readiness.html",readiness=get_trading_readiness())

@app.route("/crypto")
@login_required
def crypto_dashboard():return render_template("crypto.html",crypto=get_crypto_dashboard_payload())
@app.route("/crypto-visual")
@login_required
def crypto_visual_dashboard():return render_template("crypto_visual.html",crypto=get_crypto_dashboard_payload())
@app.route("/api/crypto-v1")
@login_required
def api_crypto_v1():return jsonify(get_crypto_dashboard_payload())
@app.route("/api/v8-rankings")
@login_required
def api_v8_rankings():
    payload=dict(get_v8_rankings());payload["rankings"]=enrich_ranking_rows(payload["rankings"]);return jsonify(payload)
@app.route("/api/v5-rankings")
@login_required
def api_v5_rankings_compatibility():
    return api_v8_rankings()
@app.route("/api/dashboard-stock/<symbol>")
@login_required
def api_dashboard_stock(symbol):
    symbol=symbol.upper().strip()
    if symbol not in V5_SYMBOLS:return jsonify({"error":"unsupported symbol"}),404
    return jsonify({"stock":build_stock_dashboard(symbol),"recent_prices":get_recent_prices(symbol,limit=60)})
@app.route("/api/prices/<symbol>")
@login_required
def api_prices(symbol):
    symbol=symbol.upper().strip()
    if symbol not in V5_SYMBOLS:return jsonify({"error":"unsupported symbol"}),404
    # This endpoint feeds the interactive Market History chart and the live
    # EOD refresh dispatcher.  Returning only 60 rows caused ALL/5Y/3Y/1Y to
    # collapse to the same ~90-day window every time the asynchronous refresh
    # replaced the longer initial page payload.  Use the local gold history so
    # range controls retain the multi-year data they require without REST I/O.
    return jsonify(get_recent_prices_local(symbol,limit=2600))
@app.route("/api/local-history-bulk")
@login_required
def api_local_history_bulk():
    limit=request.args.get("limit",130,type=int) or 130
    return jsonify({"series":get_bulk_local_history(V5_SYMBOLS,limit=limit)})
@app.route("/api/intraday-24h-top10")
@login_required
def api_intraday_24h_top10():return jsonify(get_today_top10_intraday(V5_SYMBOLS))
@app.route("/api/intraday-24h/<symbol>")
@login_required
def api_intraday_24h_symbol(symbol):
    symbol=symbol.upper().strip()
    if symbol not in V5_SYMBOLS:return jsonify({"error":"unsupported symbol"}),404
    return jsonify(get_symbol_24h_intraday(symbol))
@app.route("/api/live-prices")
@login_required
def api_live_prices():return jsonify({"stocks":get_all_live_quotes()})
@app.route("/api/crypto-live")
@login_required
def api_crypto_live():return jsonify({"crypto":get_all_crypto_live_tickers()})
@app.route("/api/stock-stream-health")
@login_required
def api_stock_stream_health():return jsonify(get_stock_stream_health())
@app.route("/api/v4-forward")
@login_required
def api_v4_forward():return jsonify(build_v4_dashboard_payload())
@app.route("/api/v5-shadow")
@login_required
def api_v5_shadow():return jsonify(get_v5_shadow_comparison())
@app.route("/api/v5-shadow-history")
@login_required
def api_v5_shadow_history():return jsonify(get_v5_shadow_history())
@app.route("/api/crypto-history")
@login_required
def api_crypto_history():return jsonify(get_crypto_history_payload(normalize_history_range(request.args.get("range","ALL"))))
@app.route("/api/crypto-history-file")
@login_required
def api_crypto_history_file():
    history_range=normalize_history_range(request.args.get("range","ALL"));path=get_crypto_history_cache_path(history_range)
    if not path.exists():get_crypto_history_payload(history_range)
    return send_file(path,mimetype="application/json",conditional=True,max_age=30)
@app.route("/health")
def health():return jsonify({"status":"ok","service":"data-shepherd-web","timestamp_utc":datetime.now(timezone.utc).isoformat()})

@app.get("/api/operations/performance")
def api_operations_performance():
    endpoints={}
    for name,samples in sorted(_REQUEST_TIMINGS.items()):
        values=sorted(samples);count=len(values)
        if not count:continue
        endpoints[name]={"count":count,"latest_ms":round(samples[-1],2),"p50_ms":round(values[(count-1)//2],2),"p95_ms":round(values[max(0,int(count*.95)-1)],2),"max_ms":round(values[-1],2)}
    return jsonify({"status":"ok","sample_limit_per_endpoint":200,"endpoints":endpoints,
                    "heavy_modules_loaded":{"pandas":"pandas" in sys.modules,"pyarrow":"pyarrow" in sys.modules},
                    "startup_policy":"research services are lazy-loaded; lightweight health/holdout paths do not require Pandas or PyArrow",
                    "brokerage_orders":False})
@app.get("/api/v8/holdout")
def api_v8_holdout():
    response=jsonify(get_v8_holdout_dashboard())
    response.headers["Cache-Control"]="private, max-age=5"
    response.headers["X-Data-Serving-Path"]="lightweight-files; no-historical-parquet"
    return response
@app.get("/api/v10/cycle3/holdout")
def api_v10_cycle3_holdout():
    response=jsonify(get_v10_cycle3_holdout_dashboard())
    response.headers["Cache-Control"]="private, max-age=5"
    response.headers["X-Data-Serving-Path"]="lightweight-files"
    return response
@app.get("/api/v10/cycle3/accelerated-v2")
def api_v10_cycle3_accelerated():
    response=jsonify(get_v10_cycle3_accelerated_dashboard())
    response.headers["Cache-Control"]="private, max-age=5"
    response.headers["X-Data-Serving-Path"]="accelerated-status-and-journal-only; no-runner; no-january-holdout"
    return response
@app.get("/api/v15/intraday-v7")
def api_v15_intraday_v7():
    response=jsonify(get_v15_intraday_v7_dashboard())
    response.headers["Cache-Control"]="private, max-age=5"
    response.headers["X-Data-Serving-Path"]="lightweight-v15-status-model-and-journal-only; no-runner; no-network; no-historical-results"
    return response
@app.get("/api/v14/ml-ai")
def api_v14_ml_ai():
    response=jsonify(get_v14_ml_ai_dashboard())
    response.headers["Cache-Control"]="private, max-age=5"
    response.headers["X-Data-Serving-Path"]="lightweight-v14-status-journal-and-live-cache; no-runner; no-network"
    return response
@app.get("/api/v11/phase2")
def api_v11_phase2():
    response=jsonify(get_v11_phase2_dashboard())
    response.headers["Cache-Control"]="private, max-age=5"
    response.headers["X-Data-Serving-Path"]="lightweight-files; no-historical-intraday-load"
    return response
@app.get("/api/v13/regime-overlay")
def api_v13_regime_overlay():
    response=jsonify(get_v13_regime_overlay_dashboard())
    response.headers["Cache-Control"]="private, max-age=5"
    response.headers["X-Data-Serving-Path"]="lightweight-files; no-historical-reconstruction-load"
    return response
if __name__=="__main__":app.run(host="0.0.0.0",port=5000,debug=False)
