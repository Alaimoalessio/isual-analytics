import io
import base64
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# palette colori ISUAL
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


def fmt_number(n):
    # formatta numeri grandi: 1200000 -> "1.2M", 1200 -> "1.2K"
    if n is None or (isinstance(n, float) and pd.isna(n)):
        return "N/D"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def k_scale(max_val):
    # Decide se un asse va espresso in migliaia, in base al suo valore massimo.
    # Sotto i 1000 la scala K schiaccerebbe tutto a "0K" (un reach di 6 -> 0.006 -> "0K"),
    # quindi si resta sui numeri grezzi.
    # Restituisce (divisore, suffisso_unita, formatter per l'asse) da applicare INSIEME:
    # scalare i dati senza adeguare formatter e suffisso e' esattamente il bug che
    # produceva "0K" ovunque.
    use_k = max_val >= 1000
    divisor = 1000 if use_k else 1
    suffix = " (K)" if use_k else ""
    formatter = mticker.FuncFormatter(lambda x, _: f"{x:.0f}K" if use_k else f"{x:.0f}")
    return divisor, suffix, formatter


def safe(val, default=0):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    return val


def calc_overview(df_overview, df_amplification, df_adoption, days=30, start_date=None, end_date=None,
                   partner_filtered=False):
    if df_overview.empty:
        total_reach = total_impressions = total_engagement = total_posts = 0
    else:
        row = df_overview.iloc[0]
        total_reach       = safe(row["total_reach"])
        total_impressions = safe(row["total_impressions"])
        total_engagement  = safe(row["total_engagement"])
        total_posts       = safe(row["total_posts"])

    # calcolo engagement rate
    er = (total_engagement / total_reach * 100) if total_reach > 0 else 0

    # calcolo frequency
    frequency = (total_impressions / total_reach) if total_reach > 0 else 0

    # calcolo amplification factor
    if df_amplification.empty:
        brand_reach = 0
    else:
        amp_row = df_amplification.set_index("source")["reach"]
        brand_reach = safe(amp_row.get("brand", 0))
    amp_factor = (total_reach / brand_reach) if brand_reach > 0 else 0

    # calcolo network adoption
    if df_adoption.empty:
        active = total_p = 0
    else:
        adp    = df_adoption.iloc[0]
        active  = int(safe(adp["active_partners"]))
        total_p = int(safe(adp["total_partners"]))
    adoption_pct = (active / total_p * 100) if total_p > 0 else 0

    date_range = (
        f"{start_date.strftime('%d/%m/%Y')} – {end_date.strftime('%d/%m/%Y')}"
        if start_date and end_date else ""
    )

    data = {
        "period_label":      f"Ultimi {days} giorni",
        "date_range":        date_range,
        "total_reach":       fmt_number(total_reach),
        "total_impressions": fmt_number(total_impressions),
        "total_engagement":  fmt_number(total_engagement),
        "total_posts":       str(int(total_posts)),
        "engagement_rate":   f"{er:.1f}%",
        "frequency":         f"{frequency:.1f}x",
        "amplification":     f"{amp_factor:.1f}x",
        "adoption_pct":      f"{adoption_pct:.0f}%",
        "active_partners":   str(active),
        "total_partners":    str(total_p),
        "er_raw":            er,
        "amp_raw":           amp_factor,
        "adoption_raw":      adoption_pct,
        "network_scope_na":  partner_filtered,
    }

    # Network Adoption è una metrica calcolata sull'intera rete di partner:
    # con un singolo partner selezionato non va ricalcolata, va mostrata come N/A
    if partner_filtered:
        data["adoption_pct"]    = "N/A"
        data["active_partners"] = "—"
        data["total_partners"]  = "—"

    return data


