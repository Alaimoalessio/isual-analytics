"""
conftest.py — Fixture condivise tra tutti i test ISUAL.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import pytest

# Rende importabili sia il package root che il package oop
_root = Path(__file__).resolve().parent.parent
for _p in (str(_root / "oop"), str(_root)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def date_range():
    end   = datetime(2024, 6, 1)
    start = end - timedelta(days=30)
    return start, end


@pytest.fixture
def df_overview():
    return pd.DataFrame([{
        "total_reach":       500_000,
        "total_impressions": 1_200_000,
        "total_engagement":  25_000,
        "total_posts":       40,
        "active_partners":   8,
        "total_partners":    10,
    }])


@pytest.fixture
def df_amplification():
    return pd.DataFrame([
        {"source": "brand",   "reach": 200_000},
        {"source": "partner", "reach": 300_000},
    ])


@pytest.fixture
def df_adoption():
    return pd.DataFrame([{"active_partners": 8, "total_partners": 10}])


@pytest.fixture
def df_content():
    return pd.DataFrame([
        {"post_id": f"p{i}", "title": f"Post {i}", "channel": "instagram",
         "reach": (5 - i) * 10_000, "impressions": (5 - i) * 20_000,
         "engagement": (5 - i) * 500, "n_partners": i, "published_at": datetime(2024, 5, i + 1)}
        for i in range(5)
    ])


@pytest.fixture
def df_partners():
    return pd.DataFrame([
        {"partner_id": f"id{i}", "partner_name": f"Partner {i}",
         "reach": (4 - i) * 50_000, "impressions": (4 - i) * 100_000,
         "engagement": (4 - i) * 2_000, "posts": (4 - i) * 3,
         "first_pub": datetime(2024, 5, 1), "last_pub": datetime(2024, 5, 30)}
        for i in range(4)
    ])


@pytest.fixture
def df_channels():
    return pd.DataFrame([
        {"channel": "instagram", "reach": 300_000, "impressions": 700_000,
         "engagement": 15_000, "posts": 20},
        {"channel": "facebook",  "reach": 120_000, "impressions": 300_000,
         "engagement": 6_000,  "posts": 12},
        {"channel": "linkedin",  "reach": 80_000,  "impressions": 200_000,
         "engagement": 4_000,  "posts": 8},
    ])


@pytest.fixture
def df_trend():
    weeks = pd.date_range("2024-05-06", periods=4, freq="W")
    return pd.DataFrame({
        "week":        weeks,
        "reach":       [100_000, 120_000, 140_000, 140_000],
        "impressions": [250_000, 290_000, 320_000, 340_000],
        "engagement":  [5_000,   6_000,   7_000,   7_000],
    })
