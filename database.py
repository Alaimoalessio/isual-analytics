import os
import pandas as pd
from pathlib import Path
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# URL di connessione al database
DB_URL = (
    "postgresql+psycopg2://"
    f"{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
    f"@{os.environ['DB_HOST']}:{os.getenv('DB_PORT', '5432')}/{os.environ['DB_NAME']}"
    f"?sslmode={os.getenv('DB_SSLMODE', 'require')}"
)

_engine = None


def get_engine():
    # singleton: crea il motore solo al primo utilizzo
    global _engine
    if _engine is None:
        _engine = create_engine(DB_URL)
    return _engine


def normalize_partner_ids(partner_id):
    # None = nessun filtro partner; lista vuota = filtro attivo che non seleziona
    # nessun partner (zero risultati). Le due cose non vanno confuse.
    # Accetta un singolo id (report.py) o una lista (dashboard con Tag/Target).
    if partner_id is None:
        return None
    if isinstance(partner_id, str):
        return [partner_id]
    return list(partner_id)


def brand_filter(alias="pub", brand_id=None, partner_id=None, start_date=None, end_date=None):
    # clausola WHERE con filtri su periodo, brand e partner opzionali
    conditions = [
        f"{alias}.published_at >= %s",
        f"{alias}.published_at < %s",
        f"{alias}.status = 'OK'",
    ]
    params = [start_date, end_date]

    if brand_id:
        conditions.append(f"{alias}.brand_id = %s")
        params.append(brand_id)

    partner_ids = normalize_partner_ids(partner_id)
    if partner_ids is not None:
        if partner_ids:
            # il cast e' obbligatorio: psycopg2 adatta la lista a text[] e
            # Postgres non ha un operatore uuid = text
            conditions.append(f"{alias}.partner_id = ANY(%s::uuid[])")
            params.append(partner_ids)
        else:
            conditions.append("FALSE")

    where = "WHERE " + " AND ".join(conditions)
    return where, params


def run_query(sql, params=None):
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=tuple(params) if params else None)


def get_brands():
    return run_query("SELECT id, name FROM brands ORDER BY name")


def get_partners_for_filter(brand_id=None):
    sql = "SELECT id, name FROM partners"
    params = []
    if brand_id:
        sql += " WHERE brand_id = %s"
        params.append(brand_id)
    sql += " ORDER BY name"
    return run_query(sql, params)


def get_tags_for_brand(brand_id=None):
    # tags e targets sono tabelle dell'app di terzi: sola lettura, soft delete
    sql = "SELECT id, name FROM tags WHERE deleted = false"
    params = []
    if brand_id:
        sql += " AND brand_id = %s"
        params.append(brand_id)
    sql += " ORDER BY name"
    return run_query(sql, params)


def get_targets_for_brand(brand_id=None):
    sql = "SELECT id, name FROM targets WHERE deleted = false"
    params = []
    if brand_id:
        sql += " AND brand_id = %s"
        params.append(brand_id)
    sql += " ORDER BY name"
    return run_query(sql, params)


def get_partner_ids_by_tag(tag_id):
    # lista vuota = tag senza partner associati: chi chiama deve trattarla come
    # filtro attivo a zero risultati, non come assenza di filtro
    sql = """
        SELECT DISTINCT pt.partner_id
        FROM partners_tags pt
        JOIN tags t ON t.id = pt.tag_id
        WHERE pt.tag_id = %s
          AND t.deleted = false
    """
    df = run_query(sql, [tag_id])
    return [str(pid) for pid in df["partner_id"].tolist()]


def get_partner_ids_by_target(target_id):
    sql = """
        SELECT DISTINCT pt.partner_id
        FROM partners_targets pt
        JOIN targets t ON t.id = pt.target_id
        WHERE pt.target_id = %s
          AND t.deleted = false
    """
    df = run_query(sql, [target_id])
    return [str(pid) for pid in df["partner_id"].tolist()]


def get_partner_name(partner_id):
    # nome del partner selezionato, usato nell'header e nel nome file del PDF
    df = run_query("SELECT name FROM partners WHERE id = %s", [partner_id])
    if df.empty:
        return None
    return df.iloc[0]['name']


