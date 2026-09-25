"""Shared Crypto V17 Direct Market State research package.

V17 is a separately named successor to rejected V16.

V16 attempted to regress broad-market seven-day median path utility and then
threshold the regression at zero. It strongly under-called RISK_ON. V17 keeps
the exact same market-state labels, 18 point-in-time features, walk-forward
purge, future holdout, frozen V15 ranking engine, and later portfolio gates,
but learns the market state directly with a balanced binary classifier.
"""
