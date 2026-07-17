# Diagnosi Bug — Sessione Read-Only

**Data:** 2026-07-02
**Modalità:** Diagnostica, nessun file di codice modificato.

> **AGGIORNAMENTO 2026-07-17 — BUG 1 RISOLTO. Il codice citato sotto è storico.**
>
> Le righe di `kpi.py` riportate in questo documento (`label="Impressions (K)"`,
> formatter `f"{x:.0f}K"` incondizionato) **non esistono più**. Attenzione: leggere
> la diagnosi senza questa nota porta a diagnosticare un bug già chiuso.
>
> - `make_trend_chart`: risolto nel refactor **1e5d08c** con la condizione `use_k`
>   (niente scala K sotto 1000, suffisso legenda e formatter allineati).
> - `make_channel_bar_chart`: il fix **non era stato esteso qui**, quindi l'asse X
>   ha continuato a mostrare "0K" fino al 2026-07-17. Risolto allineandolo alla
>   stessa logica, ora estratta nell'helper condiviso `k_scale()` (`kpi.py`) —
>   la condizione vive in un punto solo, perché la duplicazione è ciò che ha
>   generato il bug.
>
> **BUG 2 resta aperto e la diagnosi sotto è tuttora valida.**

## Nota preliminare — discrepanza di architettura

Il contesto della richiesta descrive un'architettura a 4 classi (`IsualDataSource`,
`IsualKPIEngine`, `IsualChartEngine`, `IsualReportBuilder`) dentro `oop/`. Quella
directory **non esiste più** nel working tree corrente — risulta cancellata
(`git status` mostra `D oop/*.py`, commit recenti "chore: cleanup and rename" /
"chore: cleanup"). Il codice attuale è stato riscritto in stile procedurale:

- `database.py` — query SQL (equivalente funzionale di `IsualDataSource`)
- `kpi.py` — calcolo KPI e generazione grafici (equivalente di `IsualKPIEngine` + `IsualChartEngine`)
- `report.py` — orchestrazione e render Jinja2/WeasyPrint (equivalente di `IsualReportBuilder`)

Non esiste **nessuna classe** nel codice attuale (`grep -n "^class "` su tutti i
moduli root: zero risultati). La diagnosi sotto fa riferimento ai file e alle
righe reali (`kpi.py`, `database.py`, `report.py`, `templates/report.html`).

Ho inoltre eseguito query **read-only (SELECT)** dirette contro il DB dev
(`isual-dev` su RDS, credenziali da `.env` già presenti nel repo) per verificare
i dati reali, dato che la dimensione del dataset demo è determinante per
entrambi i bug. Nessuna scrittura è stata effettuata.

---

## BUG 1 — Asse Y "Performance Trend" mostra sempre 0K

### Root cause

File: `kpi.py`, funzione `make_trend_chart` (righe 216-248).

```python
232  ax.plot(weeks, df["impressions"] / 1000, color=primary_color,
233          linewidth=2.5, marker="o", markersize=5, label="Impressions (K)")
234  ax.plot(weeks, df["reach"] / 1000, color=secondary_color,
235          linewidth=2.5, marker="o", markersize=5, label="Reach (K)")
```

I valori vengono divisi per 1000 **prima** di essere passati a `ax.plot` — sono
già in scala "K" quando matplotlib genera i tick.

```python
243  ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}K"))
```

Il formatter usa **zero cifre decimali** (`:.0f`) senza alcuna soglia minima.

Stesso pattern (identico difetto, non ancora sintomatico nella demo) presente
anche in `make_channel_bar_chart`:
- riga 268: `df["reach"] / 1000` passato a `barh`
- riga 273: `mticker.FuncFormatter(lambda x, _: f"{x:.0f}K")` sull'asse X

### Verifica con dati reali (query SELECT read-only su DB dev, finestra 90gg)

```
db.get_weekly_trend(...) →
   week          reach  impressions
   2026-05-18       1        2
   2026-06-15       7       24
```

`impressions / 1000` = `[0.002, 0.024]` → formattato con `:.0f` → `"0K"`, `"0K"`.

Soglia matematica: perché `:.0f` produca "1K" invece di "0K" serve un valore
grezzo ≥ 500 (0.5 dopo la divisione arrotonda a 1). Qualunque somma settimanale
sotto 500 — cosa garantita nel dataset demo attuale, dove i totali sono a
singola/doppia cifra — produrrà sempre "0K" su ogni etichetta. Non esiste nel
codice alcuna logica di scaling dinamico (es. scegliere unità raw vs K vs M in
base a `df["impressions"].max()`); la divisione per 1000 e il formato a 0
decimali sono hardcoded e incondizionati.

### Tick values vs. solo testo label

Entrambi coinvolti, ma il problema pratico è la label:
- i valori passati a `ax.plot` sono già le piccole frazioni (es. 0.002), quindi
  matplotlib genera i tick internamente in quel range 0–0.03;
- il formatter poi tronca ogni precisione sub-unitaria con `:.0f`, stampando
  "0K" su ogni tick indipendentemente da quale tick sia.
- Le linee del grafico si disegnano correttamente (differenze relative tra
  reach/impressions preservate) — coerente con il sintomo riportato.
