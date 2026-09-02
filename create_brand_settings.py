"""
create_brand_settings.py
Crea la tabella brand_settings e la popola con palette colori per ogni brand.
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

# Palette colori realistiche, una per ogni brand
# La chiave è una stringa di ricerca (lowercase) presente nel nome del brand
PALETTE_PER_BRAND = [
    {
        "match": "alessia",
        "primary":   "#E63946",  # rosso vivace
        "secondary": "#457B9D",  # blu acciaio
        "accent":    "#F4A261",  # arancio caldo
    },
    {
        "match": "ddallolio+brand",  # l'email viene prima di "ddallolio" semplice
        "primary":   "#6A0572",  # viola profondo
        "secondary": "#AB83A1",  # lilla chiaro
        "accent":    "#F7C59F",  # pesca
    },
    {
        "match": "ddallolio",
        "primary":   "#2B2D42",  # blu notte
        "secondary": "#8D99AE",  # grigio freddo
        "accent":    "#EF233C",  # rosso acceso
    },
    {
        "match": "isual",
        "primary":   "#3B5BDB",  # blu ISUAL (default ufficiale)
        "secondary": "#2F9E44",  # verde ISUAL
        "accent":    "#F08C00",  # arancio ISUAL
    },
    {
        "match": "lorenzo",
        "primary":   "#1B4332",  # verde bosco
        "secondary": "#40916C",  # verde medio
        "accent":    "#D4A017",  # oro
    },
    {
        "match": "magne",
        "primary":   "#264653",  # petrolio scuro
        "secondary": "#2A9D8F",  # teal
        "accent":    "#E9C46A",  # giallo sabbia
    },
    {
        "match": "claudio",
        "primary":   "#3A0CA3",  # indaco
        "secondary": "#7209B7",  # viola elettrico
        "accent":    "#4CC9F0",  # azzurro neon
    },
]


def trova_palette(nome_brand):
    """
    Dato il nome di un brand (stringa), restituisce la palette colori
    cercando una corrispondenza (lowercase) nella lista PALETTE_PER_BRAND.
    Se non trova nulla usa la palette default ISUAL.
    """
    nome_lower = nome_brand.lower()

    for palette in PALETTE_PER_BRAND:
        if palette["match"] in nome_lower:
            return palette

    # fallback: palette ISUAL default
    print(f"  [WARN] Nessuna palette trovata per '{nome_brand}', uso default ISUAL")
    return {
        "primary":   "#3B5BDB",
        "secondary": "#2F9E44",
        "accent":    "#F08C00",
    }


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

    #crea la tabella se non esiste
    cur.execute("""
        CREATE TABLE IF NOT EXISTS brand_settings (
            brand_id        UUID PRIMARY KEY REFERENCES brands(id),
            primary_color   VARCHAR(7) DEFAULT '#3B5BDB',
            secondary_color VARCHAR(7) DEFAULT '#2F9E44',
            accent_color    VARCHAR(7) DEFAULT '#F08C00',
            logo_url        TEXT,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    print("Tabella brand_settings: OK (creata o già esistente)\n")

    #recupera tutti i brand dal DB
    cur.execute("SELECT id, name FROM brands ORDER BY name")
    brand_rows = cur.fetchall()

    print(f"Brand trovati nel DB: {len(brand_rows)}")
    for brand_id, brand_name in brand_rows:
        print(f"  - [{brand_id}] {brand_name}")
    print()

    #inserisce un record per ogni brand
    inseriti = 0
    saltati = 0

    for brand_id, brand_name in brand_rows:
        palette = trova_palette(brand_name)

        cur.execute("""
            INSERT INTO brand_settings
                (brand_id, primary_color, secondary_color, accent_color)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (brand_id) DO NOTHING
        """, (
            str(brand_id),
            palette["primary"],
            palette["secondary"],
            palette["accent"],
        ))

        # rowcount = 1 se inserito, 0 se saltato per conflitto
        if cur.rowcount == 1:
            inseriti += 1
            print(f"  [OK] Inserito: {brand_name}")
            print(f"       primary={palette['primary']}  "
                  f"secondary={palette['secondary']}  "
                  f"accent={palette['accent']}")
        else:
            saltati += 1
            print(f"  [SKIP] Già presente: {brand_name}")

    conn.commit()

    print(f"\n=== COMPLETATO ===")
    print(f"Inseriti: {inseriti} | Saltati (già presenti): {saltati}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ISUAL Analytics — crea e popola brand_settings")
    parser.add_argument("--env-file", type=str, default=DEFAULT_ENV_FILE, dest="env_file",
                        help="File .env da caricare (default: .env, cioe' dev)")
    args = parser.parse_args()

    main(env_file=args.env_file)
