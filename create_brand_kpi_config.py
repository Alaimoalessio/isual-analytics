"""
create_brand_kpi_config.py
Crea la tabella brand_kpi_config e la popola con la configurazione delle KPI card
per ogni brand (ordine + etichetta + visibilità).
Da eseguire una sola volta (INSERT ON CONFLICT DO NOTHING = idempotente).

L'ambiente si sceglie con --env-file (default .env, cioe' dev).
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

DEFAULT_ENV_FILE = ".env"

# Configurazione delle 8 KPI card, nell'ordine attuale mostrato da dashboard e report PDF.
# Questa mappa è UGUALE per tutti i brand: replica esattamente lo stato hardcoded di oggi.
# (kpi_key, etichetta title-case, ordine)
KPI_CONFIG = [
    ("reach",                "Network Reach",         1),
    ("impressions",          "Impressions Totali",    2),
    ("engagement_total",     "Engagement Totale",     3),
    ("post_pubblicati",      "Post Pubblicati",       4),
    ("engagement_rate",      "Engagement Rate",       5),
    ("amplification_factor", "Amplification Factor",  6),
    ("network_adoption",     "Network Adoption",      7),
    ("frequency",            "Frequency",             8),
]


def carica_env(env_file):
    """
    Carica il file di ambiente indicato e restituisce i parametri di connessione.
    override=True: il file passato esplicitamente vince sulle variabili gia'
    presenti nell'ambiente, altrimenti un export dimenticato in shell
    dirotterebbe lo script su un DB diverso da quello richiesto.
    """
    path = Path(env_file)
    if not path.is_file():
        sys.exit(f"ERRORE: file di ambiente non trovato: {path}")

    load_dotenv(path, override=True)

    mancanti = [k for k in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")
                if not os.getenv(k)]
    if mancanti:
        sys.exit(f"ERRORE: variabili mancanti in {path}: {', '.join(mancanti)}")

    return {
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT", 5432),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "sslmode": os.getenv("DB_SSLMODE", "require"),
    }


def main(env_file=DEFAULT_ENV_FILE):
    params = carica_env(env_file)

    # Ambiente a schermo prima di qualunque scrittura: la password non si stampa
    print(f"=== Ambiente: {env_file} ===")
    print(f"    host={params['host']}  db={params['dbname']}  user={params['user']}\n")

    conn = psycopg2.connect(**params)
    conn.autocommit = False
    cur = conn.cursor()

    print("=== Connessione al DB riuscita ===\n")

    # crea la tabella se non esiste
    # PK composita (brand_id, kpi_key): garantisce unicità e fa da indice per le
    # letture "WHERE brand_id = %s ORDER BY ordine" (brand_id è la colonna più a sinistra).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS brand_kpi_config (
            brand_id    UUID         NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            kpi_key     VARCHAR(50)  NOT NULL,
            etichetta   VARCHAR(100) NOT NULL,
            ordine      SMALLINT     NOT NULL,
            visibile    BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMP    DEFAULT NOW(),
            updated_at  TIMESTAMP    DEFAULT NOW(),
            PRIMARY KEY (brand_id, kpi_key)
        )
    """)
    print("Tabella brand_kpi_config: OK (creata o già esistente)\n")

    # recupera tutti i brand dal DB
    cur.execute("SELECT id, name FROM brands ORDER BY name")
    brand_rows = cur.fetchall()

    print(f"Brand trovati nel DB: {len(brand_rows)}")
    for brand_id, brand_name in brand_rows:
        print(f"  - [{brand_id}] {brand_name}")
    print()

    # inserisce le 8 righe KPI per ogni brand
    inseriti = 0
    saltati = 0

    for brand_id, brand_name in brand_rows:
        print(f"Brand: {brand_name}")
        for kpi_key, etichetta, ordine in KPI_CONFIG:
            cur.execute("""
                INSERT INTO brand_kpi_config
                    (brand_id, kpi_key, etichetta, ordine, visibile)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT (brand_id, kpi_key) DO NOTHING
            """, (
                str(brand_id),
                kpi_key,
                etichetta,
                ordine,
            ))

            # rowcount = 1 se inserito, 0 se saltato per conflitto
            if cur.rowcount == 1:
                inseriti += 1
                print(f"  [OK]   {ordine}. {kpi_key:22s} -> {etichetta}")
            else:
                saltati += 1
                print(f"  [SKIP] {ordine}. {kpi_key:22s} (già presente)")
        print()

    conn.commit()

    print("=== COMPLETATO ===")
    print(f"Inseriti: {inseriti} | Saltati (già presenti): {saltati}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ISUAL Analytics — crea e popola brand_kpi_config")
    parser.add_argument("--env-file", type=str, default=DEFAULT_ENV_FILE, dest="env_file",
                        help="File .env da caricare (default: .env, cioe' dev)")
    args = parser.parse_args()

    main(env_file=args.env_file)
