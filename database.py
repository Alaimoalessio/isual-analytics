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


# ── Partner canonici ────────────────────────────────────────────────────────
# L'app di terzi permette di ricreare un partner con lo stesso nome nello stesso
# brand (partners ha solo PRIMARY KEY (id), nessun vincolo su (brand_id, name)),
# e in produzione le righe non vengono mai cancellate. Risultato: nomi duplicati,
# quasi sempre con una riga popolata e le altre vuote.
#
# Criterio del canonico, per gruppo (brand_id, name):
#   1. piu' pubblicazioni  — "il piu' popolato", il record realmente in uso;
#   2. version piu' alta   — spareggio quando nessuna riga ha pubblicazioni;
#   3. created_at piu' vecchio — a parita', l'originale e non la ricreazione;
#   4. id                  — determinismo assoluto, mai un risultato ambiguo.
# Si contano TUTTE le pubblicazioni, non solo status='OK': una riga con sole
# pubblicazioni non-OK e' comunque il record reale rispetto a un duplicato vuoto.
#
# La CTE e' deliberatamente SENZA PARAMETRI (calcola i canonici di tutti i brand,
# il filtro per brand resta separato): get_adoption costruisce i suoi parametri
# con un ordine posizionale fragile, e un frammento parametrico costringerebbe a
# rimaneggiarlo.
PARTNERS_CANONICI = """
WITH canonici AS (
  SELECT DISTINCT ON (pa.brand_id, pa.name)
         pa.brand_id, pa.name, pa.id AS canonical_id
  FROM partners pa
  LEFT JOIN publications pu ON pu.partner_id = pa.id
  GROUP BY pa.id, pa.brand_id, pa.name, pa.version, pa.created_at
  ORDER BY pa.brand_id, pa.name,
           COUNT(pu.id)  DESC,
           pa.version    DESC,
           pa.created_at ASC,
           pa.id
)
"""

# Condizione di appartenenza ai canonici, nello stesso formato {alias} usato dalle
# altre condizioni di scope: va aggiunta alla LISTA condivisa, mai applicata a mano
# a un solo lato di una query (vedi l'invariante di get_adoption).
CONDIZIONE_CANONICO = "{alias}id IN (SELECT canonical_id FROM canonici)"


def run_query(sql, params=None):
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=tuple(params) if params else None)


def get_brands():
    return run_query("SELECT id, name FROM brands ORDER BY name")


def get_partners_for_filter(brand_id=None):
    # solo i partner canonici: le copie vuote sono indistinguibili nella tendina
    # (l'utente vede solo il nome) e selezionarle dava KPI a zero senza spiegazione.
    # Le righe restano nel DB, vengono solo escluse dalla selezione.
    sql = PARTNERS_CANONICI + " SELECT id, name FROM partners WHERE " + \
          CONDIZIONE_CANONICO.format(alias="")
    params = []
    if brand_id:
        sql += " AND brand_id = %s"
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
    #
    # I collegamenti puntano all'id che l'app di terzi aveva sottomano al momento del
    # tag, che puo' essere una copia vuota: il tag 'ggg' era legato al duplicato senza
    # pubblicazioni e non al partner reale, quindi il filtro mostrava zero. Qui i
    # collegamenti vengono RIMAPPATI sul canonico del gruppo, non filtrati: filtrare
    # lascerebbe il tag senza alcun partner (peggio di adesso), rimappare lo porta sul
    # record giusto. Il DISTINCT e' necessario, non decorativo: un tag legato sia alla
    # riga canonica sia a una copia (caso 'Prosciutto') le collassa sullo stesso id.
    sql = PARTNERS_CANONICI + """
        SELECT DISTINCT c.canonical_id AS partner_id
        FROM partners_tags pt
        JOIN tags t     ON t.id = pt.tag_id
        JOIN partners p ON p.id = pt.partner_id
        JOIN canonici c ON c.brand_id = p.brand_id AND c.name = p.name
        WHERE pt.tag_id = %s
          AND t.deleted = false
    """
    df = run_query(sql, [tag_id])
    return [str(pid) for pid in df["partner_id"].tolist()]