def get_tag_name(tag_id):
    # nome del tag selezionato, usato nell'header e nel nome file del PDF
    df = run_query("SELECT name FROM tags WHERE id = %s AND deleted = false", [tag_id])
    if df.empty:
        return None
    return df.iloc[0]['name']


def get_target_name(target_id):
    # nome del target selezionato, usato nell'header e nel nome file del PDF
    df = run_query("SELECT name FROM targets WHERE id = %s AND deleted = false", [target_id])
    if df.empty:
        return None
    return df.iloc[0]['name']


def get_brand_name(brand_id):
    # nome del brand selezionato, usato nel nome file del PDF
    df = run_query("SELECT name FROM brands WHERE id = %s", [brand_id])
    if df.empty:
        return None
    return df.iloc[0]['name']


def get_overview(brand_id, partner_id, start_date, end_date):
    where, params = brand_filter(brand_id=brand_id, partner_id=partner_id, start_date=start_date, end_date=end_date)
    sql = f"""
        SELECT
            SUM(pub.ana_reach)                                      AS total_reach,
            SUM(pub.ana_impressions)                                AS total_impressions,
            SUM(pub.ana_engagement)                                 AS total_engagement,
            COUNT(DISTINCT pub.id)                                  AS total_posts,
            COUNT(DISTINCT pub.partner_id)
                FILTER (WHERE pub.partner_id IS NOT NULL)           AS active_partners,
            COUNT(DISTINCT p.id)                                    AS total_partners
        FROM publications pub
        LEFT JOIN partners p ON p.brand_id = pub.brand_id
        {where}
    """
    return run_query(sql, params)


def get_amplification(brand_id, partner_id, start_date, end_date):
    where, params = brand_filter(brand_id=brand_id, partner_id=partner_id, start_date=start_date, end_date=end_date)
    sql = f"""
        SELECT
            CASE
                WHEN pub.partner_id IS NULL THEN 'brand'
                ELSE 'partner'
            END                          AS source,
            SUM(pub.ana_reach)           AS reach
        FROM publications pub
        {where}
        GROUP BY source
    """
    return run_query(sql, params)


def get_adoption(brand_id, partner_id, start_date, end_date):
    where, params = brand_filter(brand_id=brand_id, partner_id=partner_id, start_date=start_date, end_date=end_date)

    # Il denominatore deve coprire lo stesso insieme di partner del numeratore:
    # senza il filtro partner, un tag da 5 partner tutti attivi su un brand da 50
    # darebbe 5/50 = 10% invece di 100%.
    sub_conditions = []
    sub_params = []
    if brand_id:
        sub_conditions.append("brand_id = %s")
        sub_params.append(brand_id)

    partner_ids = normalize_partner_ids(partner_id)
    if partner_ids is not None:
        if partner_ids:
            sub_conditions.append("id = ANY(%s::uuid[])")
            sub_params.append(partner_ids)
        else:
            sub_conditions.append("FALSE")

    sub_where = ("WHERE " + " AND ".join(sub_conditions)) if sub_conditions else ""

    sql = f"""
        SELECT
            COUNT(DISTINCT pub.partner_id)
                FILTER (WHERE pub.partner_id IS NOT NULL)   AS active_partners,
            (
                SELECT COUNT(DISTINCT id)
                FROM partners
                {sub_where}
            )                                               AS total_partners
        FROM publications pub
        {where}
    """
    # i parametri della subquery vanno prima di quelli del WHERE principale
    return run_query(sql, sub_params + params)


def get_weekly_trend(brand_id, partner_id, start_date, end_date):
    where, params = brand_filter(brand_id=brand_id, partner_id=partner_id, start_date=start_date, end_date=end_date)
    sql = f"""
        SELECT
            DATE_TRUNC('week', pub.published_at)  AS week,
            SUM(pub.ana_reach)                    AS reach,
            SUM(pub.ana_impressions)              AS impressions,
            SUM(pub.ana_engagement)               AS engagement
        FROM publications pub
        {where}
        GROUP BY week
        ORDER BY week
    """
    return run_query(sql, params)


