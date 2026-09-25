"""Shared Crypto V16 Risk-Gated Rank research package.

V16 is a separately named successor to rejected V15.

V15's cross-sectional ranker passed all predictive gates, but its always-deployed
60%-crypto portfolio failed stability, BTC-relative, drawdown, concentration,
and consistency gates. V16 preserves that ranker as a frozen selection engine
and adds a separately learned broad-market risk gate that decides whether the
ranker is deployed or the portfolio remains in CASH.
"""
