"""Faisal Barkat Khorasi module: weekly activity features and EWMA trend baselines.

The package is deliberately generic. :mod:`signals.series` knows nothing about
GitHub; it models *any* weekly numeric series with explicit missing-week
semantics, and :mod:`signals.ewma` scores any such series. GitHub activity, job
counts by role family, and distinct-source news counts are three callers of the
same machinery.
"""

FEATURE_VERSION = "signals/0.1.0"

__all__ = ["FEATURE_VERSION"]