def get_content_performance(brand_id, partner_id, start_date, end_date):
    where, params = brand_filter(brand_id=brand_id, partner_id=partner_id, start_date=start_date, end_date=end_date)
    sql = f"""
        SELECT
            pub.post_id,
            LEFT(po.text, 60)            AS title,
            pub.social                   AS channel,
            SUM(pub.ana_reach)           AS reach,
            SUM(pub.ana_impressions)     AS impressions,
            SUM(pub.ana_engagement)      AS engagement,
            COUNT(DISTINCT pub.partner_id)
                FILTER (WHERE pub.partner_id IS NOT NULL) AS n_partners,
            MAX(pub.published_at)        AS published_at
        FROM publications pub
        JOIN posts po ON po.id = pub.post_id
        {where}
        GROUP BY pub.post_id, po.text, pub.social
        ORDER BY reach DESC
    """
    return run_query(sql, params)


def get_partner_stats(brand_id, partner_id, start_date, end_date):
    where, params = brand_filter(brand_id=brand_id, partner_id=partner_id, start_date=start_date, end_date=end_date)
    sql = f"""
        SELECT
            p.id                         AS partner_id,
            p.name                       AS partner_name,
            SUM(pub.ana_reach)           AS reach,
            SUM(pub.ana_impressions)     AS impressions,
            SUM(pub.ana_engagement)      AS engagement,
            COUNT(pub.id)               AS posts,
            MIN(pub.published_at)        AS first_pub,
            MAX(pub.published_at)        AS last_pub
        FROM publications pub
        JOIN partners p ON p.id = pub.partner_id
        {where}
        GROUP BY p.id, p.name
        ORDER BY reach DESC
    """
    return run_query(sql, params)


def get_channel_breakdown(brand_id, partner_id, start_date, end_date):
    where, params = brand_filter(brand_id=brand_id, partner_id=partner_id, start_date=start_date, end_date=end_date)
    sql = f"""
        SELECT
            pub.social                   AS channel,
            SUM(pub.ana_reach)           AS reach,
            SUM(pub.ana_impressions)     AS impressions,
            SUM(pub.ana_engagement)      AS engagement,
            COUNT(pub.id)               AS posts
        FROM publications pub
        {where}
        GROUP BY pub.social
        ORDER BY reach DESC
    """
    return run_query(sql, params)


# colori di default ISUAL usati quando un brand non ha impostazioni
_DEFAULT_COLORS = {
    'primary_color': '#1C2B46',
    'secondary_color': '#F24C27',
    'accent_color': '#F24C27',
    'logo_url': None,
}


def get_brand_settings(brand_id):
    # recupera i colori del brand; se non trovato restituisce i default ISUAL
    df = run_query(
        "SELECT primary_color, secondary_color, accent_color, logo_url"
        " FROM brand_settings WHERE brand_id = %s",
        [brand_id],
    )
    if df.empty:
        return dict(_DEFAULT_COLORS)
    row = df.iloc[0]
    return {
        'primary_color':   row['primary_color'],
        'secondary_color': row['secondary_color'],
        'accent_color':    row['accent_color'],
        'logo_url':        row['logo_url'],
    }


# ordine di default delle KPI card, usato quando non c'è una config per-brand in DB
# (brand_id=None, o brand senza righe in brand_kpi_config). Condiviso da report PDF
# e dashboard live, così il fallback è identico per entrambe le surface.
DEFAULT_KPI_ORDER = [
    {"kpi_key": "reach",                "etichetta": "Network Reach",         "ordine": 1},
    {"kpi_key": "impressions",          "etichetta": "Impressions Totali",    "ordine": 2},
    {"kpi_key": "engagement_total",     "etichetta": "Engagement Totale",     "ordine": 3},
    {"kpi_key": "post_pubblicati",      "etichetta": "Post Pubblicati",       "ordine": 4},
    {"kpi_key": "engagement_rate",      "etichetta": "Engagement Rate",       "ordine": 5},
    {"kpi_key": "amplification_factor", "etichetta": "Amplification Factor",  "ordine": 6},
    {"kpi_key": "network_adoption",     "etichetta": "Network Adoption",      "ordine": 7},
    {"kpi_key": "frequency",            "etichetta": "Frequency",             "ordine": 8},
]


