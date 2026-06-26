"""
data_source.py — Layer di accesso ai dati.

Espone la classe :class:`IsualDataSource`, unica responsabile della
connessione al database e del fetching dei dati grezzi (DataFrame pandas).
La connessione usa retry con backoff esponenziale (max 3 tentativi).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


class DBConnectionError(Exception):
    """Sollevata quando tutti i tentativi di connessione al DB falliscono."""


class IsualDataSource:
    """
    Sorgente dati ISUAL: gestisce la connessione Postgres e il fetching grezzo.

    Responsabilità:
        - costruire un engine SQLAlchemy con retry (1s→2s→4s) e singleton cache;
        - eseguire le query SQL e restituire DataFrame pandas non elaborati.

    Non esegue nessun calcolo di KPI e non scrive file.
    """

    def __init__(
        self,
        db_config: dict,
        date_start: datetime,
        date_end: datetime,
        brand_id: str | None = None,
    ) -> None:
        self.db_config: dict = db_config
        self.date_start: datetime = date_start
        self.date_end: datetime = date_end
        self.brand_id: str | None = brand_id
        self.period_days: int = (date_end - date_start).days
        self._engine: Engine | None = None

    # ── Connessione con retry ─────────────────────────────────────────────────
    def _get_engine(self) -> Engine:
        """Restituisce l'engine SQLAlchemy, creandolo con retry se necessario."""
        if self._engine is None:
            self._engine = self._create_engine_with_retry()
        return self._engine

    def _create_engine_with_retry(self, max_attempts: int = 3) -> Engine:
        """Crea l'engine con backoff esponenziale: 1s→2s→4s tra i tentativi."""
        cfg = self.db_config
        url = (
            "postgresql+psycopg2://"
            f"{cfg['user']}:{cfg['password']}"
            f"@{cfg['host']}:{cfg['port']}/{cfg['dbname']}"
            f"?sslmode={cfg['sslmode']}"
        )
        delays = [1, 2, 4]
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                engine = create_engine(url)
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                logger.info("[DB] Connessione stabilita al tentativo %d", attempt)
                return engine
            except Exception as exc:
                last_exc = exc
                ts = datetime.utcnow().isoformat(timespec="seconds")
                logger.warning(
                    "[DB] %s — Tentativo %d/%d fallito: %s",
                    ts, attempt, max_attempts, exc,
                )
                if attempt < max_attempts:
                    delay = delays[attempt - 1]
                    logger.info("[DB] Nuovo tentativo tra %ds...", delay)
                    time.sleep(delay)

        raise DBConnectionError(
            f"Impossibile connettersi al DB dopo {max_attempts} tentativi. "
            f"Ultimo errore: {last_exc}"
        ) from last_exc

    # ── Helper ────────────────────────────────────────────────────────────────
    def _brand_filter(self, alias: str = "pub") -> tuple[str, list]:
        """Costruisce la clausola WHERE e i parametri per il filtro brand/periodo."""
        conditions = [
            f"{alias}.published_at >= %s",
            f"{alias}.published_at < %s",
            f"{alias}.status = 'OK'",
        ]
        params: list = [self.date_start, self.date_end]

        if self.brand_id:
            conditions.append(f"{alias}.brand_id = %s")
            params.append(self.brand_id)

        where = "WHERE " + " AND ".join(conditions)
        return where, params

    def _run(self, sql: str, params: list) -> pd.DataFrame:
        """Esegue una query parametrizzata e restituisce un DataFrame."""
        with self._get_engine().connect() as conn:
            return pd.read_sql(sql, conn, params=tuple(params))

    # ── 1. KPI Overview ───────────────────────────────────────────────────────
    def fetch_overview(self) -> pd.DataFrame:
        """KPI aggregati totali del periodo: reach, impressions, engagement, posts."""
        where, params = self._brand_filter()
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
        return self._run(sql, params)

    # ── 2. Amplification ──────────────────────────────────────────────────────
    def fetch_amplification(self) -> pd.DataFrame:
        """Reach suddiviso tra pubblicazioni brand-only e partner."""
        where, params = self._brand_filter()
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
        return self._run(sql, params)

    # ── 3. Network Adoption ───────────────────────────────────────────────────
    def fetch_adoption(self) -> pd.DataFrame:
        """Partner attivi vs totale partner del brand."""
        where, params = self._brand_filter()
        sql = f"""
            SELECT
                COUNT(DISTINCT pub.partner_id)
                    FILTER (WHERE pub.partner_id IS NOT NULL)   AS active_partners,
                (
                    SELECT COUNT(DISTINCT id)
                    FROM partners
                    {('WHERE brand_id = %s' if self.brand_id else '')}
                )                                               AS total_partners
            FROM publications pub
            {where}
        """
        if self.brand_id:
            params = params + [self.brand_id]
        return self._run(sql, params)

    # ── 4. Performance Trend (weekly) ─────────────────────────────────────────
    def fetch_weekly_trend(self) -> pd.DataFrame:
        """Reach, impressions ed engagement aggregati per settimana."""
        where, params = self._brand_filter()
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
        return self._run(sql, params)

    # ── 5. Content Performance ────────────────────────────────────────────────
    def fetch_content_performance(self) -> pd.DataFrame:
        """Metriche per singolo post, ordinato per reach decrescente."""
        where, params = self._brand_filter()
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
        return self._run(sql, params)

    # ── 6. Partner Leaderboard ────────────────────────────────────────────────
    def fetch_partner_stats(self) -> pd.DataFrame:
        """Metriche per singolo partner, ordinato per reach decrescente."""
        where, params = self._brand_filter()
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
        return self._run(sql, params)

    # ── 7. Brands ─────────────────────────────────────────────────────────────
    def fetch_brands(self) -> pd.DataFrame:
        """Lista di tutti i brand (id, name)."""
        sql = "SELECT id, name FROM brands ORDER BY name"
        return self._run(sql, [])

    # ── 8. Channel Breakdown ──────────────────────────────────────────────────
    def fetch_channel_breakdown(self) -> pd.DataFrame:
        """Metriche aggregate per canale social, ordinato per reach decrescente."""
        where, params = self._brand_filter()
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
        return self._run(sql, params)