def get_partner_ids_by_target(target_id):
    # stessa rimappatura sui canonici di get_partner_ids_by_tag, per simmetria.
    # Oggi e' un no-op verificato (nessun target e' collegato a un partner non
    # canonico), ma senza di essa Tag e Target si comporterebbero in modo diverso
    # davanti allo stesso dato: un target assegnato a una copia vuota mostrerebbe
    # zero mentre il tag equivalente funziona.
    sql = PARTNERS_CANONICI + """
        SELECT DISTINCT c.canonical_id AS partner_id
        FROM partners_targets pt
        JOIN targets t  ON t.id = pt.target_id
        JOIN partners p ON p.id = pt.partner_id
        JOIN canonici c ON c.brand_id = p.brand_id AND c.name = p.name
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

    # Numeratore e denominatore devono descrivere lo STESSO insieme di partner, altrimenti
    # la percentuale e' priva di senso. Due modi in cui divergevano:
    #  - denominatore troppo largo: un tag da 5 partner tutti attivi su un brand da 50
    #    dava 5/50 = 10% invece di 100%;
    #  - numeratore troppo largo: publications contiene partner_id di partner cancellati
    #    (orfani), contati fra gli attivi ma assenti dal denominatore -> 3/1 = 300%.
    # Da qui l'unica condizione di appartenenza, costruita una volta e applicata a
    # entrambi i lati: l'invariante attivi <= totali vale per costruzione.
    # I duplicati vuoti gonfiavano il denominatore: Terme di Cervia dava 5/9 = 56%
    # con 9 righe partners per 6 nomi reali. Contano solo i canonici — e la condizione
    # va QUI, nella lista condivisa, cosi' numeratore e denominatore la ereditano
    # entrambi. Applicarla a un solo lato ricreerebbe la divergenza descritta sopra.
    # Nessun parametro: si formatta da se' su entrambi i lati (vedi CONDIZIONE_CANONICO).
    scope_conditions = [CONDIZIONE_CANONICO]
    scope_params = []
    if brand_id:
        scope_conditions.append("{alias}brand_id = %s")
        scope_params.append(brand_id)

    partner_ids = normalize_partner_ids(partner_id)
    if partner_ids is not None:
        if partner_ids:
            scope_conditions.append("{alias}id = ANY(%s::uuid[])")
            scope_params.append(partner_ids)
        else:
            scope_conditions.append("FALSE")

    # denominatore: COUNT su partners, colonne non qualificate
    sub_where = ("WHERE " + " AND ".join(c.format(alias="") for c in scope_conditions)) if scope_conditions else ""

    # numeratore: le stesse condizioni applicate al partner della pubblicazione, via EXISTS.
    # Senza questo, un partner_id orfano gonfia gli attivi.
    exists_where = " AND ".join(["p.id = pub.partner_id"] + [c.format(alias="p.") for c in scope_conditions])

    # la CTE dei canonici prefissa l'intera query: e' cosi' visibile sia all'EXISTS
    # del numeratore sia alla subquery del denominatore.
    sql = PARTNERS_CANONICI + f"""
        SELECT
            COUNT(DISTINCT pub.partner_id) FILTER (
                WHERE pub.partner_id IS NOT NULL
                  AND EXISTS (SELECT 1 FROM partners p WHERE {exists_where})
            )                                               AS active_partners,
            (
                SELECT COUNT(DISTINCT id)
                FROM partners
                {sub_where}
            )                                               AS total_partners
        FROM publications pub
        {where}
    """
    # ordine dei parametri = ordine di apparizione nella SQL:
    # EXISTS (numeratore) -> subquery (denominatore) -> WHERE principale
    return run_query(sql, scope_params + scope_params + params)


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

# palette ufficiale ISUAL, applicata a TUTTI i brand quando i colori per-brand
# sono disattivati via BRAND_COLORS_ENABLED=false. Coincide con i DEFAULT delle
# colonne di brand_settings e con la palette "isual" di create_brand_settings.py.
# NB: diversa da _DEFAULT_COLORS (fallback per un brand SENZA riga in tabella).
# Solo i tre colori: il logo resta quello del DB, il flag riguarda i colori.
_ISUAL_COLORS = {
    'primary_color': '#3B5BDB',
    'secondary_color': '#2F9E44',
    'accent_color': '#F08C00',
}


def brand_colors_enabled():
    # BRAND_COLORS_ENABLED=false forza la palette ISUAL ignorando brand_settings
    # (filtro in lettura, reversibile: i dati nel DB non vengono toccati).
    # Assente o qualsiasi valore != "false" (case-insensitive) = attivo, così il
    # comportamento storico resta invariato senza dover impostare nulla.
    return os.getenv('BRAND_COLORS_ENABLED', 'true').strip().lower() != 'false'


def get_brand_settings(brand_id):
    # recupera i colori del brand; se non trovato restituisce i default ISUAL
    df = run_query(
        "SELECT primary_color, secondary_color, accent_color, logo_url"
        " FROM brand_settings WHERE brand_id = %s",
        [brand_id],
    )
    if df.empty:
        settings = dict(_DEFAULT_COLORS)
    else:
        row = df.iloc[0]
        settings = {
            'primary_color':   row['primary_color'],
            'secondary_color': row['secondary_color'],
            'accent_color':    row['accent_color'],
            'logo_url':        row['logo_url'],
        }
    if not brand_colors_enabled():
        # flag spento: forza la palette ISUAL, lascia intatto il logo
        settings.update(_ISUAL_COLORS)
    return settings


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
    force_isual = not brand_colors_enabled()
    result = []
    for _, row in df.iterrows():
        entry = {
            'brand_id':        row['id'],
            'brand_name':      row['name'],
            'primary_color':   row['primary_color']   if pd.notna(row['primary_color'])   else '#1C2B46',
            'secondary_color': row['secondary_color'] if pd.notna(row['secondary_color']) else '#F24C27',
            'accent_color':    row['accent_color']    if pd.notna(row['accent_color'])    else '#F24C27',
            'logo_url':        row['logo_url']        if pd.notna(row['logo_url'])        else None,
        }
        if force_isual:
            # flag spento: forza la palette ISUAL, lascia intatto il logo
            entry.update(_ISUAL_COLORS)
        result.append(entry)
    return result