def _score_content(df):
    # Classifica COMPLETA per content score, senza troncamento: la stessa
    # classifica alimenta sia Top che Worst. Calcolarla una volta sola e' quello
    # che rende la mutua esclusione fra le due tabelle strutturale invece che un
    # filtro da ricordarsi (vedi calc_worst_content).
    # content score = ER_post * 0.6 + reach_normalizzata * 0.4
    if df.empty:
        return df.copy()

    df = df.copy()
    df["reach"]       = df["reach"].fillna(0).astype(float)
    df["engagement"]  = df["engagement"].fillna(0).astype(float)
    df["impressions"] = df["impressions"].fillna(0).astype(float)

    df["er_post"] = df.apply(
        lambda r: r["engagement"] / r["reach"] * 100 if r["reach"] > 0 else 0, axis=1
    )

    # normalizzazione sul pool INTERO, prima di qualsiasi taglio: cosi' lo score di
    # una riga non dipende da quante righe vengono poi mostrate, e Top e Worst sono
    # espressi sulla stessa scala.
    max_reach = df["reach"].max()
    df["reach_norm"] = df["reach"] / max_reach if max_reach > 0 else 0

    df["content_score"] = (df["er_post"] * 0.6) + (df["reach_norm"] * 100 * 0.4)
    # mergesort = stabile: a parita' di score l'ordine resta quello di arrivo dal DB
    # invece di cambiare fra due generazioni dello stesso report.
    df = df.sort_values("content_score", ascending=False, kind="mergesort")

    # rank sulla classifica intera, assegnato PRIMA di ogni slice: Worst mostra le
    # ultime posizioni reali (su 21 contenuti: 21, 20, 19), non una numerazione
    # locale che ripartirebbe da 1 e collidere con quella di Top.
    df["rank"] = range(1, len(df) + 1)

    df["reach_fmt"]      = df["reach"].apply(fmt_number)
    df["impr_fmt"]       = df["impressions"].apply(fmt_number)
    df["engagement_fmt"] = df["engagement"].apply(fmt_number)
    df["er_fmt"]         = df["er_post"].apply(lambda x: f"{x:.1f}%")
    df["score_fmt"]      = df["content_score"].apply(lambda x: f"{x:.1f}")
    df["title_short"]    = df["title"].fillna("—").str[:45]
    df["channel_upper"]  = df["channel"].str.upper()
    # data formattata QUI e non nei template: PDF e dashboard mostrano la stessa
    # stringa, e il client riceve testo invece di un Timestamp non serializzabile.
    # published_at e' MIN(...) dalla query: la prima pubblicazione del gruppo.
    df["date_fmt"]       = pd.to_datetime(df["published_at"]).dt.strftime("%d/%m/%Y")

    return df.reset_index(drop=True)


def calc_content_score(df, top_n=3):
    # i top_n contenuti migliori
    scored = _score_content(df)
    if scored.empty:
        return scored
    return scored.head(top_n).reset_index(drop=True)


def calc_worst_content(df, top_n=3, worst_n=3):
    # I worst_n contenuti peggiori, ESCLUSI i top_n gia' mostrati da
    # calc_content_score. L'esclusione e' uno slice posizionale sulla stessa
    # classifica ordinata (.iloc[top_n:]) e non un anti-join su post_id+channel:
    # non esiste il caso in cui una riga finisca in entrambe le tabelle.
    # Con N righe totali il risultato ha min(worst_n, max(0, N - top_n)) righe:
    # N<=top_n -> tabella vuota, ed e' il comportamento atteso.
    scored = _score_content(df)
    if scored.empty:
        return scored
    # tail() dopo lo slice = le posizioni piu' basse; [::-1] mette la PEGGIORE in cima,
    # senza toccare il rank, che resta quello globale.
    worst = scored.iloc[top_n:].tail(worst_n)
    return worst.iloc[::-1].reset_index(drop=True)


def calc_partner_health(df):
    # health score = 40% activation + 35% regularity + 25% performance
    if df.empty:
        return df.copy()

    df = df.copy()
    df["reach"]      = df["reach"].fillna(0).astype(float)
    df["engagement"] = df["engagement"].fillna(0).astype(float)
    df["posts"]      = df["posts"].fillna(0).astype(float)

    # calcolo engagement rate per partner
    df["er"] = df.apply(
        lambda r: r["engagement"] / r["reach"] * 100 if r["reach"] > 0 else 0, axis=1
    )

    df["activation_score"] = 100.0

    max_posts = df["posts"].max()
    df["regularity_score"] = (df["posts"] / max_posts * 100) if max_posts > 0 else 0

    max_er = df["er"].max()
    df["performance_score"] = (df["er"] / max_er * 100) if max_er > 0 else 0

    df["health_score"] = (
        df["activation_score"] * 0.40
        + df["regularity_score"] * 0.35
        + df["performance_score"] * 0.25
    ).round(0).astype(int)

    median_reach = df["reach"].median()
    median_er    = df["er"].median()

    def classify(row):
        hi_reach = row["reach"] >= median_reach
        hi_er    = row["er"] >= median_er
        if hi_reach and hi_er:      return "Top Performer"
        if hi_reach and not hi_er:  return "Amplifier"
        if not hi_reach and hi_er:  return "Quality Niche"
        return "Weak"

    df["classification"] = df.apply(classify, axis=1)

    def health_label(score):
        if score >= 85: return "VIP"
        if score >= 70: return "Active"
        return "ALERT"

    df["health_label"] = df["health_score"].apply(health_label)
    df["reach_fmt"]    = df["reach"].apply(fmt_number)
    df["er_fmt"]       = df["er"].apply(lambda x: f"{x:.1f}%")
    df["posts_int"]    = df["posts"].astype(int)

    return df.sort_values("health_score", ascending=False).reset_index(drop=True)


