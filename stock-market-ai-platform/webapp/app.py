"""Data Shepherd Engineering presentation layer.

The member dashboard presents the frozen V5 cross-sectional ranking model
natively while keeping the separate frozen V4 paper-trading monitor visible.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

load_dotenv()
sys.path.append("data-ingestion")

from v5_symbols import (  # noqa: E402
    get_v5_company_name,
    get_v5_symbol_options,
    get_v5_symbols,
)
from webapp.services.live_market_service import get_all_live_quotes, get_live_quote  # noqa: E402
from webapp.services.market_service import get_market_summary, get_recent_prices  # noqa: E402
from webapp.services.prediction_service import get_latest_prediction, get_v5_rankings  # noqa: E402
from webapp.services.paper_trading_service import get_portfolio_summary  # noqa: E402
from webapp.services.paper_journal_reader import summarize_journal  # noqa: E402


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


@app.after_request
def inject_dashboard_market_chart(response):
    """Load dashboard-only interactive chart modules."""
    if (
        request.path == "/dashboard"
        and response.mimetype == "text/html"
        and response.status_code == 200
    ):
        html = response.get_data(as_text=True)
        marker = "</body>"
        scripts = (
            '<script src="/static/js/v4_equity_chart.js"></script>\n'
            '<script src="/static/js/market_history_chart.js"></script>'
        )
        if marker in html and "/static/js/v4_equity_chart.js" not in html:
            response.set_data(html.replace(marker, scripts + "\n" + marker, 1))
    return response


V5_SYMBOLS = get_v5_symbols()
V5_SYMBOL_OPTIONS = get_v5_symbol_options()
DEFAULT_SYMBOL = "AAPL"


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def valid_member_credentials(username, password):
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
    """Return V4 state with stable dashboard-facing compatibility keys."""
    forward = dict(summarize_journal())
    portfolio = dict(get_portfolio_summary())

    forward["observations"] = forward.get("observation_count", 0)
    portfolio["open_positions"] = portfolio.get("open_position_count", 0)
    portfolio["top_five"] = forward.get("latest_top_five", [])

    starting_cash = float(portfolio.get("starting_cash") or 100000.0)
    equity = float(portfolio.get("equity") or starting_cash)
    portfolio["net_change"] = equity - starting_cash
    portfolio["net_change_pct"] = (
        (equity / starting_cash - 1.0) if starting_cash else 0.0
    )
    portfolio["top_five_details"] = [
        {
            "symbol": symbol,
            "company_name": get_v5_company_name(symbol),
        }
        for symbol in portfolio["top_five"]
    ]

    history = list(forward.get("equity_history", []))
    chart_history = [
        {
            "timestamp": forward.get("start_timestamp"),
            "label": "Start",
            "equity": starting_cash,
            "synthetic_baseline": True,
        },
        *[
            {
                **row,
                "label": None,
                "synthetic_baseline": False,
            }
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
        chart_history[-1] = {
            **chart_history[-1],
            "label": "Current",
            "current_mark": True,
        }
    forward["chart_history"] = chart_history

    return {"forward": forward, "portfolio": portfolio}


def enrich_ranking_rows(rows):
    """Add presentation-only company names without changing V5 ranking data."""
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


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return redirect(url_for("dashboard" if session.get("authenticated") else "home"))

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if valid_member_credentials(username, password):
        session.clear()
        session.permanent = True
        session["authenticated"] = True
        session["username"] = username
        return redirect(url_for("dashboard"))

    return render_template(
        "landing.html",
        authenticated=False,
        login_error="Invalid username or password.",
    ), 401


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
            row["display_price"] = (
                live["reference_price"] if live["available"] else market["close"]
            )
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
    return jsonify({
        "stock": build_stock_dashboard(symbol),
        "recent_prices": get_recent_prices(symbol, limit=60),
    })


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


@app.route("/api/paper-portfolio")
@login_required
def api_paper_portfolio():
    return jsonify(get_portfolio_summary())


@app.route("/api/v4-forward")
@login_required
def api_v4_forward():
    return jsonify(build_v4_dashboard_payload())


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
