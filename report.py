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


def resolve_filter(partner_id=None, tag_id=None, target_id=None):
    # Risolve il filtro partner/tag/target in
    # (partner_ids, single_partner, filter_label, filter_slug, filter_kind).
    # Rispecchia get_params() della dashboard: gli stessi input devono produrre gli stessi
    # numeri nel PDF e a schermo.
    #
    # partner_ids: None = nessun filtro; lista (anche vuota) = filtro attivo.
    # Un tag senza partner associati da' [] -> zero risultati, non "tutti".
    # filter_kind: 'partner' | 'tag' | 'target' | None (nessun filtro), usato dal template
    # per parlare del filtro con il suo nome.
    selected = [k for k, v in (("partner", partner_id), ("tag", tag_id), ("target", target_id)) if v]
    if len(selected) > 1:
        raise ValueError(
            f"Filtri mutuamente esclusivi: specificarne uno solo tra "
            f"--partner-id/--tag-id/--target-id (ricevuti: {', '.join(selected)})"
        )

    if partner_id:
        # single_partner dipende dalla richiesta, non dal risultato: un tag che risolve
        # a un solo partner NON e' un partner singolo e non deve dare N/A su Network Adoption.
        name = db.get_partner_name(partner_id)
        return ([partner_id], True, f"Partner: {name or partner_id}",
                slugify(name) or "tutti-partner", "partner")

    if tag_id:
        name = db.get_tag_name(tag_id)
        return (db.get_partner_ids_by_tag(tag_id), False, f"Tag: {name or tag_id}",
                f"tag-{slugify(name) or tag_id}", "tag")

    if target_id:
        name = db.get_target_name(target_id)
        return (db.get_partner_ids_by_target(target_id), False, f"Target: {name or target_id}",
                f"target-{slugify(name) or target_id}", "target")

    return None, False, "Tutti i partner", "tutti-partner", None


def generate_report(brand_id=None, partner_id=None, tag_id=None, target_id=None,
                     days=DEFAULT_DAYS, output_path=DEFAULT_OUTPUT,
                     date_from=None, date_to=None):
    if date_from and date_to:
        start_date = datetime.strptime(date_from, '%Y-%m-%d')
        end_date   = datetime.strptime(date_to, '%Y-%m-%d')
        days = (end_date - start_date).days
    else:
        end_date   = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

    # filtro selezionato (partner, tag o target), per header e filename del PDF
    partner_ids, single_partner, filter_label, filter_slug, filter_kind = resolve_filter(
        partner_id, tag_id, target_id)

    print(f"[ISUAL] Periodo: {start_date.date()} → {end_date.date()}")
    print(f"[ISUAL] Brand: {brand_id or 'tutti'}")
    print(f"[ISUAL] Filtro: {filter_label}")
    if partner_ids is not None:
        print(f"[ISUAL] Partner selezionati: {len(partner_ids)}")

    # fetch dati dal database — stessi filtri (brand_id, partner_ids) usati dalla vista dashboard
    print("[1/4] Carico dati...")
    df_overview = db.get_overview(brand_id, partner_ids, start_date, end_date)
    df_amplif   = db.get_amplification(brand_id, partner_ids, start_date, end_date)
    df_trend    = db.get_weekly_trend(brand_id, partner_ids, start_date, end_date)
    df_content  = db.get_content_performance(brand_id, partner_ids, start_date, end_date)
    df_partners = db.get_partner_stats(brand_id, partner_ids, start_date, end_date)
    df_channels = db.get_channel_breakdown(brand_id, partner_ids, start_date, end_date)

    # Network Adoption resta una metrica di rete, ma la "rete" e' il sottoinsieme selezionato:
    # per un tag/target il denominatore sono i suoi partner, non l'intero brand. Per il singolo
    # partner la metrica non ha senso e viene mostrata N/A tramite partner_filtered qui sotto.
    df_adoption = db.get_adoption(brand_id, partner_ids, start_date, end_date)

    # nome del brand per l'header: identifica il report a colpo d'occhio ora che i colori
    # e i loghi per-brand sono disattivati. Senza brand_id il report copre tutta la rete.
    brand_name = (db.get_brand_name(brand_id) or "").strip() if brand_id else ""
    if not brand_name:
        brand_name = "Tutti i brand"

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
    # N/A su Network Adoption dipende dalla selezione (single_partner) e non dalla
    # lunghezza della lista risolta: identico alla dashboard.
    kpi_data       = kpi.calc_overview(df_overview, df_amplif, df_adoption, days, start_date, end_date,
                                        partner_filtered=single_partner)
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
        brand_name=brand_name,
        filter_label=filter_label,
        single_partner=single_partner,
        filter_kind=filter_kind,
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
    # partner/tag/target sono tre modi alternativi di selezionare gli stessi partner:
    # argparse rifiuta la combinazione prima di toccare il DB
    filtro = parser.add_mutually_exclusive_group()
    filtro.add_argument("--partner-id", type=str, default=None,           dest="partner_id", help="UUID partner")
    filtro.add_argument("--tag-id",     type=str, default=None,           dest="tag_id", help="UUID tag")
    filtro.add_argument("--target-id",  type=str, default=None,           dest="target_id", help="UUID target")
    parser.add_argument("--out",        type=str, default=DEFAULT_OUTPUT, help="Path output PDF")
    parser.add_argument("--date-from",  type=str, default=None,           help="Data inizio")
    parser.add_argument("--date-to",    type=str, default=None,           help="Data fine")
    args = parser.parse_args()

    generate_report(
        brand_id=args.brand_id,
        partner_id=args.partner_id,
        tag_id=args.tag_id,
        target_id=args.target_id,
        days=args.days,
        output_path=args.out,
        date_from=args.date_from,
        date_to=args.date_to,
    )