def calc_channel_breakdown(df):
    if df.empty:
        return df.copy()

    df = df.copy()
    df["reach"]       = df["reach"].fillna(0).astype(float)
    df["engagement"]  = df["engagement"].fillna(0).astype(float)
    df["impressions"] = df["impressions"].fillna(0).astype(float)
    df["posts"]       = df["posts"].fillna(0).astype(int)

    df["er"] = df.apply(
        lambda r: r["engagement"] / r["reach"] * 100 if r["reach"] > 0 else 0, axis=1
    )
    df["reach_fmt"]     = df["reach"].apply(fmt_number)
    df["impr_fmt"]      = df["impressions"].apply(fmt_number)
    df["eng_fmt"]       = df["engagement"].apply(fmt_number)
    df["er_fmt"]        = df["er"].apply(lambda x: f"{x:.1f}%")
    df["channel_upper"] = df["channel"].str.capitalize()
    return df


def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return b64


def make_trend_chart(df, brand_colors=None):
    # grafico lineare: reach e impressions per settimana
    if df.empty or df["week"].isna().all():
        return ""
        
    primary_color = brand_colors.get('primary_color', COLORS["blue_primary"]) if brand_colors else COLORS["blue_primary"]
    secondary_color = brand_colors.get('secondary_color', COLORS["green_positive"]) if brand_colors else COLORS["green_positive"]

    df = df.copy()
    df["week"] = pd.to_datetime(df["week"])
    df = df.sort_values("week")
    weeks = df["week"].dt.strftime("W%W\n%d/%m")

    fig, ax = plt.subplots(figsize=(10, 3.5))
    fig.patch.set_facecolor("white")

    divisor, unit_suffix, y_formatter = k_scale(max(df["impressions"].max(), df["reach"].max()))

    ax.plot(weeks, df["impressions"] / divisor, color=primary_color,
            linewidth=2.5, marker="o", markersize=5, label=f"Impressions{unit_suffix}")
    ax.plot(weeks, df["reach"] / divisor, color=secondary_color,
            linewidth=2.5, marker="o", markersize=5, label=f"Reach{unit_suffix}")
    ax.fill_between(weeks, df["impressions"] / divisor, alpha=0.08, color=primary_color)
    ax.fill_between(weeks, df["reach"] / divisor, alpha=0.08, color=secondary_color)

    ax.set_facecolor("#F8F9FA")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#DEE2E6")
    ax.tick_params(colors="#6C757D", labelsize=8)
    ax.yaxis.set_major_formatter(y_formatter)
    # legenda FUORI dall'area del grafico: dentro (loc="upper left") copriva punti e linee.
    # bbox_to_anchor y negativo la porta sotto l'asse; -0.22 e non il -0.15 tipico perche'
    # le etichette X sono su due righe ("W19\n05/05") e occupano piu' spazio verticale.
    # ncol=2 tiene le due voci affiancate invece di impilate.
    # Il ritaglio non e' un rischio: fig_to_base64 salva con bbox_inches="tight", che
    # espande l'area salvata fino a comprendere la legenda esterna.
    ax.legend(fontsize=9, framealpha=0, loc="upper center",
              bbox_to_anchor=(0.5, -0.22), ncol=2)
    ax.grid(axis="y", color="#DEE2E6", linewidth=0.5)

    plt.tight_layout()
    return fig_to_base64(fig)


def make_channel_bar_chart(df, brand_colors=None):
    # bar chart orizzontale: reach per canale
    if df.empty:
        return ""
        
    primary_color = brand_colors.get('primary_color', COLORS["blue_primary"]) if brand_colors else COLORS["blue_primary"]

    fig, ax = plt.subplots(figsize=(6, 2.2))
    fig.patch.set_facecolor("white")

    channel_colors = {
        "instagram": "#E1306C",
        "facebook":  "#1877F2",
        "linkedin":  "#0A66C2",
    }
    colors = [channel_colors.get(c.lower(), primary_color) for c in df["channel"]]

    divisor, _, x_formatter = k_scale(df["reach"].max())

    bars = ax.barh(df["channel_upper"], df["reach"] / divisor, color=colors, height=0.5)
    ax.set_facecolor("#F8F9FA")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#DEE2E6")
    ax.tick_params(colors="#6C757D", labelsize=9)
    ax.xaxis.set_major_formatter(x_formatter)

    for bar, val in zip(bars, df["reach"]):
        ax.text(
            bar.get_width() + max(df["reach"]) * 0.01 / divisor,
            bar.get_y() + bar.get_height() / 2,
            fmt_number(val), va="center", fontsize=8,
            color=COLORS["text_secondary"],
        )

    plt.tight_layout()
    return fig_to_base64(fig)
