"""
test_kpi.py — Unit test per IsualKPIEngine.

Tutti i test usano DataFrame fittizi: nessuna connessione al DB reale.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

_root = Path(__file__).resolve().parent.parent
for _p in (str(_root / "oop"), str(_root)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kpi_engine import IsualKPIEngine
from data_source import IsualDataSource


def _make_engine(df_overview, df_amplification, df_adoption,
                 df_content=None, df_partners=None, df_channels=None,
                 df_trend=None, date_range=None):
    """Costruisce un IsualKPIEngine con sorgente dati mockata."""
    mock_source = MagicMock(spec=IsualDataSource)
    mock_source.fetch_overview.return_value        = df_overview
    mock_source.fetch_amplification.return_value   = df_amplification
    mock_source.fetch_adoption.return_value        = df_adoption
    if df_content  is not None: mock_source.fetch_content_performance.return_value = df_content
    if df_partners is not None: mock_source.fetch_partner_stats.return_value       = df_partners
    if df_channels is not None: mock_source.fetch_channel_breakdown.return_value   = df_channels
    if df_trend    is not None: mock_source.fetch_weekly_trend.return_value        = df_trend

    if date_range:
        start, end = date_range
        mock_source.date_start  = start
        mock_source.date_end    = end
        mock_source.period_days = (end - start).days
    else:
        mock_source.date_start  = datetime(2024, 5, 1)
        mock_source.date_end    = datetime(2024, 6, 1)
        mock_source.period_days = 31

    return IsualKPIEngine(mock_source)


# ── Test calc_overview ────────────────────────────────────────────────────────

def test_overview_engagement_rate(df_overview, df_amplification, df_adoption):
    eng = _make_engine(df_overview, df_amplification, df_adoption)
    result = eng.calc_overview()
    # ER = 25_000 / 500_000 * 100 = 5.0%
    assert result["engagement_rate"] == "5.0%"


def test_overview_amplification_factor(df_overview, df_amplification, df_adoption):
    eng = _make_engine(df_overview, df_amplification, df_adoption)
    result = eng.calc_overview()
    # amp = 500_000 / 200_000 = 2.5x
    assert result["amplification"] == "2.5x"


def test_overview_adoption_pct(df_overview, df_amplification, df_adoption):
    eng = _make_engine(df_overview, df_amplification, df_adoption)
    result = eng.calc_overview()
    assert result["adoption_pct"] == "80%"


def test_overview_total_reach_formatted(df_overview, df_amplification, df_adoption):
    eng = _make_engine(df_overview, df_amplification, df_adoption)
    result = eng.calc_overview()
    assert result["total_reach"] == "500.0K"


def test_overview_empty_dataframes():
    """Con DataFrame vuoti deve restituire zero senza sollevare eccezioni."""
    empty = pd.DataFrame()
    mock_source = MagicMock(spec=IsualDataSource)
    mock_source.fetch_overview.return_value      = empty
    mock_source.fetch_amplification.return_value = empty
    mock_source.fetch_adoption.return_value      = empty
    mock_source.date_start  = datetime(2024, 5, 1)
    mock_source.date_end    = datetime(2024, 6, 1)
    mock_source.period_days = 31

    eng    = IsualKPIEngine(mock_source)
    result = eng.calc_overview()
    assert result["engagement_rate"] == "0.0%"
    assert result["amplification"]   == "0.0x"


# ── Test calc_content_score ───────────────────────────────────────────────────

def test_content_score_top_n(df_overview, df_amplification, df_adoption, df_content):
    eng = _make_engine(df_overview, df_amplification, df_adoption)
    scored = eng.calc_content_score(df_content, top_n=3)
    assert len(scored) == 3


def test_content_score_ordering(df_overview, df_amplification, df_adoption, df_content):
    eng = _make_engine(df_overview, df_amplification, df_adoption)
    scored = eng.calc_content_score(df_content, top_n=5)
    scores = scored["content_score"].tolist()
    assert scores == sorted(scores, reverse=True)


def test_content_score_empty(df_overview, df_amplification, df_adoption):
    eng = _make_engine(df_overview, df_amplification, df_adoption)
    result = eng.calc_content_score(pd.DataFrame(), top_n=5)
    assert result.empty


# ── Test calc_partner_health ──────────────────────────────────────────────────

def test_partner_health_scores_bounded(df_overview, df_amplification, df_adoption, df_partners):
    eng = _make_engine(df_overview, df_amplification, df_adoption)
    result = eng.calc_partner_health(df_partners)
    assert result["health_score"].between(0, 100).all()


def test_partner_health_classification_values(df_overview, df_amplification, df_adoption, df_partners):
    eng = _make_engine(df_overview, df_amplification, df_adoption)
    result = eng.calc_partner_health(df_partners)
    valid = {"Top Performer", "Amplifier", "Quality Niche", "Weak"}
    assert set(result["classification"]).issubset(valid)


def test_partner_health_label_values(df_overview, df_amplification, df_adoption, df_partners):
    eng = _make_engine(df_overview, df_amplification, df_adoption)
    result = eng.calc_partner_health(df_partners)
    valid = {"VIP", "Active", "ALERT"}
    assert set(result["health_label"]).issubset(valid)


# ── Test calc_channel_breakdown ───────────────────────────────────────────────

def test_channel_breakdown_er_positive(df_overview, df_amplification, df_adoption, df_channels):
    eng = _make_engine(df_overview, df_amplification, df_adoption)
    result = eng.calc_channel_breakdown(df_channels)
    assert (result["er"] >= 0).all()


def test_channel_breakdown_channel_upper(df_overview, df_amplification, df_adoption, df_channels):
    eng = _make_engine(df_overview, df_amplification, df_adoption)
    result = eng.calc_channel_breakdown(df_channels)
    assert "channel_upper" in result.columns


# ── Test helper _fmt_number ───────────────────────────────────────────────────

def test_fmt_number_millions():
    assert IsualKPIEngine._fmt_number(1_500_000) == "1.5M"


def test_fmt_number_thousands():
    assert IsualKPIEngine._fmt_number(2_500) == "2.5K"


def test_fmt_number_small():
    assert IsualKPIEngine._fmt_number(42) == "42"


def test_fmt_number_none():
    assert IsualKPIEngine._fmt_number(None) == "N/D"
