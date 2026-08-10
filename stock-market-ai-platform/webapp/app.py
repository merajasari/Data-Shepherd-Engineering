"""
Stock Market AI Platform presentation layer.

Public layer:
- Data Shepherd Engineering landing page
- Member authentication

Protected member layer:
- Stock Market AI dashboard
- Historical / EOD market analytics
- Machine-learning inference
- Live Tiingo IEX quote data
- Top 10 stock comparison
- 26-stock future trend forecasting
"""

import os
import sys

from datetime import timedelta
from functools import wraps

from dotenv import load_dotenv

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from werkzeug.security import (
    check_password_hash,
)


load_dotenv()

sys.path.append("data-ingestion")

from symbols import SYMBOLS

from webapp.services.forecast_service import (
    build_market_forecast,
)

from webapp.services.live_market_service import (
    get_all_live_quotes,
    get_live_quote,
)

from webapp.services.market_service import (
    get_market_summary,
    get_recent_prices,
)

from webapp.services.prediction_service import (
    get_latest_prediction,
)


app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY"
)

if not app.secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY is not configured"
    )


app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(
        hours=12
    ),
)


TOP_SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AVGO",
    "AMD",
    "ORCL",
]


def login_required(view):
    """
    Require an authenticated member session.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):

        if not session.get(
            "authenticated"
        ):
            return redirect(
                url_for("home")
            )

        return view(
            *args,
            **kwargs
        )

    return wrapped


def valid_member_credentials(
    username,
    password,
):
    """
    Validate username and password
    against environment configuration.
    """

    configured_username = (
        os.environ.get(
            "MEMBER_USERNAME",
            "",
        )
    )

    password_hash = (
        os.environ.get(
            "MEMBER_PASSWORD_HASH",
            "",
        )
    )

    if (
        not configured_username
        or not password_hash
    ):
        return False

    if username != configured_username:
        return False

    return check_password_hash(
        password_hash,
        password,
    )


def build_stock_dashboard(symbol):
    """
    Build combined market, prediction, and live data
    for one dashboard symbol.
    """

    market = get_market_summary(
        symbol
    )

    prediction = get_latest_prediction(
        symbol
    )

    live = get_live_quote(
        symbol
    )

    display_price = (
        live["reference_price"]
        if live["available"]
        else market["close"]
    )

    return {
        "symbol":
            symbol,

        "timestamp":
            market["timestamp"],

        "close":
            market["close"],

        "display_price":
            display_price,

        "live_available":
            live["available"],

        "live_price":
            live["reference_price"],

        "live_timestamp":
            live["timestamp"],

        "live_received_at":
            live["received_at"],

        "price_change":
            market["price_change"],

        "price_change_pct":
            market["price_change_pct"],

        "rsi_14":
            market["rsi_14"],

        "sma_20":
            market["sma_20"],

        "sma_50":
            market["sma_50"],

        "sma_200":
            market["sma_200"],

        "volatility_20d":
            market["volatility_20d"],

        "volume_ratio":
            market["volume_ratio"],

        "prediction":
            prediction["prediction"],

        "probability_up":
            prediction["probability_up"],

        "probability_down":
            prediction["probability_down"],

        "output_probability":
            prediction["confidence"],

        "accuracy":
            prediction["accuracy"],

        "majority_baseline":
            prediction[
                "majority_baseline"
            ],

        "precision":
            prediction["precision"],

        "recall":
            prediction["recall"],

        "f1":
            prediction["f1"],
    }


@app.route("/")
def home():
    """
    Public Data Shepherd Engineering landing page.
    """

    return render_template(
        "landing.html",
        authenticated=session.get(
            "authenticated",
            False,
        ),
        login_error=None,
    )


@app.route(
    "/login",
    methods=["GET", "POST"],
)
def login():
    """
    Authenticate a member and create
    a secure Flask session.
    """

    if request.method == "GET":

        if session.get(
            "authenticated"
        ):
            return redirect(
                url_for(
                    "dashboard"
                )
            )

        return redirect(
            url_for("home")
        )

    username = (
        request.form.get(
            "username",
            "",
        )
        .strip()
    )

    password = (
        request.form.get(
            "password",
            ""
        )
    )

    if valid_member_credentials(
        username,
        password,
    ):
        session.clear()

        session.permanent = True

        session["authenticated"] = True

        session["username"] = username

        return redirect(
            url_for(
                "dashboard"
            )
        )

    return render_template(
        "landing.html",
        authenticated=False,
        login_error=(
            "Invalid username or password."
        ),
    ), 401


@app.route("/logout")
def logout():
    """
    End the current member session.
    """

    session.clear()

    return redirect(
        url_for("home")
    )


@app.route("/dashboard")
@login_required
def dashboard():
    """
    Render selected-stock detail plus
    Top 10 analytics.
    """

    selected_symbol = (
        request.args.get(
            "symbol",
            "AAPL",
        )
        .upper()
        .strip()
    )

    if selected_symbol not in TOP_SYMBOLS:
        return redirect(
            url_for(
                "dashboard",
                symbol="AAPL",
            )
        )

    market = get_market_summary(
        selected_symbol
    )

    prediction = get_latest_prediction(
        selected_symbol
    )

    live = get_live_quote(
        selected_symbol
    )

    recent_prices = get_recent_prices(
        selected_symbol,
        limit=60,
    )

    stocks = []

    for symbol in TOP_SYMBOLS:
        try:
            stocks.append(
                build_stock_dashboard(
                    symbol
                )
            )

        except Exception as exc:
            print(
                f"[DASHBOARD ERROR] "
                f"{symbol}: {exc}"
            )

    display_price = (
        live["reference_price"]
        if live["available"]
        else market["close"]
    )

    price_source = (
        "LIVE IEX"
        if live["available"]
        else "LATEST EOD"
    )

    return render_template(
        "index.html",

        market=market,

        prediction=prediction,

        live=live,

        display_price=display_price,

        price_source=price_source,

        recent_prices=recent_prices,

        stocks=stocks,

        selected_symbol=
            selected_symbol,

        top_symbols=
            TOP_SYMBOLS,

        stock_count=
            len(stocks),

        forecast_symbol_count=
            len(SYMBOLS),
    )


@app.route("/api/stocks")
@login_required
def api_stocks():
    """
    Return Top 10 stock/model/live data.
    """

    stocks = [
        build_stock_dashboard(
            symbol
        )
        for symbol in TOP_SYMBOLS
    ]

    return jsonify(
        stocks
    )


@app.route(
    "/api/prices/<symbol>"
)
@login_required
def api_prices(symbol):
    """
    Return recent historical price data.
    """

    symbol = symbol.upper()

    if symbol not in TOP_SYMBOLS:
        return jsonify(
            {
                "error":
                    "unsupported symbol"
            }
        ), 404

    return jsonify(
        get_recent_prices(
            symbol,
            limit=60,
        )
    )


@app.route(
    "/api/live/<symbol>"
)
@login_required
def api_live_quote(symbol):
    """
    Return latest live quote
    for one symbol.
    """

    symbol = symbol.upper()

    return jsonify(
        get_live_quote(
            symbol
        )
    )


@app.route(
    "/api/live"
)
@login_required
def api_live_quotes():
    """
    Return all currently cached live quotes.
    """

    return jsonify(
        get_all_live_quotes()
    )


@app.route(
    "/api/forecast"
)
@login_required
def api_forecast():
    """
    Return 5-trading-day directional forecasts
    for the complete 26-stock universe.
    """

    forecasts = build_market_forecast(
        SYMBOLS
    )

    valid_count = len(
        [
            forecast
            for forecast in forecasts
            if "forecast_score"
            in forecast
        ]
    )

    return jsonify(
        {
            "horizon_days":
                5,

            "symbol_count":
                len(SYMBOLS),

            "available_count":
                valid_count,

            "forecasts":
                forecasts,
        }
    )


@app.route("/health")
def health():
    """
    Return public application health state.
    """

    live_state = (
        get_all_live_quotes()
    )

    return jsonify(
        {
            "status":
                "healthy",

            "service":
                "stock-market-ai-platform",

            "dashboard_symbols":
                len(TOP_SYMBOLS),

            "forecast_symbols":
                len(SYMBOLS),

            "live_symbols":
                live_state[
                    "symbol_count"
                ],

            "live_cache_updated_at":
                live_state[
                    "updated_at"
                ],
        }
    )


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
    )
