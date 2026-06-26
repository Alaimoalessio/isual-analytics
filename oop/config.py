"""
config.py — Configurazione per il package OOP.

Delega al config radice per evitare duplicazione. Le credenziali vengono
lette da .env nella root del progetto.
"""

import sys
from pathlib import Path

# Aggiunge la root al path così possiamo importare il config radice
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from config import DB_CONFIG, DATE_START, DATE_END, BRAND_ID, COLORS, OUTPUT_PATH, PERIOD_DAYS  # noqa: F401, E402
