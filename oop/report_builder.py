"""
report_builder.py — Orchestrazione e rendering del report.

Espone la classe :class:`IsualReportBuilder`, che mette insieme KPI e grafici,
renderizza il template Jinja2 e genera il PDF con WeasyPrint.
"""

from __future__ import annotations

import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS

from kpi_engine import IsualKPIEngine
from chart_engine import IsualChartEngine


class IsualReportBuilder:
    """
    Costruttore del report ISUAL: dai dati al PDF finale.

    Responsabilità:
        - recuperare i DataFrame tramite la sorgente dati del KPI engine;
        - calcolare KPI e tabelle, generare i grafici;
        - renderizzare il template Jinja2 e scrivere il PDF con WeasyPrint.
    """

    def __init__(
        self,
        kpi_engine: IsualKPIEngine,
        chart_engine: IsualChartEngine,
        template_dir: str = "templates",
    ) -> None:
        """
        Inizializza il builder.

        Args:
            kpi_engine: motore KPI (espone anche la sorgente dati).
            chart_engine: motore di generazione grafici.
            template_dir: cartella dei template. Se relativa, viene risolta
                rispetto alla directory di questo modulo (il package ``oop``),
                così il builder funziona indipendentemente dalla working dir.
        """
        self.kpi_engine: IsualKPIEngine = kpi_engine
        self.chart_engine: IsualChartEngine = chart_engine

        template_path = Path(template_dir)
        if not template_path.is_absolute():
            template_path = Path(__file__).resolve().parent / template_path
        self.template_dir: Path = template_path

    def build(self, output_path: str) -> str:
        """
        Esegue l'intera pipeline e genera il PDF.

        Args:
            output_path: percorso del PDF di output. Le cartelle mancanti
                vengono create automaticamente.

        Returns:
            Il percorso del PDF generato (``output_path``).
        """
        source = self.kpi_engine.datasource

        # ── 1. Fetch dati ──────────────────────────────────────────
        print("[1/4] Fetching dati dalla sorgente...")
        df_trend = source.fetch_weekly_trend()
        df_content = source.fetch_content_performance()
        df_partners = source.fetch_partner_stats()
        df_channels = source.fetch_channel_breakdown()

        # ── 2. Calcola KPI ─────────────────────────────────────────
        print("[2/4] Calcolando metriche...")
        kpi_data = self.kpi_engine.calc_overview()
        df_content_scored = self.kpi_engine.calc_content_score(df_content, top_n=5)
        df_partners_health = self.kpi_engine.calc_partner_health(df_partners)
        df_channels_calc = self.kpi_engine.calc_channel_breakdown(df_channels)

        # ── 3. Genera grafici ──────────────────────────────────────
        print("[3/4] Generando grafici...")
        trend_chart = self.chart_engine.trend_chart(df_trend)
        channel_chart = self.chart_engine.channel_bar_chart(df_channels_calc)

        # ── 4. Render HTML + PDF ───────────────────────────────────
        print("[4/4] Rendering template e generazione PDF...")
        content_rows = df_content_scored.to_dict("records")
        partner_rows = df_partners_health.to_dict("records")
        channel_rows = df_channels_calc.to_dict("records")

        env = Environment(loader=FileSystemLoader(str(self.template_dir)))
        template = env.get_template("report.html")

        html_content = template.render(
            kpi=kpi_data,
            trend_chart=trend_chart,
            channel_chart=channel_chart,
            content_rows=content_rows,
            partner_rows=partner_rows,
            channel_rows=channel_rows,
        )

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        HTML(string=html_content).write_pdf(
            output_path,
            stylesheets=[CSS(string="@page { size: A4; margin: 0; }")],
        )

        print(f"[✓] Report generato: {output_path}")
        return output_path
