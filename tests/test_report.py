"""
test_report.py — Test per IsualReportBuilder.

Verifica che il builder produca un PDF non vuoto dato un set di KPI mock,
senza toccare il DB reale.
"""

import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

import pytest

_root = Path(__file__).resolve().parent.parent
for _p in (str(_root / "oop"), str(_root)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kpi_engine import IsualKPIEngine
from chart_engine import IsualChartEngine
from report_builder import IsualReportBuilder
from data_source import IsualDataSource


MOCK_KPI = {
    "period_label":      "Ultimi 30 giorni",
    "date_range":        "01/05/2024 – 01/06/2024",
    "total_reach":       "500.0K",
    "total_impressions": "1.2M",
    "total_engagement":  "25.0K",
    "total_posts":       "40",
    "engagement_rate":   "5.0%",
    "frequency":         "2.4x",
    "amplification":     "2.5x",
    "adoption_pct":      "80%",
    "active_partners":   "8",
    "total_partners":    "10",
    "er_raw":            5.0,
    "amp_raw":           2.5,
    "adoption_raw":      80.0,
}

COLORS = {
    "blue_primary":   "#3B5BDB",
    "blue_dark":      "#1A1A2E",
    "red_brand":      "#C0392B",
    "green_positive": "#2F9E44",
    "orange_warning": "#F08C00",
    "red_alert":      "#E03131",
    "bg_page":        "#F1F3F5",
    "bg_card":        "#FFFFFF",
    "text_primary":   "#1A1A2E",
    "text_secondary": "#6C757D",
}


def _make_builder(df_content, df_partners, df_channels, df_trend,
                  df_overview, df_amplification, df_adoption):
    """Costruisce un IsualReportBuilder con tutti i layer mockati."""
    mock_source = MagicMock(spec=IsualDataSource)
    mock_source.fetch_weekly_trend.return_value         = df_trend
    mock_source.fetch_content_performance.return_value  = df_content
    mock_source.fetch_partner_stats.return_value        = df_partners
    mock_source.fetch_channel_breakdown.return_value    = df_channels
    mock_source.fetch_overview.return_value             = df_overview
    mock_source.fetch_amplification.return_value        = df_amplification
    mock_source.fetch_adoption.return_value             = df_adoption
    mock_source.date_start  = datetime(2024, 5, 1)
    mock_source.date_end    = datetime(2024, 6, 1)
    mock_source.period_days = 31

    kpi_engine   = IsualKPIEngine(mock_source)
    chart_engine = IsualChartEngine(COLORS)

    template_dir = str(_root / "oop" / "templates")
    return IsualReportBuilder(kpi_engine, chart_engine, template_dir=template_dir)


def test_pdf_is_generated(df_overview, df_amplification, df_adoption,
                          df_content, df_partners, df_channels, df_trend):
    """Il builder deve creare un file PDF sul disco."""
    builder = _make_builder(df_content, df_partners, df_channels, df_trend,
                            df_overview, df_amplification, df_adoption)
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "test_report.pdf")
        builder.build(out)
        assert os.path.exists(out)


def test_pdf_is_not_empty(df_overview, df_amplification, df_adoption,
                          df_content, df_partners, df_channels, df_trend):
    """Il PDF generato non deve essere un file vuoto (minimo 1 KB)."""
    builder = _make_builder(df_content, df_partners, df_channels, df_trend,
                            df_overview, df_amplification, df_adoption)
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "test_report.pdf")
        builder.build(out)
        size = os.path.getsize(out)
        assert size > 1_024, f"PDF troppo piccolo: {size} byte"


def test_pdf_starts_with_pdf_header(df_overview, df_amplification, df_adoption,
                                    df_content, df_partners, df_channels, df_trend):
    """Il file deve essere un PDF valido (magic bytes %PDF)."""
    builder = _make_builder(df_content, df_partners, df_channels, df_trend,
                            df_overview, df_amplification, df_adoption)
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "test_report.pdf")
        builder.build(out)
        with open(out, "rb") as f:
            header = f.read(4)
        assert header == b"%PDF", f"Magic bytes errati: {header}"


def test_output_dir_created_automatically(df_overview, df_amplification, df_adoption,
                                          df_content, df_partners, df_channels, df_trend):
    """Il builder deve creare la directory di output se non esiste."""
    builder = _make_builder(df_content, df_partners, df_channels, df_trend,
                            df_overview, df_amplification, df_adoption)
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "subdir", "nested", "report.pdf")
        builder.build(out)
        assert os.path.exists(out)


def test_build_returns_output_path(df_overview, df_amplification, df_adoption,
                                   df_content, df_partners, df_channels, df_trend):
    """build() deve restituire il percorso del PDF generato."""
    builder = _make_builder(df_content, df_partners, df_channels, df_trend,
                            df_overview, df_amplification, df_adoption)
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "report.pdf")
        result = builder.build(out)
        assert result == out
