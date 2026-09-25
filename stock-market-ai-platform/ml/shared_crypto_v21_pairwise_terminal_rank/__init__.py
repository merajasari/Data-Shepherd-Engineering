"""Shared Crypto V21 Pairwise Terminal Rank research package.

Offline research only. No brokerage orders, no paper-state mutation, and no
automatic promotion.

V21 is a materially different successor after V20 confirmed useful broad
cross-sectional ordering but failed to concentrate BTC-relative return in its
top-three selections.

V21 replaces scalar rank regression with pairwise learning. The classifier
learns which of two assets will have the higher exact seven-day BTC-relative
net terminal return, then aggregates pairwise win probabilities into an
asset-level ranking score.
"""
