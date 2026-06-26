#!/usr/bin/env bash
# setup.sh — Prepara l'ambiente di sviluppo ISUAL su Mac.
# Uso: bash setup.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/venv"

ok()   { echo "  ✓ $*"; }
fail() { echo "  ✗ $*"; }
info() { echo "→ $*"; }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   ISUAL Analytics — Setup ambiente"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. Virtualenv ──────────────────────────────────────────────────────────
info "1. Virtualenv Python"
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
    ok "Creato venv in $VENV"
else
    ok "venv già esistente"
fi

# ── 2. Dipendenze Python ───────────────────────────────────────────────────
info "2. Installazione dipendenze Python"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$ROOT/requirements.txt"
ok "requirements.txt installato"

# ── 3. Pango (WeasyPrint) ─────────────────────────────────────────────────
info "3. Verifica Pango (richiesto da WeasyPrint)"
if command -v brew &>/dev/null; then
    if brew list pango &>/dev/null 2>&1; then
        ok "pango già installato"
    else
        echo "   pango non trovato — installazione in corso..."
        brew install pango
        ok "pango installato"
    fi
else
    fail "Homebrew non trovato — installa Homebrew da https://brew.sh e poi installa pango"
fi

# ── 4. File .env ───────────────────────────────────────────────────────────
info "4. Verifica .env"
if [ -f "$ROOT/.env" ]; then
    ok ".env presente"
else
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo ""
    echo "  ⚠️  ATTENZIONE: .env.example copiato in .env"
    echo "      Apri $ROOT/.env e sostituisci i valori placeholder"
    echo "      con le credenziali reali del database."
    echo ""
fi

# ── 5. Riepilogo ───────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   Riepilogo dipendenze"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

check() {
    local label="$1"; shift
    if "$@" &>/dev/null 2>&1; then ok "$label"; else fail "$label"; fi
}

check "Python venv"    test -f "$VENV/bin/python"
check "python-dotenv"  "$VENV/bin/python" -c "import dotenv"
check "SQLAlchemy"     "$VENV/bin/python" -c "import sqlalchemy"
check "pandas"         "$VENV/bin/python" -c "import pandas"
check "WeasyPrint"     "$VENV/bin/python" -c "import weasyprint"
check "matplotlib"     "$VENV/bin/python" -c "import matplotlib"
check "Flask"          "$VENV/bin/python" -c "import flask"
check "pytest"         "$VENV/bin/python" -c "import pytest"
check "pango (sistema)" command -v pango-view
check ".env configurato" test -f "$ROOT/.env"

echo ""
echo "Pronto. Comandi disponibili:"
echo "  venv/bin/python report_oop.py --out outputs/isual_report.pdf"
echo "  venv/bin/python dashboard/app.py"
echo "  venv/bin/python -m pytest tests/ -v"
echo ""