- Il DataFrame grezzo (`df_trend`) che alimenta il grafico non viene mutato:
  la divisione per 1000 avviene su una copia locale dentro `ax.plot(...)`, non
  sull'oggetto condiviso. Nessun altro punto del report (KPI overview, tabelle)
  è affetto — è isolato al percorso di rendering del grafico.

### Severità

Solo estetico/visualizzazione. I dati sottostanti sono corretti; il difetto è
interamente nel formatter dell'asse e nella scala hardcoded a monte di esso.

### Rischio stimato di un fix mirato

**Basso.** Il difetto è contenuto in `make_trend_chart` (kpi.py:216-248), con un
unico chiamante (`report.py:66`). Un fix (unità dinamiche o più decimali)
toccherebbe solo il codice di generazione grafico, non la logica di calcolo KPI
né i template né `kpi_order`. Lo stesso pattern in `make_channel_bar_chart`
(righe 268, 273) andrebbe probabilmente allineato per coerenza, ma non è
sintomatico in questa sessione (le etichette numeriche delle barre usano
`fmt_number()` a riga 279, indipendente dal formatter dell'asse).

---

## BUG 2 — Colonna PARTNER sempre 0 in Top Content

### Root cause

**Non è un bug di join/query.** Verificato con query SELECT dirette sul DB dev
(finestra 90gg, tutti i brand):

`database.py:124-143` (`get_content_performance`) e `database.py:146-164`
(`get_partner_stats`) referenziano correttamente `partner_id` e calcolano
`n_partners` / reach partner in modo coerente:

```
=== CONTENT (raw, 8 righe totali) ===
post_id                                channel     reach   n_partners
5bc24791-...                           linkedin      2        0
c57f0ea7-...                           facebook      2        0
67fbdaa5-...                           linkedin      1        0
84e26ed5-...                           linkedin      1        0
ee32ddc1-...                           facebook      1        1   ← unica riga con partner
67fbdaa5-...                           facebook      1        0
c57f0ea7-...                           instagram     0        0
67fbdaa5-...                           instagram     0        0

=== PARTNER STATS ===
partner_id      partner_name          reach   posts
7fc6266d-...    New Magne Partner       1       1
```

La riga `ee32ddc1-...` (facebook, reach=1, n_partners=1) corrisponde 1:1 al
partner attivo "New Magne Partner" (reach=1, posts=1). Il join e il conteggio
sono corretti a livello di query grezza.

### Dove si perde il dato

`kpi.calc_content_score()` (`kpi.py:99-127`) ordina per
`content_score = er_post*0.6 + reach_norm*100*0.4` e mantiene solo `top_n=5`
(default usato in `report.py:60`). Verificato eseguendo `calc_content_score`
sui dati reali:

```
=== TOP-5 CONTENT (dopo calc_content_score) ===
post_id       channel    content_score   n_partners
84e26ed5-...  linkedin      200.0           0
67fbdaa5-...  facebook      140.0           0
5bc24791-...  linkedin       70.0           0
c57f0ea7-...  facebook       70.0           0
67fbdaa5-...  linkedin       20.0           0
```

L'unica riga con `n_partners=1` (engagement=0 nella query grezza) ha un
`content_score` troppo basso e finisce **fuori dal top-5**, prima ancora di
arrivare al template. `templates/report.html:373` (`{{ row.n_partners }}`)
stampa quindi 0 per tutte e 5 le righe sopravvissute — non perché il dato sia
sbagliato, ma perché la riga con partner non è più nel set renderizzato.

### Comportamento atteso o bug reale?

Dato il dataset attuale, è **comportamento atteso dell'algoritmo di ranking**,
non un difetto di join/filtro. Diventa un problema di visibilità/UX solo
perché il dataset demo è estremamente sparso (8 righe content/canale totali, 1
solo post partner con engagement=0): la formula di content score non ha alcun
termine che premi la co-authorship di un partner, quindi un contenuto con
partner ma basso engagement è strutturalmente svantaggiato rispetto ai
contenuti solo-brand nel ranking attuale.

### Rischio stimato di un fix mirato

**Medio.** Qualsiasi fix che renda visibile il contenuto partner nel Top
Content richiederebbe di toccare o (a) la formula `content_score` in
`kpi.py:116` — esplicitamente fuori scope per questa sessione ("logica di
calcolo KPI esistente"), oppure (b) `top_n` / logica di filtro, il che cambia
quali contenuti appaiono nel report demo — una decisione di prodotto, non solo
un fix tecnico. Nessuna modifica tentata in questa sessione.

---

## Riepilogo

| Bug | Causa | Dati corretti? | Severità | Stato |
|---|---|---|---|---|
| 1 — Asse Y/X 0K | scala /1000 hardcoded + formatter a 0 decimali senza soglia | Sì, solo visualizzazione | Estetico | **RISOLTO** — trend in 1e5d08c, channel il 2026-07-17 via helper `k_scale()` |
| 2 — Partner=0 in Top Content | `kpi.py:116` (content_score non pesa i partner) → riga con partner esclusa dal `top_n=5` prima del render | Sì, query e join corretti | Comportamento atteso su dataset sparso, non bug di join | **APERTO** — fix tocca logica KPI, decisione di prodotto |
