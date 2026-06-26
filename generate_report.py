import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

_root = Path(__file__).resolve().parent
_root_str = str(_root)
_oop_str  = str(_root / "oop")
# Rimuove eventuali copie preesistenti e forza l'ordine: [root, oop/, ...]
# Necessario perché Python inserisce già la dir dello script in sys.path.
for _p in (_root_str, _oop_str):
    while _p in sys.path:
        sys.path.remove(_p)
sys.path[0:0] = [_root_str, _oop_str]

from data_source import IsualDataSource      # noqa: E402
from kpi_engine import IsualKPIEngine        # noqa: E402
from chart_engine import IsualChartEngine    # noqa: E402
from report_builder import IsualReportBuilder  # noqa: E402
from config import DB_CONFIG, DATE_START, DATE_END, BRAND_ID, COLORS, OUTPUT_PATH  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ISUAL Analytics PDF Report (OOP)")
    parser.add_argument("--days",     type=int, default=None, help="Override periodo giorni")
    parser.add_argument("--brand-id", type=str, default=None, dest="brand_id",
                        help="Override brand UUID")
    parser.add_argument("--out",      type=str, default=None, help="Override output path PDF")
    return parser.parse_args()


def main() -> str:
    args = parse_args()

    date_start, date_end = DATE_START, DATE_END
    if args.days:
        date_end   = datetime.utcnow()
        date_start = date_end - timedelta(days=args.days)

    brand_id    = args.brand_id if args.brand_id else BRAND_ID
    output_path = args.out      if args.out      else OUTPUT_PATH

    print(f"[ISUAL Report OOP] Periodo: {date_start.date()} → {date_end.date()}")
    print(f"[ISUAL Report OOP] Brand filter: {brand_id or 'tutti'}")

    source  = IsualDataSource(DB_CONFIG, date_start, date_end, brand_id)
    kpis    = IsualKPIEngine(source)
    charts  = IsualChartEngine(COLORS)
    builder = IsualReportBuilder(kpis, charts, template_dir="templates")

    return builder.build(output_path)


if __name__ == "__main__":
    main()
