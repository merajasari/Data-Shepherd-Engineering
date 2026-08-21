"""PySpark implementation of the stock Gold-to-Feature transformation.

This module intentionally runs beside the Pandas implementation in
feature_transform.py. It does not replace or modify existing feature datasets.
"""

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F


def _ordered_window():
    return Window.partitionBy("symbol").orderBy("timestamp")


def _rolling_window(days: int):
    return (
        Window.partitionBy("symbol")
        .orderBy("timestamp")
        .rowsBetween(-(days - 1), 0)
    )


def _pct_change(column: str, days: int):
    previous = F.lag(column, days).over(_ordered_window())
    return F.col(column) / previous - F.lit(1.0)


def _complete_rolling(expression, source_column: str, days: int):
    window = _rolling_window(days)
    observed = F.count(F.col(source_column)).over(window)
    return F.when(observed == days, expression.over(window))


def transform_to_features_spark(df: DataFrame) -> DataFrame:
    """Transform Gold stock rows into the existing ML-ready feature contract."""

    order = _ordered_window()

    result = df
    for days in (2, 3, 5, 10, 20, 60):
        result = result.withColumn(
            f"return_{days}d",
            _pct_change("close", days),
        )

    result = (
        result
        .withColumn("price_vs_sma_7", F.col("close") / F.col("sma_7") - 1)
        .withColumn("price_vs_sma_20", F.col("close") / F.col("sma_20") - 1)
        .withColumn("price_vs_sma_50", F.col("close") / F.col("sma_50") - 1)
        .withColumn("price_vs_sma_200", F.col("close") / F.col("sma_200") - 1)
        .withColumn("sma_7_vs_sma_20", F.col("sma_7") / F.col("sma_20") - 1)
        .withColumn("sma_20_vs_sma_50", F.col("sma_20") / F.col("sma_50") - 1)
        .withColumn("sma_50_vs_sma_200", F.col("sma_50") / F.col("sma_200") - 1)
        .withColumn(
            "intraday_range",
            (F.col("high") - F.col("low")) / F.col("close"),
        )
        .withColumn(
            "open_close_range",
            (F.col("close") - F.col("open")) / F.col("open"),
        )
        .withColumn("volume_ratio", F.col("volume") / F.col("volume_sma_20"))
        .withColumn("volume_change_5d", _pct_change("volume", 5))
    )

    result = (
        result
        .withColumn(
            "volatility_5d",
            _complete_rolling(F.stddev_samp("daily_return"), "daily_return", 5),
        )
        .withColumn(
            "volatility_20d",
            _complete_rolling(F.stddev_samp("daily_return"), "daily_return", 20),
        )
        .withColumn(
            "volatility_ratio_5_20",
            F.col("volatility_5d") / F.col("volatility_20d"),
        )
        .withColumn("trend_20_50", F.col("sma_20") / F.col("sma_50") - 1)
        .withColumn("trend_50_200", F.col("sma_50") / F.col("sma_200") - 1)
    )

    high_window = _rolling_window(20)
    low_window = _rolling_window(20)
    high_count = F.count(F.col("high")).over(high_window)
    low_count = F.count(F.col("low")).over(low_window)

    result = (
        result
        .withColumn(
            "_rolling_high_20",
            F.when(high_count == 20, F.max("high").over(high_window)),
        )
        .withColumn(
            "_rolling_low_20",
            F.when(low_count == 20, F.min("low").over(low_window)),
        )
        .withColumn(
            "distance_from_20d_high",
            F.col("close") / F.col("_rolling_high_20") - 1,
        )
        .withColumn(
            "distance_from_20d_low",
            F.col("close") / F.col("_rolling_low_20") - 1,
        )
    )

    delta = F.col("close") - F.lag("close", 1).over(order)
    result = (
        result
        .withColumn(
            "_gain",
            F.when(delta.isNull(), F.lit(None).cast("double")).otherwise(
                F.greatest(delta, F.lit(0.0))
            ),
        )
        .withColumn(
            "_loss",
            F.when(delta.isNull(), F.lit(None).cast("double")).otherwise(
                -F.least(delta, F.lit(0.0))
            ),
        )
    )

    rsi_window = _rolling_window(14)
    gain_count = F.count(F.col("_gain")).over(rsi_window)
    loss_count = F.count(F.col("_loss")).over(rsi_window)
    avg_gain = F.when(gain_count == 14, F.avg("_gain").over(rsi_window))
    avg_loss = F.when(loss_count == 14, F.avg("_loss").over(rsi_window))
    complete_rsi_window = (gain_count == 14) & (loss_count == 14)
    rsi_14 = (
        F.when(~complete_rsi_window, F.lit(None).cast("double"))
        .when((avg_gain == 0) & (avg_loss == 0), F.lit(None).cast("double"))
        .when(avg_loss == 0, F.lit(100.0))
        .otherwise(100 - (100 / (1 + (avg_gain / avg_loss))))
    )

    result = (
        result
        .withColumn("rsi_14", rsi_14)
        .withColumn("rsi_centered", (F.col("rsi_14") - 50.0) / 50.0)
        .withColumn(
            "momentum_10d",
            F.col("close") - F.lag("close", 10).over(order),
        )
        .withColumn(
            "forward_return_5d",
            F.lead("close", 5).over(order) / F.col("close") - 1,
        )
        .withColumn(
            "target_up_5d",
            F.when(
                F.col("forward_return_5d").isNotNull(),
                (F.col("forward_return_5d") > 0).cast("byte"),
            ).cast("byte"),
        )
        .withColumn(
            "target_trade_5d",
            F.when(
                F.col("forward_return_5d").isNotNull(),
                (F.col("forward_return_5d") > 0.01).cast("byte"),
            ).cast("byte"),
        )
        .drop(
            "_rolling_high_20",
            "_rolling_low_20",
            "_gain",
            "_loss",
        )
    )

    return result
