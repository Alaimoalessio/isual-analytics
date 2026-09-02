"""
update_logo_urls.py
Aggiorna logo_url in brand_settings per ogni brand presente nel DB.
Da eseguire dopo create_brand_settings.py (la tabella deve già esistere).
"""

import os
import psycopg2
from dotenv import load_dotenv

# Carica variabili d'ambiente dal file .env
load_dotenv()

# Mapping nome brand → path logo
# La chiave è una stringa di ricerca (lowercase) presente nel nome del brand
LOGO_PER_BRAND = [
    {"match": "alessia",        "logo": "static/logos/alessiabrand.png"},
    {"match": "ddallolio+brand","logo": "static/logos/ddallolio.png"},
    {"match": "ddallolio",      "logo": "static/logos/ddallolio.png"},
    {"match": "isual",          "logo": "static/logos/isual.png"},
    {"match": "lorenzo",        "logo": "static/logos/lorenzo orlandi.png"},
    {"match": "magne",          "logo": "static/logos/magne todelete.png"},
    {"match": "claudio",        "logo": "static/logos/claudio uno.png"},
]


def trova_logo(nome_brand):
    # cerca corrispondenza lowercase nella lista; restituisce None se non trovata
    nome_lower = nome_brand.lower()

    for entry in LOGO_PER_BRAND:
        if entry["match"] in nome_lower:
            return entry["logo"]

    print(f"  [WARN] Nessun logo trovato per '{nome_brand}', salto")
    return None


def main():
    # Connessione al database
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )
    conn.autocommit = False
    cur = conn.cursor()

    print("=== Connessione al DB riuscita ===\n")

    # Recupera tutti i brand dal DB
    cur.execute("SELECT id, name FROM brands ORDER BY name")
    brand_rows = cur.fetchall()

    print(f"Brand trovati nel DB: {len(brand_rows)}")
    for brand_id, brand_name in brand_rows:
        print(f"  - [{brand_id}] {brand_name}")
    print()

    # Aggiorna logo_url per ogni brand
    aggiornati = 0
    saltati = 0

    for brand_id, brand_name in brand_rows:
        logo = trova_logo(brand_name)

        if logo is None:
            saltati += 1
            continue

        cur.execute("""
            UPDATE brand_settings
            SET logo_url = %s, updated_at = NOW()
            WHERE brand_id = %s
        """, (logo, str(brand_id)))

        if cur.rowcount == 1:
            aggiornati += 1
            print(f"  [OK] Aggiornato: {brand_name}")
            print(f"       logo_url={logo}")
        else:
            saltati += 1
            print(f"  [SKIP] Nessuna riga in brand_settings per: {brand_name}")

    conn.commit()

    print(f"\n=== COMPLETATO ===")
    print(f"Aggiornati: {aggiornati} | Saltati: {saltati}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
