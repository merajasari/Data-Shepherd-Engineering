"""Data Shepherd Engineering presentation layer.

The member dashboard presents the frozen V5 cross-sectional ranking model,
the separate frozen V4 stock paper-trading monitor, and a read-only Crypto V1
research simulation view.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash

load_dotenv()
sys.path.append("data-ingestion")

from v5_symbols import (  # noqa: E402
    get_v5_company_name,
    get_v5_symbol_options,
    get_v5_symbols,
)
from webapp.services.account_service import (  # noqa: E402
    authenticate_account,
    begin_signup,
    change_password,
    complete_account_setup,
    get_account_setup_context,
    initialize_account_store,
    send_verification_email,
    verify_email_token,
)
from webapp.services.crypto_dashboard_service import get_crypto_dashboard_payload  # noqa: E402
from webapp.services.live_market_service import get_all_live_quotes, get_live_quote  # noqa: E402
from webapp.services.stock_stream_health_service import get_stock_stream_health  # noqa: E402
from webapp.services.crypto_live_market_service import get_all_crypto_live_tickers  # noqa: E402
from webapp.services.crypto_history_service import get_crypto_history_payload  # noqa: E402
from webapp.services.crypto_history_web_cache_service import get_crypto_history_cache_path, normalize_history_range  # noqa: E402
from webapp.services.market_service import get_market_summary, get_recent_prices  # noqa: E402
from webapp.services.prediction_service import get_latest_prediction, get_v5_rankings  # noqa: E402
from webapp.services.paper_trading_service import get_pnl_attribution, get_portfolio_summary  # noqa: E402
from webapp.services.paper_journal_reader import summarize_journal  # noqa: E402
from webapp.services.v5_shadow_portfolio_service import get_v5_shadow_comparison  # noqa: E402
from webapp.services.v5_shadow_history_service import get_v5_shadow_history  # noqa: E402
from webapp.services.v4_realtime_equity_journal_service import get_v4_realtime_equity_history  # noqa: E402


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("FLASK_SECRET_KEY is not configured")

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)
initialize_account_store()


@app.after_request
def inject_dashboard_modules(response):
    """Load small presentation modules without duplicating template markup."""
    if response.mimetype == "text/html" and response.status_code == 200:
        html = response.get_data(as_text=True)
        marker = "</body>"
        scripts = []
        if request.path in {"/", "/dashboard", "/crypto"}:
            scripts.append('<script src="/static/js/signup_button.js" defer></script>')
        if request.path in {"/dashboard", "/crypto"}:
            scripts.append('<script src="/static/js/realtime_market_refresh.js" defer></script>')
        if request.path == "/dashboard":
            scripts.extend([
                '<script src="/static/js/dashboard_layout.js" defer></script>',
                '<script src="/static/js/v4_equity_chart.js" defer></script>',
                '<script src="/static/js/v4_pnl_attribution.js" defer></script>',
                '<script src="/static/js/v5_shadow_comparison.js" defer></script>',
                '<script src="/static/js/v5_shadow_history_chart.js" defer></script>',
                '<script src="/static/js/market_history_chart.js" defer></script>',
                '<script src="/static/js/primary_stock_spotlight.js" defer></script>',
            ])
        if marker in html:
            for script in scripts:
                if script not in html:
                    html = html.replace(marker, script + "\n" + marker, 1)
            response.set_data(html)
    return response


V5_SYMBOLS = get_v5_symbols()
V5_SYMBOL_OPTIONS = get_v5_symbol_options()
DEFAULT_SYMBOL = "AAPL"


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("home"))
        if session.get("must_change_password"):
            return redirect(url_for("change_member_password"))
        return view(*args, **kwargs)
    return wrapped


def valid_legacy_member_credentials(username, password):
    configured_username = os.environ.get("MEMBER_USERNAME", "")
    password_hash = os.environ.get("MEMBER_PASSWORD_HASH", "")
    if not configured_username or not password_hash:
        return False
    return username == configured_username and check_password_hash(password_hash, password)


def build_stock_dashboard(symbol):
    market = get_market_summary(symbol)
    prediction = get_latest_prediction(symbol)
    live = get_live_quote(symbol)
    display_price = live["reference_price"] if live["available"] else market["close"]
    return {
        "symbol": symbol,
        "company_name": get_v5_company_name(symbol),
        "timestamp": market["timestamp"],
        "close": market["close"],
        "display_price": display_price,
        "price_source": "LIVE IEX" if live["available"] else "LATEST EOD",
        "price_change": market["price_change"],
        "price_change_pct": market["price_change_pct"],
        "rsi_14": market["rsi_14"],
        "sma_20": market["sma_20"],
        "sma_50": market["sma_50"],
        "sma_200": market["sma_200"],
        "volatility_20d": market["volatility_20d"],
        "volume_ratio": market["volume_ratio"],
        **prediction,
    }


def build_v4_dashboard_payload():
    forward = dict(summarize_journal())
    portfolio = dict(get_portfolio_summary())
    portfolio["pnl_attribution"] = get_pnl_attribution()
    forward["observations"] = forward.get("observation_count", 0)
    portfolio["open_positions"] = portfolio.get("open_position_count", 0)
    portfolio["top_five"] = forward.get("latest_top_five", [])
    starting_cash = float(portfolio.get("starting_cash") or 100000.0)
    equity = float(portfolio.get("equity") or starting_cash)
    portfolio["net_change"] = equity - starting_cash
    portfolio["net_change_pct"] = (equity / starting_cash - 1.0) if starting_cash else 0.0
    portfolio["top_five_details"] = [
        {"symbol": symbol, "company_name": get_v5_company_name(symbol)}
        for symbol in portfolio["top_five"]
    ]
    history = list(forward.get("equity_history", []))
    history.extend(get_v4_realtime_equity_history())
    history.sort(key=lambda row: str(row.get("timestamp") or ""))
    chart_history = [
        {
            "timestamp": forward.get("start_timestamp"),
            "label": "Start",
            "equity": starting_cash,
            "synthetic_baseline": True,
        },
        *[
            {**row, "label": None, "synthetic_baseline": False}
            for row in history
        ],
    ]
    current_timestamp = datetime.now(timezone.utc).isoformat()
    if not chart_history or abs(float(chart_history[-1]["equity"]) - equity) > 1e-9:
        chart_history.append(
            {
                "timestamp": current_timestamp,
                "label": "Current",
                "equity": equity,
                "synthetic_baseline": False,
                "current_mark": True,
            }
        )
    elif chart_history:
        chart_history[-1] = {**chart_history[-1], "label": "Current", "current_mark": True}
    forward["chart_history"] = chart_history
    return {"forward": forward, "portfolio": portfolio}


def enrich_ranking_rows(rows):
    return [
        {**dict(row), "company_name": get_v5_company_name(row["symbol"])}
        for row in rows
    ]


@app.route("/")
def home():
    return render_template(
        "landing.html",
        authenticated=session.get("authenticated", False),
        login_error=None,
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html", error=None, success=None)

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    try:
        token = begin_signup(full_name, email)
        verification_url = url_for("verify_email", token=token, _external=True, _scheme="https")
        send_verification_email(email, full_name, verification_url)
        return render_template(
            "signup.html",
            error=None,
            success="Verification email sent. Check your inbox and open the link within 30 minutes.",
            full_name=full_name,
            email=email,
        )
    except (ValueError, RuntimeError) as exc:
        return render_template(
            "signup.html",
            error=str(exc),
            success=None,
            full_name=full_name,
            email=email,
        ), 400


@app.route("/verify-email/<token>")
def verify_email(token):
    try:
        setup = verify_email_token(token)
        session["verified_setup_account_id"] = setup["account_id"]
        return render_template(
            "verified_account.html",
            mode="choose_username",
            setup=setup,
            credentials=None,
            error=None,
        )
    except ValueError as exc:
        return render_template(
            "verified_account.html",
            mode="error",
            setup=None,
            credentials=None,
            error=str(exc),
        ), 400


@app.route("/complete-account", methods=["POST"])
def complete_account():
    account_id = session.get("verified_setup_account_id")
    if not account_id:
        return redirect(url_for("signup"))

    requested_username = request.form.get("username", "").strip()
    try:
        credentials = complete_account_setup(account_id, requested_username)
        session.pop("verified_setup_account_id", None)
        return render_template(
            "verified_account.html",
            mode="credentials",
            setup=None,
            credentials=credentials,
            error=None,
        )
    except ValueError as exc:
        try:
            setup = get_account_setup_context(account_id, requested_username)
        except ValueError:
            session.pop("verified_setup_account_id", None)
            return redirect(url_for("signup"))
        return render_template(
            "verified_account.html",
            mode="choose_username",
            setup=setup,
            credentials=None,
            error=str(exc),
        ), 400


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return redirect(url_for("dashboard" if session.get("authenticated") else "home"))

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if valid_legacy_member_credentials(username, password):
        session.clear()
        session.permanent = True
        session["authenticated"] = True
        session["username"] = username
        session["legacy_member"] = True
        return redirect(url_for("dashboard"))

    account = authenticate_account(username, password)
    if account:
        session.clear()
        session.permanent = True
        session["authenticated"] = True
        session["username"] = account["username"]
        session["account_id"] = account["id"]
        session["must_change_password"] = bool(account["must_change_password"])
        if session["must_change_password"]:
            return redirect(url_for("change_member_password"))
        return redirect(url_for("dashboard"))

    return render_template(
        "landing.html",
        authenticated=False,
        login_error="Invalid username or password.",
    ), 401


@app.route("/change-password", methods=["GET", "POST"])
def change_member_password():
    if not session.get("authenticated") or not session.get("account_id"):
        return redirect(url_for("home"))
    if not session.get("must_change_password"):
        return redirect(url_for("dashboard"))
    if request.method == "GET":
        return render_template("change_password.html", error=None)

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    if new_password != confirm_password:
        return render_template("change_password.html", error="New passwords do not match."), 400
    try:
        change_password(session["account_id"], current_password, new_password)
        session["must_change_password"] = False
        return redirect(url_for("dashboard"))
    except ValueError as exc:
        return render_template("change_password.html", error=str(exc)), 400


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    selected_symbol = request.args.get("symbol", DEFAULT_SYMBOL).upper().strip()
    if selected_symbol not in V5_SYMBOLS:
        return redirect(url_for("dashboard", symbol=DEFAULT_SYMBOL))

    selected = build_stock_dashboard(selected_symbol)
    recent_prices = get_recent_prices(selected_symbol, limit=60)
    rankings_payload = get_v5_rankings()
    rankings = enrich_ranking_rows(rankings_payload["rankings"])
    top5 = rankings[:5]

    top10_rows = []
    for row in rankings[:10]:
        try:
            market = get_market_summary(row["symbol"])
            live = get_live_quote(row["symbol"])
            row = dict(row)
            row["display_price"] = live["reference_price"] if live["available"] else market["close"]
            row["eod_change_pct"] = market["price_change_pct"]
            row["rsi_14"] = market["rsi_14"]
            top10_rows.append(row)
        except Exception as exc:
            print(f"[V5 TOP10 ERROR] {row['symbol']}: {exc}")

    return render_template(
        "index.html",
        selected=selected,
        recent_prices=recent_prices,
        rankings=rankings,
        top5=top5,
        top10_rows=top10_rows,
        v5_symbols=V5_SYMBOL_OPTIONS,
        v5=rankings_payload,
    )


@app.route("/crypto")
@login_required
def crypto_dashboard():
    return render_template("crypto.html", crypto=get_crypto_dashboard_payload())


@app.route("/crypto-visual")
@login_required
def crypto_visual_dashboard():
    return render_template("crypto_visual.html", crypto=get_crypto_dashboard_payload())


@app.route("/api/crypto-v1")
@login_required
def api_crypto_v1():
    return jsonify(get_crypto_dashboard_payload())


@app.route("/api/v5-rankings")
@login_required
def api_v5_rankings():
    payload = dict(get_v5_rankings())
    payload["rankings"] = enrich_ranking_rows(payload["rankings"])
    return jsonify(payload)


@app.route("/api/dashboard-stock/<symbol>")
@login_required
def api_dashboard_stock(symbol):
    symbol = symbol.upper().strip()
    if symbol not in V5_SYMBOLS:
        return jsonify({"error": "unsupported symbol"}), 404
    return jsonify({"stock": build_stock_dashboard(symbol), "recent_prices": get_recent_prices(symbol, limit=60)})


@app.route("/api/prices/<symbol>")
@login_required
def api_prices(symbol):
    symbol = symbol.upper().strip()
    if symbol not in V5_SYMBOLS:
        return jsonify({"error": "unsupported symbol"}), 404
    return jsonify(get_recent_prices(symbol, limit=60))


@app.route("/api/live/<symbol>")
@login_required
def api_live_quote(symbol):
    return jsonify(get_live_quote(symbol.upper().strip()))


@app.route("/api/live")
@login_required
def api_live_quotes():
    return jsonify(get_all_live_quotes())


@app.route("/api/stock-stream-health")
@login_required
def api_stock_stream_health():
    return jsonify(get_stock_stream_health())


@app.route("/api/crypto-live")
@login_required
def api_crypto_live_quotes():
    return jsonify(get_all_crypto_live_tickers())


@app.route("/api/crypto-history")
@login_required
def api_crypto_history():
    range_name = normalize_history_range(request.args.get("range"))
    cache_path = get_crypto_history_cache_path(range_name)
    if cache_path.exists():
        response = send_file(
            cache_path,
            mimetype="application/json",
            conditional=True,
            max_age=30,
        )
        response.headers["Cache-Control"] = "private, max-age=30"
        response.headers["X-Data-Shepherd-History-Source"] = "persistent-web-cache"
        return response

    # Safe fallback for first install or a missing cache file. This preserves the
    # current read-only service contract, but normal page loads should never need it.
    try:
        payload = get_crypto_history_payload(range_name=range_name)
    except TypeError:
        payload = get_crypto_history_payload()
    return jsonify(payload)

@app.route("/api/paper-portfolio")
@login_required
def api_paper_portfolio():
    return jsonify(get_portfolio_summary())


@app.route("/api/v4-forward")
@login_required
def api_v4_forward():
    return jsonify(build_v4_dashboard_payload())


@app.route("/api/v5-shadow-comparison")
@login_required
def api_v5_shadow_comparison():
    return jsonify(get_v5_shadow_comparison())


@app.route("/api/v5-shadow-history")
@login_required
def api_v5_shadow_history():
    return jsonify(get_v5_shadow_history())


@app.route("/health")
def health():
    live_state = get_all_live_quotes()
    rankings = get_v5_rankings()
    return jsonify({
        "status": "healthy",
        "service": "stock-market-ai-platform",
        "v5_candidates": rankings.get("candidate_count", 100),
        "v5_decision_date_utc": rankings.get("decision_date_utc"),
        "live_symbols": live_state["symbol_count"],
        "live_cache_updated_at": live_state["updated_at"],
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
