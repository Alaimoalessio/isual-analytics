import os
import sys
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, render_template, Response
from sqlalchemy import text

# aggiunge la root al path per importare database, kpi e report
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import database as db
import kpi
from report import generate_report, slugify

import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__,
            static_folder=os.path.join(BASE_DIR, 'static'),
            template_folder=os.path.join(BASE_DIR, 'dashboard', 'templates'))

OUTPUT_DIR = str(ROOT / "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _clean(value):
    # 'all' e stringa vuota significano "nessuna selezione"
    return None if value in ('all', '') else value


def get_params():
    brand_id = _clean(request.args.get('brand_id', default=None, type=str))

    partner_id = _clean(request.args.get('partner_id', default=None, type=str))
    tag_id     = _clean(request.args.get('tag_id', default=None, type=str))
    target_id  = _clean(request.args.get('target_id', default=None, type=str))

    # single_partner dipende dalla richiesta, non dal risultato: un tag che risolve
    # a un solo partner NON e' un partner singolo e non deve dare N/A su Network Adoption.
    single_partner = partner_id is not None

    # partner_ids: None = nessun filtro; lista (anche vuota) = filtro attivo.
    # Un tag senza partner associati da' [] -> zero risultati, non "tutti".
    if single_partner:
        partner_ids = [partner_id]
    elif tag_id is not None:
        partner_ids = db.get_partner_ids_by_tag(tag_id)
    elif target_id is not None:
        partner_ids = db.get_partner_ids_by_target(target_id)
    else:
        partner_ids = None

    date_from = request.args.get('date_from', default=None, type=str)
    date_to   = request.args.get('date_to', default=None, type=str)

    if date_from and date_to:
        start_date = datetime.strptime(date_from, '%Y-%m-%d')
        end_date   = datetime.strptime(date_to, '%Y-%m-%d')
        days = (end_date - start_date).days
    else:
        days = request.args.get('days', default=30, type=int)
        end_date   = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

    return brand_id, partner_ids, single_partner, days, start_date, end_date


@app.route('/')
def index():
    return render_template('dashboard.html')


@app.route('/api/db-status')
def api_db_status():
    try:
        import concurrent.futures

        def ping():
            t0 = datetime.now()
            with db.get_engine().connect() as conn:
                conn.execute(text('SELECT 1'))
            return (datetime.now() - t0).total_seconds() * 1000

        with concurrent.futures.ThreadPoolExecutor() as executor:
            latency = executor.submit(ping).result(timeout=5.0)

        return jsonify({"success": True, "status": "ok", "latency_ms": int(latency)})
    except concurrent.futures.TimeoutError:
        return jsonify({"success": False, "status": "error", "error": "Timeout"}), 504
    except Exception as e:
        return jsonify({"success": False, "status": "error", "error": str(e)}), 500


@app.route('/api/health')
def api_health():
    try:
        t0 = datetime.now()
        with db.get_engine().connect() as conn:
            conn.execute(text('SELECT 1'))
        latency = (datetime.now() - t0).total_seconds() * 1000
        return jsonify({"success": True, "status": "ok", "latency_ms": int(latency)})
    except Exception as e:
        return jsonify({"success": False, "status": "error", "error": str(e)}), 500


@app.route('/api/brands')
def api_brands():
    try:
        df = db.get_brands()
        return jsonify({"success": True, "data": df.to_dict('records')})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/filter/partners')
def api_filter_partners():
    try:
        brand_id = _clean(request.args.get('brand_id', default=None, type=str))
        df = db.get_partners_for_filter(brand_id)
        return jsonify({"success": True, "data": df.to_dict('records')})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/filter/tags')
def api_filter_tags():
    try:
        brand_id = _clean(request.args.get('brand_id', default=None, type=str))
        df = db.get_tags_for_brand(brand_id)
        return jsonify({"success": True, "data": df.to_dict('records')})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/filter/targets')
def api_filter_targets():
    try:
        brand_id = _clean(request.args.get('brand_id', default=None, type=str))
        df = db.get_targets_for_brand(brand_id)
        return jsonify({"success": True, "data": df.to_dict('records')})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/kpi')
def api_kpi():
    try:
        brand_id, partner_ids, single_partner, days, start_date, end_date = get_params()

        df_overview = db.get_overview(brand_id, partner_ids, start_date, end_date)
        df_amplif   = db.get_amplification(brand_id, partner_ids, start_date, end_date)
        df_adoption = db.get_adoption(brand_id, partner_ids, start_date, end_date)

        # Network Adoption è una metrica di rete: con un singolo partner filtrato va mostrata N/A.
        # Con un filtro Tag/Target si calcola normalmente sul gruppo, quindi il flag segue la
        # selezione (single_partner) e non la lunghezza della lista.
        kpi_data = kpi.calc_overview(df_overview, df_amplif, df_adoption, days, start_date, end_date,
                                     partner_filtered=single_partner)

        # calcola trend confrontando col periodo precedente
        prev_end   = start_date
        prev_start = prev_end - timedelta(days=days)

        try:
            curr_row = df_overview.iloc[0]
            prev_ov  = db.get_overview(brand_id, partner_ids, prev_start, prev_end)
            prev_row = prev_ov.iloc[0]

            def delta(curr, prev):
                curr = float(curr) if pd.notna(curr) else 0
                prev = float(prev) if pd.notna(prev) else 0
                return None if prev == 0 else ((curr - prev) / prev) * 100

            def direction(t):
                if t is None: return None
                return "flat" if abs(t) < 1.0 else ("up" if t > 0 else "down")

            prev_reach      = float(prev_row['total_reach'])      if pd.notna(prev_row['total_reach'])      else 0
            prev_engagement = float(prev_row['total_engagement'])  if pd.notna(prev_row['total_engagement'])  else 0
            prev_er         = (prev_engagement / prev_reach * 100) if prev_reach > 0 else 0

            prev_amp_df = db.get_amplification(brand_id, partner_ids, prev_start, prev_end)
            if not prev_amp_df.empty:
                amp_row         = prev_amp_df.set_index("source")["reach"]
                prev_br         = float(amp_row.get("brand", 0)) if pd.notna(amp_row.get("brand", 0)) else 0
                prev_amp_factor = (prev_reach / prev_br) if prev_br > 0 else 0
            else:
                prev_amp_factor = 0

            prev_adp_df = db.get_adoption(brand_id, partner_ids, prev_start, prev_end)
            if not prev_adp_df.empty:
                adp_row  = prev_adp_df.iloc[0]
                prev_act = int(adp_row["active_partners"]) if pd.notna(adp_row["active_partners"]) else 0
                prev_tot = int(adp_row["total_partners"])  if pd.notna(adp_row["total_partners"])  else 0
                prev_adp = (prev_act / prev_tot * 100) if prev_tot > 0 else 0
            else:
                prev_adp = 0

            trends = {
                'total_reach':       delta(curr_row['total_reach'],      prev_row['total_reach']),
                'total_impressions': delta(curr_row['total_impressions'], prev_row['total_impressions']),
                'engagement_rate':   delta(kpi_data['er_raw'],            prev_er),
                'total_posts':       delta(curr_row['total_posts'],       prev_row['total_posts']),
                'amplification':     delta(kpi_data['amp_raw'],           prev_amp_factor),
                'adoption_pct':      delta(kpi_data['adoption_raw'],      prev_adp),
            }

            for key, t in trends.items():
                if key in kpi_data:
                    kpi_data[key] = {"value": kpi_data[key], "trend": t, "direction": direction(t)}

        except Exception as e:
            print("Trend error:", e)
            for key in ['total_reach', 'total_impressions', 'engagement_rate',
                        'total_posts', 'amplification', 'adoption_pct']:
                if key in kpi_data:
                    kpi_data[key] = {"value": kpi_data[key], "trend": None, "direction": None}

        # Engagement Totale e Frequency non hanno un confronto storico (nessun trend calcolato):
        # le avvolgo nella stessa forma {value, trend, direction} delle altre card, con trend
        # assente → il frontend mostra "N/D" al posto dell'indicatore, senza rompersi.
        for key in ['total_engagement', 'frequency']:
            if key in kpi_data and not isinstance(kpi_data[key], dict):
                kpi_data[key] = {"value": kpi_data[key], "trend": None, "direction": None}

        # configurazione ordinata delle KPI card visibili per il brand (stessa fonte del PDF);
        # fallback all'ordine di default se brand_id assente o brand senza config.
        kpi_config = db.get_kpi_config(brand_id) or db.DEFAULT_KPI_ORDER

        return jsonify({"success": True, "data": kpi_data, "kpi_config": kpi_config})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/partners')
def api_partners():
    try:
        brand_id, partner_ids, single_partner, days, start_date, end_date = get_params()
        df = db.get_partner_stats(brand_id, partner_ids, start_date, end_date)
        if df.empty:
            return jsonify({"success": True, "data": []})
        result = kpi.calc_partner_health(df)
        return jsonify({"success": True, "data": result.head(3).to_dict('records')})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/top-partners')
def api_top_partners():
    try:
        brand_id, partner_ids, single_partner, days, start_date, end_date = get_params()
        df = db.get_partner_stats(brand_id, partner_ids, start_date, end_date)
        if df.empty:
            return jsonify({"success": True, "data": []})
        result = kpi.calc_partner_health(df)

        def classify_v2(score):
            if score >= 80: return "Top Performer"
            if score >= 60: return "Amplifier"
            if score >= 40: return "Quality Niche"
            return "Weak"

        result["classification"] = result["health_score"].apply(classify_v2)
        return jsonify({"success": True, "data": result.head(3).to_dict('records')})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/top-content')
def api_top_content():
    try:
        brand_id, partner_ids, single_partner, days, start_date, end_date = get_params()
        df = db.get_content_performance(brand_id, partner_ids, start_date, end_date)
        if df.empty:
            return jsonify({"success": True, "data": []})

        # stessa funzione usata dal PDF (report.py): il troncamento a 5 righe e' dentro
        # kpi.calc_content_score, cosi' dashboard e report mostrano le stesse identiche righe
        result = kpi.calc_content_score(df)

        # colonne selezionate a mano, non to_dict() sul df intero: published_at e' un
        # Timestamp non serializzabile, e reach_norm/title/post_id non servono al client
        rows = [
            {
                "rank":          i + 1,
                "title_short":   r["title_short"],
                "channel":       r["channel"],
                "channel_upper": r["channel_upper"],
                "reach_fmt":     r["reach_fmt"],
                "impr_fmt":      r["impr_fmt"],
                "er_fmt":        r["er_fmt"],
                "er_post":       float(r["er_post"]),   # grezzo: serve al JS per la soglia colore
                "score_fmt":     r["score_fmt"],
                # lista di nomi, non il conteggio: stessa colonna e stessi nomi del PDF.
                # ARRAY_AGG torna None quando il contenuto e' stato pubblicato solo dal
                # brand (partner_id NULL) -> lista vuota, che il JS rende come "—".
                "partner_names": list(r["partner_names"]) if r["partner_names"] is not None else [],
            }
            for i, r in result.iterrows()
        ]
        return jsonify({"success": True, "data": rows})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/chart/trend')
def api_chart_trend():
    try:
        brand_id, partner_ids, single_partner, days, start_date, end_date = get_params()
        df    = db.get_weekly_trend(brand_id, partner_ids, start_date, end_date)
        if df.empty:
            return jsonify({"success": True, "data": {"chart": ""}})
            
        if brand_id:
            brand_colors = db.get_brand_settings(brand_id)
        else:
            brand_colors = {
                'primary_color': '#1C2B46',
                'secondary_color': '#F24C27',
                'accent_color': '#F24C27'
            }
            
        chart = kpi.make_trend_chart(df, brand_colors)
        return jsonify({"success": True, "data": {"chart": chart}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/trend-chart')
def api_trend_chart():
    try:
        metric = request.args.get('metric', 'reach')
        if metric not in ['reach', 'impressions', 'engagement']:
            metric = 'reach'

        brand_id, partner_ids, single_partner, days, start_date, end_date = get_params()
        where, params = db.brand_filter(alias="pub", brand_id=brand_id, partner_id=partner_ids,
                                        start_date=start_date, end_date=end_date)
        sql = f"""
            SELECT
                DATE(pub.published_at)   AS date,
                SUM(pub.ana_{metric})    AS value
            FROM publications pub
            {where}
            GROUP BY date
            ORDER BY date
        """
        with db.get_engine().connect() as conn:
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
        data       = request.get_json() or {}
        brand_id   = _clean(data.get('brand_id'))
        partner_id = _clean(data.get('partner_id'))
        tag_id     = _clean(data.get('tag_id'))
        target_id  = _clean(data.get('target_id'))
        days       = data.get('days', 30)
        date_from  = data.get('date_from')
        date_to    = data.get('date_to')

        selected = [k for k, v in (("partner_id", partner_id), ("tag_id", tag_id), ("target_id", target_id)) if v]
        if len(selected) > 1:
            return jsonify({"success": False,
                            "error": f"Filtri mutuamente esclusivi: {', '.join(selected)}"}), 400

        # costruisce i parametri per report.py
        import subprocess, sys
        cmd = [sys.executable, 'report.py']

        if brand_id:
            cmd += ['--brand-id', brand_id]

        # passthrough dell'id: la risoluzione tag/target -> lista partner avviene dentro
        # report.py, cosi' non passiamo N uuid sulla command line
        if partner_id:
            cmd += ['--partner-id', partner_id]
        elif tag_id:
            cmd += ['--tag-id', tag_id]
        elif target_id:
            cmd += ['--target-id', target_id]

        if date_from and date_to:
            cmd += ['--date-from', date_from, '--date-to', date_to]
        else:
            cmd += ['--days', str(days)]

        # naming standardizzato: isual_report_[brand-slug]_[partner-slug]_[YYYYMMDD]_[HHMMSS_ms].pdf
        # brand-slug e partner-slug sono SEMPRE presenti (mai omessi), cosi' in Storico Report
        # si distingue a colpo d'occhio un report aggregato da uno filtrato, per qualunque combinazione di filtri
        brand_name = db.get_brand_name(brand_id) if brand_id else None
        brand_slug = slugify(brand_name) or "tutti-brand"

        # lo slug del filtro porta il prefisso tag-/target- per distinguere in Storico Report
        # un report per tag da uno per partner omonimo
        if partner_id:
            partner_slug = slugify(db.get_partner_name(partner_id)) or "tutti-partner"
        elif tag_id:
            partner_slug = "tag-" + (slugify(db.get_tag_name(tag_id)) or tag_id)
        elif target_id:
            partner_slug = "target-" + (slugify(db.get_target_name(target_id)) or target_id)
        else:
            partner_slug = "tutti-partner"

        # millisecondi in coda al timestamp: due generazioni ravvicinate per lo stesso
        # brand+partner nello stesso secondo altrimenti si sovrascriverebbero silenziosamente
        timestamp   = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
        output_path = str(ROOT / "outputs" / f"isual_report_{brand_slug}_{partner_slug}_{timestamp}.pdf")
        cmd += ['--out', output_path]

        subprocess.run(cmd, check=True, cwd=str(ROOT))

        return jsonify({"success": True, "message": "Report generato!", "file": os.path.basename(output_path)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/export-csv')
def api_export_csv():
    try:
        brand_id, partner_ids, single_partner, days, start_date, end_date = get_params()
        where, params = db.brand_filter(alias="pub", brand_id=brand_id, partner_id=partner_ids,
                                        start_date=start_date, end_date=end_date)
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
        with db.get_engine().connect() as conn:
            df = pd.read_sql(sql, conn, params=tuple(params))

        filename = f"isual_export_{datetime.now().strftime('%Y-%m-%d')}.csv"
        return Response(
            df.to_csv(index=False),
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


@app.route('/api/reports/<filename>', methods=['DELETE'])
def api_delete_report(filename):
    try:
        # Previeni directory traversal
        if '..' in filename or '/' in filename or '\\' in filename:
            return jsonify({"success": False, "error": "Nome file non valido"}), 400
            
        filepath = os.path.join(OUTPUT_DIR, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({"success": True, "message": "Report eliminato"})
        else:
            return jsonify({"success": False, "error": "File non trovato"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/reports/bulk-delete', methods=['POST'])
def api_bulk_delete_reports():
    try:
        data = request.get_json() or {}
        filenames = data.get('filenames', [])
        
        if not isinstance(filenames, list) or len(filenames) == 0:
            return jsonify({"success": False, "error": "Nessun file selezionato"}), 400
            
        deleted_count = 0
        for filename in filenames:
            if '..' in filename or '/' in filename or '\\' in filename:
                continue # Salta nomi file non validi per sicurezza
                
            filepath = os.path.join(OUTPUT_DIR, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
                deleted_count += 1
                
        return jsonify({
            "success": True, 
            "message": f"{deleted_count} report eliminat{'o' if deleted_count == 1 else 'i'} con successo"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/kpi-config/all')
def api_kpi_config_all():
    # TUTTE le 8 KPI (visibili E nascoste) per il pannello di configurazione.
    # Config globale: brand_id opzionale; senza, legge da un brand di riferimento.
    # NB: endpoint separato da /api/kpi (che continua a restituire solo le visibili).
    try:
        brand_id = request.args.get('brand_id', default=None, type=str)
        if brand_id in ('all', ''):
            brand_id = None
        kpi_config = db.get_kpi_config_all(brand_id)
        return jsonify({"success": True, "kpi_config": kpi_config})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/kpi-config/save', methods=['POST'])
def api_save_kpi_config():
    # salva ordine e visibilità delle KPI card in modo GLOBALE (tutti i brand).
    # L'ordine è dedotto dalla sequenza ricevuta; il set deve contenere esattamente
    # gli 8 kpi_key noti (nessuno mancante, sconosciuto o duplicato).
    try:
        data = request.get_json(silent=True) or {}
        kpi_order = data.get('kpi_order')

        # validazione fail-fast: nessuna scrittura se l'input non è consistente
        if not isinstance(kpi_order, list) or len(kpi_order) == 0:
            return jsonify({"success": False, "error": "'kpi_order' mancante o vuoto"}), 400

        noti = {c["kpi_key"] for c in db.DEFAULT_KPI_ORDER}
        visti = []
        for i, item in enumerate(kpi_order):
            if (not isinstance(item, dict)
                    or not isinstance(item.get("kpi_key"), str)
                    or not isinstance(item.get("visibile"), bool)):
                return jsonify({"success": False,
                                "error": f"elemento non valido in posizione {i}: "
                                         "serve kpi_key (string) e visibile (bool)"}), 400
            k = item["kpi_key"]
            if k not in noti:
                return jsonify({"success": False, "error": f"kpi_key sconosciuto: '{k}'"}), 400
            if k in visti:
                return jsonify({"success": False, "error": f"kpi_key duplicato: '{k}'"}), 400
            visti.append(k)

        mancanti = noti - set(visti)
        if mancanti:
            return jsonify({"success": False, "error": f"kpi_key mancanti: {sorted(mancanti)}"}), 400

        # input validato: scrittura globale in transazione unica (commit/rollback in database.py)
        updated = db.save_kpi_config_global(kpi_order)
        return jsonify({"success": True, "updated": updated})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/outputs/<filename>')
def serve_output(filename):
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == '__main__':
    # Solo per sviluppo locale. In produzione l'app è servita da Gunicorn
    # (vedi dashboard/Procfile), che importa direttamente l'oggetto `app`.
    app.run(host='0.0.0.0', port=5001, debug=False)
