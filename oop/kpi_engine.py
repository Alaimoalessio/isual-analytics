"""
kpi_engine.py — Motore di calcolo dei KPI.

Espone la classe :class:`IsualKPIEngine`, che trasforma i DataFrame grezzi
forniti da :class:`~data_source.IsualDataSource` in KPI e tabelle pronte per
il template. Nessun SQL, nessun I/O su file. Le formule sono identiche alla
versione procedurale (kpi.py).
"""

from __future__ import annotations

import pandas as pd

from data_source import IsualDataSource


class IsualKPIEngine:
    """
    Motore KPI ISUAL: calcola metriche e tabelle a partire dai DataFrame.

    Responsabilità:
        - calcolare i KPI di overview (reach, ER, amplification, adoption, …);
        - calcolare Content Score, Partner Health Score e breakdown per canale.

    Non esegue query SQL e non scrive file: riceve i dati tramite la
    :class:`IsualDataSource` passata al costruttore.
    """

    def __init__(self, datasource: IsualDataSource) -> None:
        """
        Inizializza il motore KPI.

        Args:
            datasource: sorgente dati da cui leggere i DataFrame grezzi.
        """
        self.datasource: IsualDataSource = datasource

    # ── Helper di formattazione ───────────────────────────────────────────────
    @staticmethod
    def _fmt_number(n: float | None) -> str:
        """Formatta numeri grandi: 1_200_000 → '1.2M', 1_200 → '1.2K'."""
        if n is None or (isinstance(n, float) and pd.isna(n)):
            return "N/D"
        n = int(n)
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)

    @staticmethod
    def _safe(val, default=0):
        """Restituisce ``default`` se il valore è None/NaN, altrimenti il valore."""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return default
        return val

    # ── 1. Overview KPI ───────────────────────────────────────────────────────
    def calc_overview(self) -> dict:
        """
        Calcola tutti i KPI della sezione Overview leggendo i dati dalla sorgente.

        Gestisce in modo robusto i DataFrame vuoti restituendo valori a zero.

        Returns:
            dict con i valori formattati (più i valori grezzi ``*_raw``) per il
            template.
        """
        ds = self.datasource
        df_overview = ds.fetch_overview()
        df_amplification = ds.fetch_amplification()
        df_adoption = ds.fetch_adoption()

        # Overview: la query aggregata restituisce sempre 1 riga, ma proteggiamo
        # comunque il caso DataFrame vuoto.
        if df_overview.empty:
            total_reach = total_impressions = total_engagement = total_posts = 0
        else:
            row = df_overview.iloc[0]
            total_reach = self._safe(row["total_reach"])
            total_impressions = self._safe(row["total_impressions"])
            total_engagement = self._safe(row["total_engagement"])
            total_posts = self._safe(row["total_posts"])

        # Engagement Rate
        er = (total_engagement / total_reach * 100) if total_reach > 0 else 0

        # Frequency (content pressure)
        frequency = (total_impressions / total_reach) if total_reach > 0 else 0

        # Amplification Factor
        if df_amplification.empty:
            brand_reach = 0
        else:
            amp_row = df_amplification.set_index("source")["reach"]
            brand_reach = self._safe(amp_row.get("brand", 0))
        amp_factor = (total_reach / brand_reach) if brand_reach > 0 else 0

        # Network Adoption
        if df_adoption.empty:
            active = total_p = 0
        else:
            adp = df_adoption.iloc[0]
            active = int(self._safe(adp["active_partners"]))
            total_p = int(self._safe(adp["total_partners"]))
        adoption_pct = (active / total_p * 100) if total_p > 0 else 0

        return {
            "period_label":      f"Ultimi {ds.period_days} giorni",
            "date_range":        f"{ds.date_start.strftime('%d/%m/%Y')} – {ds.date_end.strftime('%d/%m/%Y')}",
            "total_reach":       self._fmt_number(total_reach),
            "total_impressions": self._fmt_number(total_impressions),
            "total_engagement":  self._fmt_number(total_engagement),
            "total_posts":       str(int(total_posts)),
            "engagement_rate":   f"{er:.1f}%",
            "frequency":         f"{frequency:.1f}x",
            "amplification":     f"{amp_factor:.1f}x",
            "adoption_pct":      f"{adoption_pct:.0f}%",
            "active_partners":   str(active),
            "total_partners":    str(total_p),
            # raw per logica condizionale nel template
            "er_raw":            er,
            "amp_raw":           amp_factor,
            "adoption_raw":      adoption_pct,
        }

    # ── 2. Content Score ──────────────────────────────────────────────────────
    def calc_content_score(self, df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
        """
        Content Score = (ER_post × 0.6) + (Reach_norm × 100 × 0.4).

        Args:
            df: DataFrame da :meth:`IsualDataSource.fetch_content_performance`.
            top_n: numero massimo di post da restituire.

        Returns:
            DataFrame ordinato per content_score, troncato a ``top_n`` righe e
            arricchito con le colonne di display. Vuoto se l'input è vuoto.
        """
        if df.empty:
            return df.copy()

        df = df.copy()
        df["reach"] = df["reach"].fillna(0).astype(float)
        df["engagement"] = df["engagement"].fillna(0).astype(float)
        df["impressions"] = df["impressions"].fillna(0).astype(float)

        # ER per post
        df["er_post"] = df.apply(
            lambda r: r["engagement"] / r["reach"] * 100 if r["reach"] > 0 else 0,
            axis=1,
        )

        # Reach normalizzata (0–1)
        max_reach = df["reach"].max()
        df["reach_norm"] = df["reach"] / max_reach if max_reach > 0 else 0

        # Content Score
        df["content_score"] = (df["er_post"] * 0.6) + (df["reach_norm"] * 100 * 0.4)

        # Classifica
        df = df.sort_values("content_score", ascending=False).head(top_n)

        # Formattazione display
        df["reach_fmt"] = df["reach"].apply(self._fmt_number)
        df["impr_fmt"] = df["impressions"].apply(self._fmt_number)
        df["engagement_fmt"] = df["engagement"].apply(self._fmt_number)
        df["er_fmt"] = df["er_post"].apply(lambda x: f"{x:.1f}%")
        df["score_fmt"] = df["content_score"].apply(lambda x: f"{x:.1f}")
        df["title_short"] = df["title"].fillna("—").str[:45]
        df["channel_upper"] = df["channel"].str.upper()

        return df.reset_index(drop=True)

    # ── 3. Partner Health Score & Leaderboard ─────────────────────────────────
    def calc_partner_health(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Health Score = 40% Activation + 35% Regularity + 25% Performance.

        Args:
            df: DataFrame da :meth:`IsualDataSource.fetch_partner_stats`.

        Returns:
            DataFrame ordinato per health_score, con classificazione,
            etichetta e colonne di display. Vuoto se l'input è vuoto.
        """
        if df.empty:
            return df.copy()

        df = df.copy()
        df["reach"] = df["reach"].fillna(0).astype(float)
        df["engagement"] = df["engagement"].fillna(0).astype(float)
        df["posts"] = df["posts"].fillna(0).astype(float)

        # ER per partner
        df["er"] = df.apply(
            lambda r: r["engagement"] / r["reach"] * 100 if r["reach"] > 0 else 0,
            axis=1,
        )

        # Activation: tutti i partner in questo DF hanno almeno 1 post → 100
        df["activation_score"] = 100.0

        # Regularity: normalizzata sul max post
        max_posts = df["posts"].max()
        df["regularity_score"] = (df["posts"] / max_posts * 100) if max_posts > 0 else 0

        # Performance: ER normalizzato
        max_er = df["er"].max()
        df["performance_score"] = (df["er"] / max_er * 100) if max_er > 0 else 0

        # Health Score pesato
        df["health_score"] = (
            df["activation_score"] * 0.40
            + df["regularity_score"] * 0.35
            + df["performance_score"] * 0.25
        ).round(0).astype(int)

        # Classificazione quadrante
        median_reach = df["reach"].median()
        median_er = df["er"].median()

        def classify(row) -> str:
            hi_reach = row["reach"] >= median_reach
            hi_er = row["er"] >= median_er
            if hi_reach and hi_er:
                return "Top Performer"
            if hi_reach and not hi_er:
                return "Amplifier"
            if not hi_reach and hi_er:
                return "Quality Niche"
            return "Weak"

        df["classification"] = df.apply(classify, axis=1)

        # Etichetta Health
        def health_label(score: int) -> str:
            if score >= 85:
                return "VIP"
            if score >= 70:
                return "Active"
            return "ALERT"

        df["health_label"] = df["health_score"].apply(health_label)

        # Formattazione display
        df["reach_fmt"] = df["reach"].apply(self._fmt_number)
        df["er_fmt"] = df["er"].apply(lambda x: f"{x:.1f}%")
        df["posts_int"] = df["posts"].astype(int)

        return df.sort_values("health_score", ascending=False).reset_index(drop=True)

    # ── 4. Channel Breakdown ──────────────────────────────────────────────────
    def calc_channel_breakdown(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Arricchisce il breakdown per canale con ER e colonne di display.

        Args:
            df: DataFrame da :meth:`IsualDataSource.fetch_channel_breakdown`.

        Returns:
            DataFrame con ER calcolato e colonne formattate. Vuoto se l'input
            è vuoto.
        """
        if df.empty:
            return df.copy()

        df = df.copy()
        df["reach"] = df["reach"].fillna(0).astype(float)
        df["engagement"] = df["engagement"].fillna(0).astype(float)
        df["impressions"] = df["impressions"].fillna(0).astype(float)
        df["posts"] = df["posts"].fillna(0).astype(int)

        df["er"] = df.apply(
            lambda r: r["engagement"] / r["reach"] * 100 if r["reach"] > 0 else 0,
            axis=1,
        )
        df["reach_fmt"] = df["reach"].apply(self._fmt_number)
        df["impr_fmt"] = df["impressions"].apply(self._fmt_number)
        df["eng_fmt"] = df["engagement"].apply(self._fmt_number)
        df["er_fmt"] = df["er"].apply(lambda x: f"{x:.1f}%")
        df["channel_upper"] = df["channel"].str.capitalize()
        return df
