"""
app.py — Dashboard Flask ISUAL (stack OOP).
"""

import os
import sys
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, render_template, Response
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
OOP_DIR = ROOT / "oop"
# ROOT deve precedere oop/ nel path: evita il circular import di oop/config.py
for _p in (str(OOP_DIR), str(ROOT)):
    if _p in sys.path:
        sys.path.remove(_p)
sys.path[0:0] = [str(ROOT), str(OOP_DIR)]

from data_source import IsualDataSource      # noqa: E402
from kpi_engine import IsualKPIEngine        # noqa: E402
from chart_engine import IsualChartEngine    # noqa: E402
from report_builder import IsualReportBuilder  # noqa: E402
from config import DB_CONFIG, COLORS         # noqa: E402

app = Flask(__name__)

OUTPUT_DIR = str(ROOT / "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Engine condiviso per i check di salute: creato una sola volta e riusato.
_health_engine = None


def _get_health_engine():
    """Restituisce l'engine SQLAlchemy (singleton) per db-status e health."""
    global _health_engine
    if _health_engine is None:
        end = datetime.utcnow()
        src = IsualDataSource(DB_CONFIG, end - timedelta(days=1), end)
        _health_engine = src._get_engine()
    return _health_engine


def _make_source(brand_id, start_date, end_date):
    """Crea un IsualDataSource con i parametri della richiesta."""
    return IsualDataSource(DB_CONFIG, start_date, end_date, brand_id)


def _get_params():
    brand_id = request.args.get('brand_id', default=None, type=str)
    if brand_id == 'all' or brand_id == '':
        brand_id = None
    days = request.args.get('days', default=30, type=int)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    return brand_id, days, start_date, end_date


@app.route('/')
def index():
    return render_template('dashboard.html')


@app.route('/api/db-status')
def api_db_status():
    try:
        import concurrent.futures

        engine = _get_health_engine()

        def ping_db():
            start_time = datetime.now()
            with engine.connect() as conn:
                conn.execute(text('SELECT 1'))
            return (datetime.now() - start_time).total_seconds() * 1000

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(ping_db)
            latency = future.result(timeout=5.0)

        return jsonify({"success": True, "status": "ok", "latency_ms": int(latency)})
    except concurrent.futures.TimeoutError:
        return jsonify({"success": False, "status": "error", "error": "Timeout"}), 504
    except Exception as e:
        return jsonify({"success": False, "status": "error", "error": str(e)}), 500


@app.route('/api/health')
def api_health():
    try:
        start_time = datetime.now()
        with _get_health_engine().connect() as conn:
            conn.execute(text('SELECT 1'))
        latency = (datetime.now() - start_time).total_seconds() * 1000
        return jsonify({"success": True, "status": "ok", "latency_ms": int(latency)})
    except Exception as e:
        return jsonify({"success": False, "status": "error", "error": str(e)}), 500


@app.route('/api/brands')
def api_brands():
    try:
        source = _make_source(None, datetime.utcnow() - timedelta(days=1), datetime.utcnow())
        df = source.fetch_brands()
        return jsonify({"success": True, "data": df.to_dict('records')})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/kpi')
def api_kpi():
    try:
        brand_id, days, start_date, end_date = _get_params()

        # Periodo corrente
        source = _make_source(brand_id, start_date, end_date)
        kpi_engine = IsualKPIEngine(source)
        kpi_data = kpi_engine.calc_overview()

        # Override etichette per valori dinamici dalla richiesta
        kpi_data['period_label'] = f"Ultimi {days} giorni"
        kpi_data['date_range'] = (
            f"{start_date.strftime('%d/%m/%Y')} – {end_date.strftime('%d/%m/%Y')}"
        )

        # Periodo precedente per trend
        prev_end_date = start_date
        prev_start_date = prev_end_date - timedelta(days=days)

        try:
            curr_overview = source.fetch_overview()
            curr_row = curr_overview.iloc[0]

            prev_source = _make_source(brand_id, prev_start_date, prev_end_date)
            prev_overview = prev_source.fetch_overview()
            prev_row = prev_overview.iloc[0]

            def calc_delta(curr, prev):
                curr = float(curr) if pd.notna(curr) else 0
                prev = float(prev) if pd.notna(prev) else 0
                if prev == 0:
                    return None
                return ((curr - prev) / prev) * 100

            def get_direction(trend_val):
                if trend_val is None:
                    return None
                if abs(trend_val) < 1.0:
                    return "flat"
                return "up" if trend_val > 0 else "down"

            prev_reach = float(prev_row['total_reach']) if pd.notna(prev_row['total_reach']) else 0
            prev_engagement = float(prev_row['total_engagement']) if pd.notna(prev_row['total_engagement']) else 0
            prev_er = (prev_engagement / prev_reach * 100) if prev_reach > 0 else 0

            prev_amp_df = prev_source.fetch_amplification()
            if not prev_amp_df.empty:
                amp_row = prev_amp_df.set_index("source")["reach"]
                prev_brand_reach = float(amp_row.get("brand", 0)) if pd.notna(amp_row.get("brand", 0)) else 0
                prev_amp_factor = (prev_reach / prev_brand_reach) if prev_brand_reach > 0 else 0
            else:
                prev_amp_factor = 0

            prev_adp_df = prev_source.fetch_adoption()
            if not prev_adp_df.empty:
                adp_row = prev_adp_df.iloc[0]
                prev_active = int(adp_row["active_partners"]) if pd.notna(adp_row["active_partners"]) else 0
                prev_total = int(adp_row["total_partners"]) if pd.notna(adp_row["total_partners"]) else 0
                prev_adp_pct = (prev_active / prev_total * 100) if prev_total > 0 else 0
            else:
                prev_adp_pct = 0

            trends = {
                'total_reach':       calc_delta(curr_row['total_reach'],       prev_row['total_reach']),
                'total_impressions': calc_delta(curr_row['total_impressions'],  prev_row['total_impressions']),
                'engagement_rate':   calc_delta(kpi_data['er_raw'],             prev_er),
                'total_posts':       calc_delta(curr_row['total_posts'],        prev_row['total_posts']),
                'amplification':     calc_delta(kpi_data['amp_raw'],            prev_amp_factor),
                'adoption_pct':      calc_delta(kpi_data['adoption_raw'],       prev_adp_pct),
            }

            for key, trend_val in trends.items():
                if key in kpi_data:
                    kpi_data[key] = {
                        "value":     kpi_data[key],
                        "trend":     trend_val,
                        "direction": get_direction(trend_val),
                    }
        except Exception as e:
            print("Trend calc error:", e)
            keys = [
                'total_reach', 'total_impressions', 'engagement_rate',
                'total_posts', 'amplification', 'adoption_pct',
            ]
            for key in keys:
                if key in kpi_data:
                    kpi_data[key] = {"value": kpi_data[key], "trend": None, "direction": None}

        return jsonify({"success": True, "data": kpi_data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/partners')
def api_partners():
    try:
        brand_id, days, start_date, end_date = _get_params()
        source = _make_source(brand_id, start_date, end_date)
        df_partners = source.fetch_partner_stats()
        if df_partners.empty:
            return jsonify({"success": True, "data": []})
        kpi_engine = IsualKPIEngine(source)
        df_health = kpi_engine.calc_partner_health(df_partners)
        return jsonify({"success": True, "data": df_health.head(3).to_dict('records')})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/top-partners')
def api_top_partners():
    try:
        brand_id, days, start_date, end_date = _get_params()
        source = _make_source(brand_id, start_date, end_date)
        df_partners = source.fetch_partner_stats()
        if df_partners.empty:
            return jsonify({"success": True, "data": []})
        kpi_engine = IsualKPIEngine(source)
        df_health = kpi_engine.calc_partner_health(df_partners)

        def classify_v2(score):
            if score >= 80: return "Top Performer"
            if score >= 60: return "Amplifier"
            if score >= 40: return "Quality Niche"
            return "Weak"

        df_health["classification"] = df_health["health_score"].apply(classify_v2)
        return jsonify({"success": True, "data": df_health.head(3).to_dict('records')})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/chart/trend')
def api_chart_trend():
    try:
        brand_id, days, start_date, end_date = _get_params()
        source = _make_source(brand_id, start_date, end_date)
        df_trend = source.fetch_weekly_trend()
        if df_trend.empty:
            return jsonify({"success": True, "data": {"chart": ""}})
        chart_engine = IsualChartEngine(COLORS)
        chart_b64 = chart_engine.trend_chart(df_trend)
        return jsonify({"success": True, "data": {"chart": chart_b64}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/trend-chart')
def api_trend_chart_v2():
    try:
        metric = request.args.get('metric', 'reach')
        if metric not in ['reach', 'impressions', 'engagement']:
            metric = 'reach'

        brand_id, days, start_date, end_date = _get_params()
        source = _make_source(brand_id, start_date, end_date)
        where, params = source._brand_filter(alias="pub")

        sql = f"""
            SELECT
                DATE(pub.published_at)   AS date,
                SUM(pub.ana_{metric})    AS value
            FROM publications pub
            {where}
            GROUP BY date
            ORDER BY date
        """
        with source._get_engine().connect() as conn:
            df = pd.read_sql(sql, conn, params=tuple(params))

        if df.empty:
            return jsonify({"success": True, "data": []})

        df['date'] = df['date'].astype(str)
        return jsonify({"success": True, "data": df.to_dict('records')})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/generate', methods=['POST'])
def api_generate():
    try:
        body = request.get_json() or {}
        brand_id = body.get('brand_id')
        if brand_id == 'all' or brand_id == '':
            brand_id = None

        days = body.get('days')
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=int(days)) if days else end_date - timedelta(days=30)

        output_path = str(
            ROOT / "outputs" / f"isual_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )

        source = _make_source(brand_id, start_date, end_date)
        kpi_engine = IsualKPIEngine(source)
        chart_engine = IsualChartEngine(COLORS)
        builder = IsualReportBuilder(kpi_engine, chart_engine, template_dir="templates")
        generated_file = builder.build(output_path)

        return jsonify({
            "success": True,
            "message": "Report generato con successo!",
            "file": os.path.basename(generated_file),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/export-csv')
def api_export_csv_v2():
    try:
        brand_id, days, start_date, end_date = _get_params()
        source = _make_source(brand_id, start_date, end_date)
        where, params = source._brand_filter(alias="pub")

        sql = f"""
            SELECT
                pub.id,
                pub.partner_id,
                pub.brand_id,
                pub.social,
                pub.status,
                pub.ana_reach        AS reach,
                pub.ana_impressions  AS impressions,
                pub.ana_engagement   AS engagement,
                pub.published_at
            FROM publications pub
            {where}
            ORDER BY pub.published_at DESC
        """
        with source._get_engine().connect() as conn:
            df = pd.read_sql(sql, conn, params=tuple(params))

        csv_data = df.to_csv(index=False)
        filename = f"isual_export_{datetime.now().strftime('%Y-%m-%d')}.csv"

        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/reports')
def api_reports():
    reports = []
    if os.path.exists(OUTPUT_DIR):
        for filename in os.listdir(OUTPUT_DIR):
            if filename.endswith('.pdf'):
                filepath = os.path.join(OUTPUT_DIR, filename)
                stat = os.stat(filepath)
                reports.append({
                    "filename":  filename,
                    "date":      datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    "size_kb":   round(stat.st_size / 1024, 1),
                    "timestamp": stat.st_mtime,
                })
    reports.sort(key=lambda x: x["timestamp"], reverse=True)
    return jsonify({"success": True, "data": reports})


@app.route('/outputs/<filename>')
def serve_output(filename):
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
