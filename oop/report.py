"""
report.py — Entry point della versione OOP del report ISUAL.

Compone le classi del package e genera il PDF. Dimostra la pulizia
dell'approccio a oggetti: poche righe leggibili e parametrizzabili.

Uso:
    python oop/report.py
    python oop/report.py --days 90
    python oop/report.py --brand <uuid>
    python oop/report.py --out /percorso/report.pdf
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Assicura che i moduli del package siano importabili anche eseguendo
# `python oop/report.py` dalla root del progetto.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_source import IsualDataSource
from kpi_engine import IsualKPIEngine
from chart_engine import IsualChartEngine
from report_builder import IsualReportBuilder
from config import DB_CONFIG, DATE_START, DATE_END, BRAND_ID, COLORS, OUTPUT_PATH


def parse_args() -> argparse.Namespace:
    """Definisce e legge gli argomenti CLI (override opzionali)."""
    parser = argparse.ArgumentParser(description="ISUAL Analytics PDF Report (OOP)")
    parser.add_argument("--days", type=int, default=None, help="Override periodo giorni")
    parser.add_argument("--brand", type=str, default=None, help="Override brand UUID")
    parser.add_argument("--out", type=str, default=None, help="Override output path PDF")
    return parser.parse_args()


def main() -> str:
    """Costruisce il report applicando eventuali override CLI."""
    args = parse_args()

    # Parametri di base dal config, con override da CLI.
    date_start, date_end = DATE_START, DATE_END
    if args.days:
        date_end = datetime.utcnow()
        date_start = date_end - timedelta(days=args.days)

    brand_id = args.brand if args.brand else BRAND_ID
    output_path = args.out if args.out else OUTPUT_PATH

    print(f"[ISUAL Report OOP] Periodo: {date_start.date()} → {date_end.date()}")
    print(f"[ISUAL Report OOP] Brand filter: {brand_id or 'tutti'}")

    # Composizione delle classi: ogni oggetto ha una singola responsabilità.
    source = IsualDataSource(DB_CONFIG, date_start, date_end, brand_id)
    kpis = IsualKPIEngine(source)
    charts = IsualChartEngine(COLORS)
    builder = IsualReportBuilder(kpis, charts, template_dir="templates")

    return builder.build(output_path)


if __name__ == "__main__":
    main()
