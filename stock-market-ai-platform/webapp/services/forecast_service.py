"""
Forecast service for the Stock Market AI Platform.

Transforms each symbol's existing 5-trading-day direction
prediction into a normalized trend score.

This is a directional model forecast, not a future price target.
"""

from webapp.services.prediction_service import (
    get_latest_prediction,
)


def build_forecast(symbol: str) -> dict:
    """
    Build the 5-day directional forecast for one symbol.

    Score range:
        -100 = strongly bearish
           0 = neutral
        +100 = strongly bullish
    """

    symbol = symbol.upper().strip()

    prediction = get_latest_prediction(
        symbol
    )

    probability_up = float(
        prediction["probability_up"]
    )

    probability_down = float(
        prediction["probability_down"]
    )

    forecast_score = (
        probability_up
        - probability_down
    ) * 100.0

    if forecast_score >= 50:
        trend_strength = "STRONG BULLISH"

    elif forecast_score >= 20:
        trend_strength = "BULLISH"

    elif forecast_score > -20:
        trend_strength = "NEUTRAL"

    elif forecast_score > -50:
        trend_strength = "BEARISH"

    else:
        trend_strength = "STRONG BEARISH"

    return {
        "symbol":
            symbol,

        "horizon_days":
            int(
                prediction.get(
                    "horizon_days",
                    5,
                )
            ),

        "prediction":
            prediction["prediction"],

        "probability_up":
            probability_up,

        "probability_down":
            probability_down,

        "confidence":
            float(
                prediction["confidence"]
            ),

        "forecast_score":
            round(
                forecast_score,
                2,
            ),

        "trend_strength":
            trend_strength,

        "accuracy":
            prediction.get(
                "accuracy"
            ),

        "majority_baseline":
            prediction.get(
                "majority_baseline"
            ),

        "model_type":
            prediction.get(
                "model_type"
            ),

        "prediction_timestamp":
            prediction.get(
                "timestamp"
            ),

        "reference_close":
            prediction.get(
                "close"
            ),
    }


def build_market_forecast(
    symbols,
) -> list:
    """
    Build forecasts for the complete configured stock universe.

    Individual symbol failures are returned as error records so one
    bad model cannot prevent the other forecasts from loading.
    """

    forecasts = []

    for symbol in symbols:

        try:
            forecasts.append(
                build_forecast(
                    symbol
                )
            )

        except Exception as exc:
            forecasts.append(
                {
                    "symbol":
                        symbol,

                    "error":
                        str(exc),

                    "available":
                        False,
                }
            )

    valid_forecasts = [
        forecast
        for forecast in forecasts
        if "forecast_score" in forecast
    ]

    failed_forecasts = [
        forecast
        for forecast in forecasts
        if "forecast_score" not in forecast
    ]

    valid_forecasts.sort(
        key=lambda forecast:
            forecast["forecast_score"],
        reverse=True,
    )

    return (
        valid_forecasts
        + failed_forecasts
    )