def get_kpi_config(brand_id):
    # configurazione ordinata delle KPI card VISIBILI per un brand (kpi_key + etichetta + ordine).
    # Query parametrizzata, ordinata per 'ordine'. Lista vuota se brand_id assente:
    # il chiamante userà DEFAULT_KPI_ORDER (report "tutti i brand" o brand senza config).
    if not brand_id:
        return []
    df = run_query(
        "SELECT kpi_key, etichetta, ordine"
        " FROM brand_kpi_config"
        " WHERE brand_id = %s AND visibile = TRUE"
        " ORDER BY ordine",
        [brand_id],
    )
    return [
        {"kpi_key": r["kpi_key"], "etichetta": r["etichetta"], "ordine": int(r["ordine"])}
        for _, r in df.iterrows()
    ]


def get_kpi_config_all(brand_id=None):
    # TUTTE le KPI configurate (visibili E nascoste), per il pannello di configurazione.
    # Come get_kpi_config ma SENZA il filtro visibile=TRUE. Ogni riga porta 'visibile'.
    # Config globale: senza brand_id legge da un brand di riferimento qualsiasi (dopo un
    # salvataggio globale tutti i brand hanno le stesse 8 righe). Query parametrizzata.
    if not brand_id:
        ref = run_query("SELECT brand_id FROM brand_kpi_config LIMIT 1")
        if ref.empty:
            # nessuna config in tabella → fallback default, tutte visibili
            return [{**c, "visibile": True} for c in DEFAULT_KPI_ORDER]
        brand_id = str(ref.iloc[0]["brand_id"])

    df = run_query(
        "SELECT kpi_key, etichetta, ordine, visibile"
        " FROM brand_kpi_config"
        " WHERE brand_id = %s"
        " ORDER BY ordine",
        [brand_id],
    )
    if df.empty:
        # brand senza righe (es. brand nuovo) → fallback default, tutte visibili
        return [{**c, "visibile": True} for c in DEFAULT_KPI_ORDER]
    return [
        {
            "kpi_key": r["kpi_key"],
            "etichetta": r["etichetta"],
            "ordine": int(r["ordine"]),
            "visibile": bool(r["visibile"]),
        }
        for _, r in df.iterrows()
    ]


def save_kpi_config_global(kpi_order):
    # riscrive ordine e visibilità delle KPI card su TUTTI i brand (config globale).
    # kpi_order è una lista già VALIDATA di dict {kpi_key, visibile}: l'ordine nella
    # lista determina il campo 'ordine' (1..N consecutivi, riscritti da capo → mai buchi).
    # Tutto in UNA transazione: engine.begin() fa commit se ok, rollback se eccezione.
    # Query parametrizzate (text + dict), nessuna concatenazione.
    engine = get_engine()
    updated = 0
    with engine.begin() as conn:
        for pos, item in enumerate(kpi_order, start=1):
            res = conn.execute(
                text(
                    "UPDATE brand_kpi_config "
                    "SET ordine = :ordine, visibile = :visibile "
                    "WHERE kpi_key = :kpi_key"
                ),
                {"ordine": pos, "visibile": bool(item["visibile"]), "kpi_key": item["kpi_key"]},
            )
            updated += res.rowcount
    return updated


def get_all_brand_settings():
    # tutti i brand con i loro colori; usa i default ISUAL per chi non ha settings
    sql = """
        SELECT b.id, b.name,
               bs.primary_color, bs.secondary_color, bs.accent_color, bs.logo_url
        FROM brands b
        LEFT JOIN brand_settings bs ON b.id = bs.brand_id
        ORDER BY b.name
    """
    df = run_query(sql)
    result = []
    for _, row in df.iterrows():
        result.append({
            'brand_id':        row['id'],
            'brand_name':      row['name'],
            'primary_color':   row['primary_color']   if pd.notna(row['primary_color'])   else '#1C2B46',
            'secondary_color': row['secondary_color'] if pd.notna(row['secondary_color']) else '#F24C27',
            'accent_color':    row['accent_color']    if pd.notna(row['accent_color'])    else '#F24C27',
            'logo_url':        row['logo_url']        if pd.notna(row['logo_url'])        else None,
        })
    return result
