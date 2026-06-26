![CI](https://github.com/<USERNAME>/<REPO>/actions/workflows/ci.yml/badge.svg)

# ISUAL Analytics — Automated Reporting System

Genera report PDF sulle performance dei brand ISUAL (reach, engagement,
partner health, channel breakdown) a partire da dati PostgreSQL su AWS RDS.
Il sistema produce un PDF esportabile e una dashboard Flask per l'esplorazione
interattiva in tempo reale.

---

## Architettura

```
                  ┌─────────────────────────────────────────┐
                  │          PostgreSQL (AWS RDS)            │
                  │  publications, partners, posts, brands   │
                  └──────────────────┬──────────────────────┘
                                     │ SQLAlchemy + psycopg2
                      ┌──────────────┴──────────────┐
                      │                             │
           ┌──────────▼──────────┐      ┌──────────▼──────────┐
           │   Stack OOP         │      │   Flask Dashboard    │
           │  oop/data_source.py │      │  dashboard/app.py    │
           │  oop/kpi_engine.py  │      │  Jinja2 templates    │
           │  oop/chart_engine.py│      │  REST + browser UI   │
           │  oop/report_builder │      └─────────────────────┘
           └──────────┬──────────┘
                      │ WeasyPrint
           ┌──────────▼──────────┐
           │    PDF Report       │
           │  outputs/*.pdf      │
           └─────────────────────┘
```

---

## Struttura del progetto

```
isual/
├── config.py              # Carica credenziali da .env (python-dotenv)
├── report_oop.py          # Entry point CLI: genera il PDF (--brand-id, --out, --days)
│
├── oop/                   # Stack OOP (4 classi, responsabilità singola)
│   ├── data_source.py     # IsualDataSource: connessione DB + fetch dati, retry logic
│   ├── kpi_engine.py      # IsualKPIEngine: DataFrame → KPI dict
│   ├── chart_engine.py    # IsualChartEngine: KPI → PNG base64
│   ├── report_builder.py  # IsualReportBuilder: KPI + chart → PDF
│   ├── config.py          # Delega a config.py radice (no duplicazione)
│   └── templates/
│       └── report.html    # Template Jinja2 per il PDF
│
├── dashboard/
│   ├── app.py             # Flask app (usa esclusivamente stack OOP)
│   ├── templates/         # HTML Jinja2 della dashboard
│   └── static/            # CSS + JS
│
├── tests/
│   ├── conftest.py        # Fixture DataFrame condivise (no DB reale)
│   ├── test_db.py         # 5 test retry/error handling connessione
│   ├── test_kpi.py        # 17 test IsualKPIEngine (unit, senza DB)
│   └── test_report.py     # 5 test generazione PDF (builder mockato)
│
├── outputs/               # PDF generati (esclusi da git)
├── .env                   # Credenziali reali (escluso da git)
├── .env.example           # Template variabili (incluso in git)
├── requirements.txt       # Dipendenze Python
└── setup.sh               # Setup completo su Mac da zero
```

---

## Quick Start

```bash
# 1. Clona il repo
git clone <repo-url> isual && cd isual

# 2. Setup ambiente (crea venv, installa dipendenze, verifica pango)
bash setup.sh

# 3. Configura le credenziali
cp .env.example .env
# Edita .env con le credenziali reali del database

# 4. Genera il report PDF
venv/bin/python report_oop.py --out outputs/isual_report.pdf

# 5. Avvia la dashboard Flask
venv/bin/python dashboard/app.py
# → http://localhost:5001
```

---

## Configurazione

Tutte le variabili vengono lette da `.env` tramite `python-dotenv`.
Non hardcodare valori in `config.py`.

| Variabile | Descrizione | Esempio |
|---|---|---|
| `DB_HOST` | Hostname AWS RDS | `isual-dev.xxx.rds.amazonaws.com` |
| `DB_PORT` | Porta PostgreSQL | `5432` |
| `DB_NAME` | Nome database | `isual_dev` |
| `DB_USER` | Utente PostgreSQL | `postgres` |
| `DB_PASSWORD` | Password PostgreSQL | `...` |
| `DB_SSLMODE` | Modalità SSL | `require` |

---

## KPI Reference

Tutti i KPI sono calcolati in `oop/kpi_engine.py` a partire dai DataFrame
restituiti dalle query SQL in `oop/data_source.py`.

| KPI | Formula | Fonte dati |
|---|---|---|
| **Total Reach** | `SUM(ana_reach)` | `publications` |
| **Total Impressions** | `SUM(ana_impressions)` | `publications` |
| **Total Engagement** | `SUM(ana_engagement)` | `publications` |
| **Engagement Rate (ER)** | `engagement / reach × 100` | calcolato |
| **Frequency** | `impressions / reach` | calcolato |
| **Amplification Factor** | `total_reach / brand_reach` | `publications GROUP BY source` |
| **Network Adoption** | `active_partners / total_partners × 100` | `publications`, `partners` |
| **Content Score** | `ER_post × 0.6 + reach_norm × 100 × 0.4` | calcolato |
| **Partner Health Score** | `activation×0.4 + regularity×0.35 + performance×0.25` | calcolato (0–100) |
| **Partner Classification** | Quadrante reach/ER vs mediana | Top Performer / Amplifier / Quality Niche / Weak |

---

## Eseguire i test

```bash
# Tutti i test (27 casi)
venv/bin/python -m pytest tests/ -v

# Solo unit test KPI (no I/O)
venv/bin/python -m pytest tests/test_kpi.py -v

# Solo test error handling DB
venv/bin/python -m pytest tests/test_db.py -v

# Solo test generazione PDF
venv/bin/python -m pytest tests/test_report.py -v
```

I test non richiedono un database reale:
- `test_kpi.py` — DataFrame fittizi in memoria, zero I/O
- `test_db.py` — `unittest.mock.patch` su `create_engine` e `time.sleep`
- `test_report.py` — `IsualDataSource` mockato, WeasyPrint genera PDF reale in `tempfile`

---

## Note tecniche

**Circular import `sys.path`**: `oop/config.py` delega al `config.py` radice.
Per evitare che Python trovi `oop/config.py` prima del radice, la root viene
inserita in `sys.path` prima di `oop/`. Stesso fix applicato in `dashboard/app.py`
e `report_oop.py`.

**Latenza connessione DB**: la prima connessione a AWS RDS include SSL handshake
e può impiegare 2–4 secondi. `IsualDataSource` usa un retry con backoff esponenziale
(1s→2s→4s, max 3 tentativi). La dashboard mantiene un engine singleton per i check
di salute (`/api/db-status`, `/api/health`) per evitare overhead ad ogni richiesta.

**WeasyPrint richiede pango**: su Mac installare via `brew install pango`.
Su Linux: `libpango-1.0-0 libpangocairo-1.0-0` via apt. `setup.sh` verifica
automaticamente la presenza.
