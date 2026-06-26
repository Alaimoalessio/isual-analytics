"""
config.py — Configurazione globale del progetto.

Le credenziali DB vengono lette da .env (mai hardcoded).
Copia .env.example → .env e compila i valori reali.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

# Carica .env dalla root del progetto (funziona ovunque si lanci lo script)
load_dotenv(Path(__file__).resolve().parent / ".env")

# ── Database ──────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":    os.environ["DB_HOST"],
    "port":    int(os.getenv("DB_PORT", "5432")),
    "dbname":  os.environ["DB_NAME"],
    "user":    os.environ["DB_USER"],
    "password":os.environ["DB_PASSWORD"],
    "sslmode": os.getenv("DB_SSLMODE", "require"),
}

# ── Periodo di analisi ────────────────────────────────────────────────────────
PERIOD_DAYS = 30
DATE_END    = datetime.utcnow()
DATE_START  = DATE_END - timedelta(days=PERIOD_DAYS)

# ── Filtri opzionali (None = tutti) ──────────────────────────────────────────
BRAND_ID = None

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_PATH = "outputs/isual_report.pdf"

# ── Brand identity ISUAL ──────────────────────────────────────────────────────
COLORS = {
    "blue_primary":   "#3B5BDB",
    "blue_dark":      "#1A1A2E",
    "red_brand":      "#C0392B",
    "green_positive": "#2F9E44",
    "orange_warning": "#F08C00",
    "red_alert":      "#E03131",
    "bg_page":        "#F1F3F5",
    "bg_card":        "#FFFFFF",
    "text_primary":   "#1A1A2E",
    "text_secondary": "#6C757D",
}
