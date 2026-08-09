"""
Stock Market AI Platform presentation layer.

Primary detailed dashboard:
    User-selected symbol

Additional analytics:
    Top 10 stock/model universe
"""

import sys

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

sys.path.append("data-ingestion")

from webapp.services.market_service import (
    get_market_summary,
    get_recent_prices,
)

from webapp.services.prediction_service import (
    get_latest_prediction,
)


app = Flask(__name__)


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


def build_stock_dashboard(symbol):
    """Build combined market and model data for one symbol."""

    market = get_market_summary(symbol)
    prediction = get_latest_prediction(symbol)

    return {
        "symbol": symbol,
        "timestamp": market["timestamp"],
        "close": market["close"],
        "price_change": market["price_change"],
        "price_change_pct": market["price_change_pct"],
        "rsi_14": market["rsi_14"],
        "sma_20": market["sma_20"],
        "sma_50": market["sma_50"],
        "sma_200": market["sma_200"],
        "volatility_20d": market["volatility_20d"],
        "volume_ratio": market["volume_ratio"],
        "prediction": prediction["prediction"],
        "probability_up": prediction["probability_up"],
        "probability_down": prediction["probability_down"],
        "output_probability": prediction["confidence"],
        "accuracy": prediction["accuracy"],
        "majority_baseline": prediction["majority_baseline"],
        "precision": prediction["precision"],
        "recall": prediction["recall"],
        "f1": prediction["f1"],
    }


@app.route("/")
def index():
    """Render selected symbol detail plus Top 10 analytics."""

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
                "index",
                symbol="AAPL",
            )
        )

    market = get_market_summary(
        selected_symbol
    )

    prediction = get_latest_prediction(
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

    return render_template(
        "index.html",
        market=market,
        prediction=prediction,
        recent_prices=recent_prices,
        stocks=stocks,
        selected_symbol=selected_symbol,
        top_symbols=TOP_SYMBOLS,
        stock_count=len(stocks),
    )


@app.route("/api/stocks")
def api_stocks():
    """Return Top 10 stock/model data."""

    stocks = [
        build_stock_dashboard(symbol)
        for symbol in TOP_SYMBOLS
    ]

    return jsonify(stocks)


@app.route("/api/prices/<symbol>")
def api_prices(symbol):
    """Return recent price history for one symbol."""

    symbol = symbol.upper()

    if symbol not in TOP_SYMBOLS:
        return jsonify(
            {
                "error": "unsupported symbol"
            }
        ), 404

    return jsonify(
        get_recent_prices(
            symbol,
            limit=60,
        )
    )


@app.route("/health")
def health():

    return jsonify(
        {
            "status": "healthy",
            "service":
                "stock-market-ai-platform",
            "dashboard_symbols":
                len(TOP_SYMBOLS),
        }
    )


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
    )
