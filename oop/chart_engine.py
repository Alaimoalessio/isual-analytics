"""
chart_engine.py — Generazione grafici.

Espone la classe :class:`IsualChartEngine`, che produce grafici matplotlib e
li restituisce come stringhe PNG codificate in base64, pronte per l'embedding
nell'HTML. La logica grafica è identica alla versione procedurale (kpi.py).
"""

from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import pandas as pd  # noqa: E402


class IsualChartEngine:
    """
    Motore grafici ISUAL: genera chart matplotlib come PNG base64.

    Responsabilità:
        - generare il trend chart settimanale (reach vs impressions);
        - generare il bar chart orizzontale del reach per canale.

    Usa la palette colori del brand passata al costruttore.
    """

    def __init__(self, colors: dict) -> None:
        """
        Inizializza il motore grafici.

        Args:
            colors: dizionario della brand identity ISUAL (chiavi come
                ``blue_primary``, ``green_positive``, ``text_secondary``, …).
        """
        self.colors: dict = colors

    # ── Helper ────────────────────────────────────────────────────────────────
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
    def _fig_to_base64(fig) -> str:
        """Converte una figura matplotlib in stringa base64 PNG e la chiude."""
        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=150,
            bbox_inches="tight",
            facecolor="white",
            edgecolor="none",
        )
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("utf-8")
        plt.close(fig)
        return b64

    # ── 1. Trend chart ────────────────────────────────────────────────────────
    def trend_chart(self, df: pd.DataFrame) -> str:
        """
        Grafico lineare: Reach e Impressions per settimana.

        Args:
            df: DataFrame da :meth:`IsualDataSource.fetch_weekly_trend`.

        Returns:
            Stringa base64 del PNG, oppure stringa vuota se non ci sono dati.
        """
        if df.empty or df["week"].isna().all():
            return ""

        df = df.copy()
        df["week"] = pd.to_datetime(df["week"])
        df = df.sort_values("week")
        weeks = df["week"].dt.strftime("W%W\n%d/%m")

        fig, ax = plt.subplots(figsize=(10, 3.5))
        fig.patch.set_facecolor("white")

        ax.plot(
            weeks, df["impressions"] / 1000, color=self.colors["blue_primary"],
            linewidth=2.5, marker="o", markersize=5, label="Impressions (K)",
        )
        ax.plot(
            weeks, df["reach"] / 1000, color=self.colors["green_positive"],
            linewidth=2.5, marker="o", markersize=5, label="Reach (K)",
        )
        ax.fill_between(weeks, df["impressions"] / 1000, alpha=0.08,
                        color=self.colors["blue_primary"])
        ax.fill_between(weeks, df["reach"] / 1000, alpha=0.08,
                        color=self.colors["green_positive"])

        ax.set_facecolor("#F8F9FA")
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color("#DEE2E6")
        ax.tick_params(colors="#6C757D", labelsize=8)
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f"{x:.0f}K")
        )
        ax.legend(fontsize=9, framealpha=0, loc="upper left")
        ax.grid(axis="y", color="#DEE2E6", linewidth=0.5)

        plt.tight_layout()
        return self._fig_to_base64(fig)

    # ── 2. Channel bar chart ──────────────────────────────────────────────────
    def channel_bar_chart(self, df: pd.DataFrame) -> str:
        """
        Bar chart orizzontale: reach per canale social.

        Args:
            df: DataFrame elaborato da
                :meth:`IsualKPIEngine.calc_channel_breakdown` (richiede le
                colonne ``channel``, ``channel_upper`` e ``reach``).

        Returns:
            Stringa base64 del PNG, oppure stringa vuota se non ci sono dati.
        """
        if df.empty:
            return ""

        fig, ax = plt.subplots(figsize=(6, 2.2))
        fig.patch.set_facecolor("white")

        channel_colors = {
            "instagram": "#E1306C",
            "facebook":  "#1877F2",
            "linkedin":  "#0A66C2",
        }
        colors = [
            channel_colors.get(c.lower(), self.colors["blue_primary"])
            for c in df["channel"]
        ]

        bars = ax.barh(df["channel_upper"], df["reach"] / 1000,
                       color=colors, height=0.5)
        ax.set_facecolor("#F8F9FA")
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color("#DEE2E6")
        ax.tick_params(colors="#6C757D", labelsize=9)
        ax.xaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f"{x:.0f}K")
        )

        for bar, val in zip(bars, df["reach"]):
            ax.text(
                bar.get_width() + max(df["reach"]) * 0.01 / 1000,
                bar.get_y() + bar.get_height() / 2,
                self._fmt_number(val), va="center", fontsize=8,
                color=self.colors["text_secondary"],
            )

        plt.tight_layout()
        return self._fig_to_base64(fig)
