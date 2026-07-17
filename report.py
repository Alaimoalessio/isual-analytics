import os
import re
import argparse
from datetime import datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS

import database as db
import kpi

DEFAULT_DAYS   = 30
DEFAULT_OUTPUT = f"outputs/isual_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"


def soglia_colore(valore, soglia_verde, soglia_arancio):
    # colore della KPI in base alle soglie (stessi hex del template originale)
    if valore >= soglia_verde:   return "#2F9E44"  # verde
    if valore >= soglia_arancio: return "#F08C00"  # arancio
    return "#E03131"                                # rosso


def slugify(text):
    # converte un nome libero (brand, partner, ...) in uno slug sicuro per filename/path/URL:
    # minuscolo, spazi e caratteri speciali sostituiti con trattini singoli
    if not text:
        return ""
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def generate_report(brand_id=None, partner_id=None, days=DEFAULT_DAYS, output_path=DEFAULT_OUTPUT,
                     date_from=None, date_to=None):
    if date_from and date_to:
        start_date = datetime.strptime(date_from, '%Y-%m-%d')
        end_date   = datetime.strptime(date_to, '%Y-%m-%d')
        days = (end_date - start_date).days
    else:
        end_date   = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

    # nome del partner selezionato (se presente), per header e filename del PDF
    partner_name  = db.get_partner_name(partner_id) if partner_id else None
    partner_label = partner_name or "Tutti i partner"

    print(f"[ISUAL] Periodo: {start_date.date()} → {end_date.date()}")
    print(f"[ISUAL] Brand: {brand_id or 'tutti'}")
    print(f"[ISUAL] Partner: {partner_label}")

    # fetch dati dal database — stessi filtri (brand_id, partner_id) usati dalla vista dashboard
    print("[1/4] Carico dati...")
    df_overview = db.get_overview(brand_id, partner_id, start_date, end_date)
    df_amplif   = db.get_amplification(brand_id, partner_id, start_date, end_date)
    df_trend    = db.get_weekly_trend(brand_id, partner_id, start_date, end_date)
    df_content  = db.get_content_performance(brand_id, partner_id, start_date, end_date)
    df_partners = db.get_partner_stats(brand_id, partner_id, start_date, end_date)
    df_channels = db.get_channel_breakdown(brand_id, partner_id, start_date, end_date)

    # Network Adoption è una metrica sull'intera rete di partner di un brand:
    # non va scoperta/ricalcolata su un singolo partner, quindi non filtriamo mai per partner_id
    df_adoption = db.get_adoption(brand_id, None, start_date, end_date)

    # recupera colori del brand dal DB
    if brand_id:
        brand_colors = db.get_brand_settings(brand_id)
    else:
        brand_colors = {
            'primary_color':   '#1C2B46',
            'secondary_color': '#F24C27',
            'accent_color':    '#F24C27',
            'logo_url':        None
        }

    # converti logo_url in path assoluto per WeasyPrint
    if brand_colors.get('logo_url'):
        logo_path = os.path.join(os.path.dirname(__file__), brand_colors['logo_url'])
        if os.path.exists(logo_path):
            brand_colors['logo_url'] = logo_path
        else:
            brand_colors['logo_url'] = None

    # calcola KPI e tabelle
    print("[2/4] Calcolo metriche...")
    kpi_data       = kpi.calc_overview(df_overview, df_amplif, df_adoption, days, start_date, end_date,
                                        partner_filtered=bool(partner_id))
    df_content_ok  = kpi.calc_content_score(df_content)
    df_partners_ok = kpi.calc_partner_health(df_partners)
    df_channels_ok = kpi.calc_channel_breakdown(df_channels)

    # impacchetta i valori KPI per il template: dict kpi_key -> attributi di presentazione
    # (valore, colore-soglia precalcolato, sottotitolo, highlight). La logica di CALCOLO
    # resta in kpi.py: qui si decide solo COME i valori vengono mostrati nella card.
    # Network Adoption: il caso N/A (singolo partner) è collassato in color+subtitle,
    # così nel loop del template non serve un ramo speciale.
    if kpi_data["network_scope_na"]:
        adp_color = "#6C757D"
        adp_sub   = "Metrica di rete — non disponibile per singolo partner"
    else:
        adp_color = soglia_colore(kpi_data["adoption_raw"], 70, 40)
        adp_sub   = f'{kpi_data["active_partners"]}/{kpi_data["total_partners"]} partner attivi'

    kpi_cards = {
        "reach":                {"value": kpi_data["total_reach"],       "color": None,                                         "subtitle": "Audience unica raggiunta",  "highlight": True},
        "impressions":          {"value": kpi_data["total_impressions"], "color": None,                                         "subtitle": "Esposizioni totali",        "highlight": False},
        "engagement_total":     {"value": kpi_data["total_engagement"],  "color": None,                                         "subtitle": "Like + Commenti + Share",   "highlight": False},
        "post_pubblicati":      {"value": kpi_data["total_posts"],       "color": None,                                         "subtitle": "Status OK nel periodo",     "highlight": False},
        "engagement_rate":      {"value": kpi_data["engagement_rate"],   "color": soglia_colore(kpi_data["er_raw"],  3.0, 1.5), "subtitle": "Engagement / Reach × 100",  "highlight": False},
        "amplification_factor": {"value": kpi_data["amplification"],     "color": soglia_colore(kpi_data["amp_raw"], 2.0, 1.2), "subtitle": "Reach totale / Reach brand", "highlight": False},
        "network_adoption":     {"value": kpi_data["adoption_pct"],      "color": adp_color,                                    "subtitle": adp_sub,                     "highlight": False},
        "frequency":            {"value": kpi_data["frequency"],         "color": None,                                         "subtitle": "Impressions / Reach",       "highlight": False},
    }

    # ordine e visibilità delle card dalla config in DB; fallback all'ordine di default
    kpi_config = db.get_kpi_config(brand_id) or db.DEFAULT_KPI_ORDER

    # genera grafici
    print("[3/4] Genero grafici...")
    trend_chart   = kpi.make_trend_chart(df_trend, brand_colors)
    channel_chart = kpi.make_channel_bar_chart(df_channels_ok, brand_colors)

    # render template HTML e salva PDF
    print("[4/4] Genero PDF...")
    template_dir = str(Path(__file__).resolve().parent / "templates")
    env      = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("report.html")

    html = template.render(
        kpi=kpi_data,
        kpi_config=kpi_config,
        kpi_cards=kpi_cards,
        trend_chart=trend_chart,
        channel_chart=channel_chart,
        content_rows=df_content_ok.to_dict("records"),
        partner_rows=df_partners_ok.to_dict("records"),
        channel_rows=df_channels_ok.to_dict("records"),
        colors=brand_colors,
        partner_label=partner_label,
    )

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    HTML(string=html).write_pdf(
        output_path,
        stylesheets=[CSS(string="@page { size: A4; margin: 0; }")],
    )

    print(f"[✓] Report salvato: {output_path}")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ISUAL Analytics — genera report PDF")
    parser.add_argument("--days",       type=int, default=DEFAULT_DAYS,   help="Numero di giorni")
    parser.add_argument("--brand-id",   type=str, default=None,           dest="brand_id", help="UUID brand")
    parser.add_argument("--partner-id", type=str, default=None,           dest="partner_id", help="UUID partner")
    parser.add_argument("--out",        type=str, default=DEFAULT_OUTPUT, help="Path output PDF")
    parser.add_argument("--date-from",  type=str, default=None,           help="Data inizio")
    parser.add_argument("--date-to",    type=str, default=None,           help="Data fine")
    args = parser.parse_args()

    generate_report(
        brand_id=args.brand_id,
        partner_id=args.partner_id,
        days=args.days,
        output_path=args.out,
        date_from=args.date_from,
        date_to=args.date_to,
    )
