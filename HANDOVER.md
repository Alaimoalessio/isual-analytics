# ISUAL Analytics — Documento di consegna

**Autore:** Alessio Alaimo (tirocinio ISUAL) · **Data:** 2 settembre 2026
**Destinatario:** CTO e chiunque prenda in mano il progetto dopo di me
**Repo:** `github.com/Alaimoalessio/isual-analytics` — branch `main`

Questo non è un manuale del codice: il codice è commentato e si legge da sé. Qui c'è
quello che **non si deduce leggendolo** — le cose che sembrano vere e non lo sono, le
decisioni che hanno una ragione non ovvia, e i muri che non dipendono da noi.

Molte delle informazioni più utili su questo progetto non stanno nel codice: sono state
ricavate interrogando direttamente il database o emerse in conversazione. Per questo
ogni affermazione è marcata con la sua fonte — così chi legge sa cosa può verificare da
solo e cosa no.

---

## 0. Leggi questo per primo — stato del repo alla consegna

**Working tree pulito, tutto committato.** Ultimo commit: `0d27af9`.

Gli ultimi tre commit sono stati fatti il giorno della consegna e chiudono il lavoro
che avevo in sospeso:

| commit | contenuto |
|---|---|
| `a5d0f88` | Banner salute sync metriche (`get_sync_health` + `/api/sync-health` + banner in dashboard) |
| `5320729` | Appendice PDF con tutti i contenuti del periodo (+ variante di stampa `.table-card--flow`) |
| `0d27af9` | I tre script one-shot che creano `brand_settings` e `brand_kpi_config` |

Il terzo merita una riga in più: **quelle due sono le uniche tabelle nostre**, tutto
il resto dello schema appartiene all'applicazione di Coders51. Fino a ieri gli script
che le creano esistevano solo nel working tree della mia macchina, il che rendeva un
ambiente nuovo non ricostruibile. Ora sono versionati, sono idempotenti
(`INSERT ON CONFLICT DO NOTHING`) e leggono le credenziali da variabili d'ambiente.
`update_logo_urls.py` va eseguito **dopo** `create_brand_settings.py`.

### Tre cose da sapere prima di toccare qualsiasi cosa

**1. Non esiste una suite di test.** `tests/` contiene solo file `.pyc` orfani: i
sorgenti (`conftest.py`, `test_db.py`, `test_kpi.py`, `test_report.py`) sono stati
cancellati dal commit `1c5ca2c`, *"chore: remove tests and CI for MVP demo"*. Non c'è
CI. **Ogni modifica va verificata a mano**, e i bug descritti nel §2 sono quasi tutti
bug che un test avrebbe intercettato: producevano numeri sbagliati ma perfettamente
plausibili. È la singola mancanza più costosa del progetto.

**2. C'è uno stash aperto e non va riapplicato.**
`stash@{0}: WIP: resolve_filter combinazione AND (da completare: template + get_params + argparse)`.
È vecchio di molti commit e `report.py` nel frattempo è cambiato parecchio. Va
**riscritto guardandolo**, non `git stash pop`. Dettagli in §6.

**3. `DIAGNOSI_BUG.md` è un documento storico, non lo stato attuale.** Ha già in testa
una nota di aggiornamento per "BUG 1", ma dichiara ancora *"BUG 2 resta aperto"*: non
lo è più (§6). Se lo leggi come diagnosi corrente, diagnostichi bug chiusi.

`.env` non è versionato e non deve esserlo. Le credenziali di produzione stanno su
Render e nel file locale di chi sviluppa.

---

## 1. Architettura in breve

Un solo database Postgres, **due consumatori dello stesso codice di calcolo**.

### Da dove vengono i dati

Il database è quello dell'applicazione **Coders51**, che pubblica i contenuti sui
social e ne raccoglie le metriche. Noi lo leggiamo e basta.

- **Tabelle di terzi, sola lettura:** `brands`, `partners`, `publications`, `posts`,
  `tags`, `targets`, `partners_tags`, `partners_targets`. Non le scriviamo mai, e il
  loro schema può cambiare senza che ce lo dicano.
- **Tabelle nostre:** `brand_settings` (palette e logo per brand) e `brand_kpi_config`
  (ordine, etichetta e visibilità delle KPI card). Le creano i tre script one-shot.

La tabella centrale è `publications`: **una riga per (contenuto × canale × partner)**.
Non è una riga per post. Quasi tutti gli errori di conteggio nascono dal dimenticarlo.

### I moduli

```
database.py      tutto l'SQL + il caricamento credenziali (python-dotenv)
kpi.py           calcoli derivati sui DataFrame pandas (score, health, breakdown)
report.py        orchestrazione PDF: Jinja2 → templates/report.html → WeasyPrint
dashboard/app.py Flask, ~22 endpoint sotto /api/
static/app.js    dashboard live (vanilla JS, nessun framework)
```

Non c'è un `config.py`, non c'è un package `oop/`, non c'è `report_oop.py`: sono
spariti nel refactor `1e5d08c` che ha appiattito lo stack a questi moduli. Se una nota
o un documento li cita, quella nota è vecchia.

### Il punto in cui l'architettura si può rompere

Dashboard e PDF **devono dare gli stessi numeri per gli stessi input**, ma leggono i
filtri in due posti diversi:

- `dashboard/app.py::get_params()` — per la dashboard
- `report.py::resolve_filter()` — per il PDF

Sono deliberatamente speculari (il commento in `resolve_filter` lo dice: *"Rispecchia
get_params() della dashboard"*), ma **non condividono codice**. Chi cambia la logica
dei filtri in uno solo dei due crea una divergenza che non dà errore: dà due numeri
diversi per lo stesso brand, uno a schermo e uno nel PDF, e ci si accorge solo quando
qualcuno li confronta.

`kpi.py` è invece condiviso davvero, ed è lì che va messa ogni logica di calcolo che
deve valere per entrambi.

### Deploy

Render, collegato a GitHub: **push su `main` = deploy automatico**. Servito da
`dashboard/Procfile` (`gunicorn -w 2 -b 0.0.0.0:$PORT app:app`) con
`dashboard/requirements.txt`. Non esistono `render.yaml` né workflow GitHub: la
configurazione vive nella dashboard di Render. Procedura di verifica in §5.

---

## 2. Trappole già scoperte

Questa è la sezione portante del documento. Per ognuna: **sintomo**, **causa**,
**fix**, e soprattutto **come accorgersene** se si ripresenta — perché il tratto comune
di tutti questi bug è che *non danno errore*: danno un numero credibile e sbagliato.

### 2.1 Fan-out in `get_overview` — le tre cifre di testa moltiplicate

**Sintomo.** Reach, Impressions ed Engagement gonfiati di un fattore costante per
brand: ×9 su Terme di Cervia, ×31 su Claudio Uno. Numeri grandi ma plausibili, nessun
errore da nessuna parte.

**Causa.** Un `LEFT JOIN partners p ON p.brand_id = pub.brand_id`: la `ON` legava il
partner **al brand**, non alla pubblicazione. Ogni riga di `publications` veniva quindi
moltiplicata per il numero di righe `partners` di quel brand, e le `SUM` uscivano
gonfiate esattamente di quel fattore.

**Perché è rimasto invisibile.** `total_posts` era `COUNT(DISTINCT pub.id)`: il
`DISTINCT` lo salvava. Quindi il conteggio dei post era giusto mentre le tre metriche
accanto erano sbagliate — la combinazione più difficile da notare, perché la cifra che
si controlla d'istinto è proprio quella corretta.

**Fix — `103cc30`.** Rimossa la JOIN, e con essa le due colonne che la giustificavano
(`total_partners`, `active_partners`). Non corretta la `ON`: quelle colonne non le
leggeva nessuno (Network Adoption prende i suoi numeri da `get_adoption`) e per di più
contavano i partner **grezzi** invece dei soli canonici — 9 righe per 6 nomi reali,
cioè lo stesso bug del §2.2. Una colonna morta che si chiama `total_partners` e
contraddice la logica buona è una trappola per il prossimo che la trova e la usa in
buona fede.

**Come accorgersene.** Ogni volta che si aggiunge una JOIN a una query che contiene
`SUM()`: chiedersi se la `ON` è su una chiave che mantiene il rapporto 1:1 con
`publications`. Se la JOIN serve solo a produrre un `COUNT(DISTINCT …)` di un'altra
entità, quel conteggio va in una query separata. Il test pratico: eseguire la query
con e senza la JOIN e confrontare le `SUM`. Se cambiano, la JOIN sta moltiplicando le
righe. `COUNT(DISTINCT …)` che resta uguale **non è** una prova che vada tutto bene.

### 2.2 Partner duplicati — e le due modalità opposte con cui si gestiscono

**Sintomo.** Network Adoption più bassa del vero (Cervia 5/9 = 56% con 6 nomi reali);
tendine dei filtri con lo stesso nome due volte; un Tag che restituisce zero risultati
pur avendo partner associati.

**Causa.** `partners` ha **solo `PRIMARY KEY (id)`**, nessun vincolo su
`(brand_id, name)`, e in produzione le righe non vengono mai cancellate.
L'applicazione di terzi permette di ricreare un partner con lo stesso nome nello stesso
brand: il risultato sono gruppi di righe omonime, quasi sempre una popolata e le altre
vuote. Non possiamo aggiungere il vincolo: non è il nostro schema.

**Fix.** La CTE `PARTNERS_CANONICI` in `database.py` elegge **un canonico per gruppo
`(brand_id, name)`** con quattro criteri in cascata: più pubblicazioni → `version` più
alta → `created_at` più vecchio → `id` (determinismo assoluto). Si contano *tutte* le
pubblicazioni, non solo le `status='OK'`: una riga con sole pubblicazioni fallite è
comunque il record reale rispetto a un duplicato vuoto.

**La parte che va capita prima di toccarla:** la CTE è applicata in tre punti con
**due modalità opposte, e la differenza è intenzionale**.

| dove | modalità | perché |
|---|---|---|
| `get_partners_for_filter` (tendine) | **esclude** le copie | nella tendina l'utente vede solo il nome: due voci identiche sono indistinguibili, e sceglierne la sbagliata dà KPI a zero senza spiegazione |
| `get_adoption` | **esclude** le copie | gonfiavano il denominatore |
| `get_partner_ids_by_tag` / `..._by_target` | **rimappa** sul canonico | i collegamenti puntano all'id che l'app di terzi aveva sottomano, che può essere una copia vuota (caso reale: il tag `ggg`). **Filtrare qui lascerebbe il tag senza alcun partner — peggio del bug di partenza.** Rimappare lo porta sul record giusto |

Il `DISTINCT` nella rimappatura non è decorativo: un tag legato sia alla riga canonica
sia a una copia (caso `Prosciutto`) le collassa sullo stesso id.
Commit: `52b0296`, `7bb9087`, `a6a647c`.

**Come accorgersene.** Sintomo tipico: un conteggio di partner che non torna con
quello che si vede nell'interfaccia di Coders51, o un filtro che dà zero senza motivo.
Query di controllo:

```sql
SELECT brand_id, name, COUNT(*)
FROM partners GROUP BY brand_id, name HAVING COUNT(*) > 1;
```

Regola per il futuro: **ogni nuova query che tocca `partners` deve dichiarare a quale
delle due modalità appartiene.** Se sta selezionando partner da mostrare o contare →
esclude. Se sta risolvendo un collegamento preesistente (tag, target, o qualunque
tabella ponte futura) → rimappa.

### 2.3 Network Adoption oltre il 100%

**Sintomo.** Percentuale di adozione sopra 100 — numericamente impossibile, quindi
almeno questo si nota subito.

**Causa.** Numeratore e denominatore contati su **insiemi diversi**. Il numeratore
partiva da `publications` e includeva `partner_id` orfani (pubblicazioni che puntano a
partner non più presenti nel perimetro), il denominatore contava le righe `partners`.
Bastava un orfano per rompere l'invariante `attivi ≤ totali`.

**Fix — `a98892d`.** In `get_adoption` esiste ora **una sola lista `scope_conditions`**,
costruita una volta e applicata a entrambi i lati: al denominatore con
`.format(alias="")`, al numeratore con `.format(alias="p.")` dentro un `EXISTS`.
L'invariante vale **per costruzione**, non per controllo a posteriori.

**Come accorgersene.** Il fatto che le condizioni siano stringhe con `{alias}` e non
f-string è deliberato: `CONDIZIONE_CANONICO` è `"{alias}id IN (SELECT canonical_id
FROM canonici)"` e viene formattata due volte, una per lato. Se qualcuno la converte
in f-string o aggiunge una condizione direttamente all'`EXISTS` invece che alla lista
condivisa, il bug torna. Controllo immediato: qualunque valore di Network Adoption
> 100% o attivi > totali significa che una condizione è finita su un lato solo.

### 2.4 `token_status` non dice se l'integrazione funziona

**Sintomo.** Il sync delle metriche di un canale è fermo da mesi, i numeri smettono di
crescere, e nessun indicatore lo segnala. Un token risulta valido mentre il 100% dei
suoi aggiornamenti fallisce.

**Causa.** `token_status` descrive lo stato formale della credenziale, non l'esito
degli aggiornamenti. Sono due cose diverse e possono divergere a lungo.

> **Marcatura fonte.** `token_status` e `analytics_update_failures` **non compaiono da
> nessuna parte nel nostro codice**: sono tabelle/colonne del database di Coders51 che
> ho ispezionato con query dirette. Quanto scritto qui è la mia testimonianza, non
> qualcosa che il repo dimostra.

**Fix — `a5d0f88`.** Il segnale affidabile è
`publications.updated_at IS DISTINCT FROM created_at`: una riga **solo inserita** ha i
due timestamp uguali e non dice nulla sul sync; una riga toccata da un aggiornamento
di metriche no. `MAX(updated_at)` per canale dice quindi quando quel sync ha lavorato
l'ultima volta. Su questo è costruito il banner in dashboard.

Dettagli che sembrano dettagli e non lo sono:

- `IS DISTINCT FROM` e non `!=`: `!=` scarterebbe anche i NULL, ma per il motivo
  sbagliato e in silenzio.
- I giorni si calcolano **in SQL**: `updated_at` è `timestamp WITHOUT time zone`
  mentre `published_at` è `WITH time zone`, e mescolarli in Python è il punto in cui
  entra un errore di fuso che nessuno vede.
- `days_since = None` significa "canale con pubblicazioni recenti ma **nessuna riga mai
  toccata dal sync**": è il caso **peggiore**, non "appena sincronizzato". Nel codice è
  mappato ad `alert` esplicitamente.
- Le soglie (3 giorni warning, 7 alert) sono strette di proposito, ma un banner che
  appare a sproposito è un banner che si smette di leggere: se si allentano, si
  allentano per canale in `SYNC_THRESHOLDS`, non alzando il default.

**Come accorgersene.** È esattamente ciò che il banner ora fa da solo. A mano:

```sql
SELECT social, MAX(updated_at) FILTER (WHERE updated_at IS DISTINCT FROM created_at)
FROM publications WHERE status = 'OK' GROUP BY social;
```

Se una data è vecchia di settimane, quel canale è fermo — **indipendentemente da cosa
dice `token_status`**.

### 2.5 `reach = 0` non significa "pubblicazione fallita"

**Sintomo (ricorrente, tornerà).** In Worst Content compaiono contenuti con reach ed
engagement a zero. Sembrano pubblicazioni andate in errore sfuggite ai filtri.

**Causa: nessuna. Non è un bug.** Le pubblicazioni fallite sono escluse **due volte in
modo indipendente**: da `pub.status = 'OK'` in `brand_filter`, e dal confronto sulle
date, perché **tutte le 222 righe KO del database hanno `published_at` NULL**. Un KO
non può arrivare in Worst Content.

Il caso reale (Terme di Cervia, diagnosticato il 03/08/2026): due righe
`status='OK'`, `published_at` 11/05/2026, `partner_id` NULL (pubblicazioni brand),
metriche genuinamente a zero. L'equivoco è fondato a metà — lo stesso testo *ha* anche
5 pubblicazioni KO su altri canali — ma le righe in Worst sono le pubblicazioni
**riuscite** dello stesso post.

> **DECISIONE DI PRODOTTO DELLA FOUNDER, definitiva (03/08/2026): questi contenuti
> DEVONO restare visibili.** Un contenuto pubblicato che non genera interazione è
> esattamente ciò che Worst Content esiste per far emergere.

Un filtro `reach > 0` sul pool Worst **è stato implementato e annullato lo stesso
giorno**, su indicazione della founder. Non è mai stato committato — per questo non c'è
un hash da citare: è stato scartato dal working tree. **Non reimplementarlo.**

**Come accorgersene.** Prima di indagare, chiedere **il periodo del report**: quelle
righe compaiono solo da ~90 giorni in su, e nel report di default a 30 giorni Worst
Content contiene tutt'altro. Poi verificare con una query grezza su `publications`
senza filtri. E se qualcuno chiede di nascondere i contenuti a reach 0, accertarsi che
sia una decisione della founder e non un'inferenza da "sembrano un errore".

### 2.6 `break-inside: avoid` è controproducente sulle tabelle lunghe

**Sintomo.** Nel PDF una tabella lunga viene spinta a inizio pagina nuova, lascia
mezza pagina bianca, **e si spezza lo stesso**.

**Causa.** `break-inside: avoid` su un blocco **più alto della pagina** non può tenerlo
intero: non ci sta. Il motore lo sposta a pagina nuova sperando che basti, non basta, e
lo frammenta comunque — ottenendo il peggio dei due mondi. La regola generale su
`.table-card` resta però quella giusta per le tabelle da 3-10 righe di tutte le altre
sezioni.

**Fix parziale — `5320729`.** Variante `.table-card--flow`, applicata **alla sola
appendice**, che è l'unica tabella del report che può superare la pagina:
`break-inside: auto` + `thead { display: table-header-group }` (senza, dalla seconda
pagina in poi restano sette colonne di numeri senza nome). Va tolto anche
`overflow: hidden`: crea un contesto di formattazione che WeasyPrint non frammenta, e
la tabella verrebbe **troncata** a fine pagina invece di continuare.

**Caso ancora aperto: Partner Leaderboard oltre ~30 righe** — vedi §6. Il fix tecnico
sarebbe cappare le righe, ma è una decisione di prodotto, non mia.

**Come accorgersene.** Non si vede a schermo: **si vede solo generando il PDF con un
brand che abbia abbastanza dati**. Un report a 30 giorni su un brand piccolo non
raggiunge mai il caso. Prima di toccare il CSS di stampa, generare un report a 90+
giorni sul brand più popolato.

### 2.7 La convenzione critica: `None` ≠ `[]`

**Questa voce non descrive un bug avvenuto: descrive la convenzione che tiene chiuse
le precedenti.** È anche la cosa che romperei per prima, se dovessi indovinare cosa si
rompe dopo di me.

```
partner_ids is None   →  NESSUN filtro partner  →  tutti i partner
partner_ids == []     →  filtro ATTIVO che non seleziona nessuno  →  zero risultati
```

Il caso reale che le distingue: **un Tag senza partner associati**. Deve mostrare zero,
non tutto.

**Quindi: sempre `is None` / `is not None`, mai un test booleano.** `if partner_ids:`
tratta `[]` come "nessun filtro" e mostra l'intero brand a chi ha chiesto un tag vuoto —
un risultato che sembra perfettamente normale. In `brand_filter` il ramo `[]` aggiunge
letteralmente `FALSE` alla `WHERE`.

**Corollario 1 — il cast `::uuid[]` è obbligatorio.** `psycopg2` adatta la lista Python
a `text[]`, e Postgres non ha un operatore `uuid = text`: senza `ANY(%s::uuid[])` la
query non gira.

**Corollario 2 — `single_partner` dipende dalla RICHIESTA, non dal RISULTATO.** Un tag
che risolve a un solo partner **non è** un partner singolo, e non deve attivare gli
`N/A` di Network Adoption. Le due implementazioni oggi coincidono ma **sono espressioni
diverse**, ed è bene saperlo prima di allinearle:

- `dashboard/app.py:41` → `single_partner = partner_id is not None`
- `report.py::resolve_filter` → truthiness (`if partner_id:`, e `selected = [… if v]`)

Coincidono finché l'input è `None` o un id valido. Divergerebbero il giorno in cui
arrivasse una stringa vuota: `is not None` la considera un filtro, la truthiness no.

**Come accorgersene.** Test di regressione manuale, da rifare dopo ogni modifica ai
filtri: **selezionare un Tag privo di partner**. Se la dashboard mostra i dati
dell'intero brand invece di zero, la convenzione è stata rotta da qualche parte.

---

## 3. Dipendenze da Coders51 — muri, non bug

Le cose in questa sezione **non sono risolvibili dal nostro lato**. Sono elencate qui
perché il costo peggiore non è il limite in sé: è il tempo che si perde cercando nel
nostro codice la causa di qualcosa che nel nostro codice non c'è.

> **Marcatura fonte.** Tutto il §3 nasce da query dirette sul database di Coders51 e da
> scambi con loro. **Nulla di quanto segue è verificabile leggendo il repo**, con
> l'unica eccezione indicata al §3.3.

### 3.1 `analytics_update_failures` dice CHE è rotto, non PERCHÉ

Esiste una tabella che registra i fallimenti degli aggiornamenti di metriche, ma il suo
campo `error` **non contiene né il codice HTTP né il motivo** del fallimento. Si può
sapere che un aggiornamento è fallito, quante volte e su quale riga; non si può sapere
se è stato un token scaduto, un permesso mancante, un rate limit o un endpoint
dismesso.

**Conseguenza pratica:** ogni diagnosi di sync parte da un'ipotesi non verificabile. È
il motivo per cui il banner del §2.4 misura *l'effetto* (`updated_at` che non si muove)
invece della *causa*: la causa non è disponibile.

Se un giorno si chiede una sola modifica a Coders51, chiedete questa.

### 3.2 LinkedIn: sync fermo da ottobre 2025 ad agosto 2026 — ora ripartito

Il caso che ha motivato tutto il §2.4.

- **Ottobre 2025:** LinkedIn dismette le API su cui si appoggiava la raccolta analytics.
  Il sync smette di aggiornare le metriche. **Nessun allarme**: i token restavano
  formalmente validi e i dati già raccolti restavano in tabella, quindi la dashboard
  continuava a mostrare numeri — semplicemente fermi.
- **12 agosto 2026:** Coders51 (Davide Dall'Olio) comunica di aver aggiornato i
  puntamenti alle nuove API e di aver esteso i permessi necessari. Sono servite **tre
  riconnessioni manuali di account** — profili personali, non organizzazioni.
- **Dopo il fix** ho verificato che tutti e tre i canali avessero `MAX(updated_at)`
  allineato: segno che il ripopolamento era avvenuto. **Il sync LinkedIn è ripartito.**

> **Fonte: testimonianza.** Le date, la causa e il contenuto della comunicazione mi
> sono stati riferiti da Coders51; la verifica finale l'ho fatta io con query dirette.
> Nel repo non c'è alcuna evidenza di tutto questo — a parte il banner che ora lo
> renderebbe visibile se ricapitasse.

**Dieci mesi di buco scoperti a posteriori** sono la ragione per cui il banner esiste.
Non impedisce il guasto: impedisce che passi inosservato.

### 3.3 Facebook: buco analogo, novembre 2025 – luglio 2026

Stesso schema, altro canale.

> **Fonte: mia affermazione.** L'unica traccia nel repo è un commento che ho scritto io,
> in testa a `get_sync_health` in `database.py` (commit `a5d0f88`). Non è una conferma
> indipendente: è la stessa informazione, scritta da me in due posti. Chi volesse
> verificarla deve rifare la query sullo storico di `publications`.

### 3.4 Le notifiche di dismissione API non arrivano a noi

Le comunicazioni ufficiali di LinkedIn sulla dismissione delle API vanno **all'indirizzo
email registrato sull'applicazione LinkedIn, che è di Coders51.** Non a ISUAL.

È il punto che rende strutturale tutto il resto: **non esiste un canale per cui ISUAL
possa venire a sapere in anticipo che un'integrazione sta per rompersi.** La prima
notizia arriva dai dati che smettono di muoversi, cioè settimane o mesi dopo. La sola
contromisura sotto il nostro controllo è accorgersene presto — di nuovo, il banner.

---

## 4. Scelte di prodotto e perché

Decisioni deliberate che, senza la motivazione accanto, sembrano errori da correggere.
Chi le "sistema" senza leggere questa sezione le rompe.

### 4.1 Amplification Factor è una QUOTA %, non un moltiplicatore

Prima era `total_reach / brand_reach`, un moltiplicatore ("la rete moltiplica per 3,4").
Ora è `partner_reach / (partner_reach + brand_reach) × 100`: **la quota percentuale del
reach totale generata dalla rete partner** (commit `f9d68c0`).

Il moltiplicatore aveva una scala aperta e un denominatore fragile: con un brand senza
reach diretto misurato la divisione era impossibile, e il valore si comportava in modo
erratico proprio nei casi limite. La quota ha una scala chiusa 0-100% e un denominatore
che è la somma dei due addendi — non può sparire se almeno una delle due fonti ha
reach.

**Attenzione al caso che si autocorreggeva prima e ora no.** Con un filtro partner
attivo, le pubblicazioni del brand (`partner_id IS NULL`) escono dal set: la riga
`brand` non arriva proprio, `brand_reach` è 0 e la formula darebbe **un 100% pulito e
credibile** — "tutto il reach viene dalla rete" — che è un artefatto del filtro, non un
dato. Per questo `amp_filtered` è passato esplicitamente a `calc_overview`, ed è
`partner_ids is not None`: il denominatore va dichiarato non valido con **qualsiasi**
filtro partner, **Tag e Target inclusi**. Con la vecchia formula l'errore si nascondeva
da solo (divisione impossibile → N/A); con questa no.

### 4.2 Nessun semaforo sulla card Amplification

Tutte le altre KPI card hanno un colore-soglia (verde/arancio/rosso). Questa **no, mai**,
ed è deliberato.

È una metrica di **composizione** (da dove arriva il reach), non di **performance** (se
il reach è stato buono). Una quota bassa significa che il brand ha un canale proprio che
funziona: colorarla di rosso direbbe *"pubblica meno in proprio"*, che non è un consiglio
sensato. Il verso del "buono" dipende dalla strategia del brand, e un semaforo la
deciderebbe al posto suo.

### 4.3 Mutua esclusione Top/Worst via slice posizionale

Top Content e Worst Content non possono mostrare lo stesso contenuto. L'esclusione è uno
**slice posizionale sulla stessa classifica ordinata** (`scored.iloc[top_n:].tail(worst_n)`),
non un anti-join su `post_id + channel`.

Perché è più solido: sulla stessa classifica non *esiste* il caso in cui una riga cada
in entrambe le tabelle — non c'è un confronto di chiavi che possa fallire. Ma vale solo
**se le due tabelle nascono dallo stesso DataFrame**: `report.py` passa `df_content` a
entrambe di proposito. Chi in futuro ricalcolasse il df in mezzo romperebbe l'invariante
senza vedere alcun errore.

Conseguenza attesa, non bug: con N righe totali Worst ne ha `min(worst_n, max(0, N - top_n))`.
Con N ≤ 3 la tabella Worst è **vuota**, e il template distingue "nessun contenuto" da
"tutti già fra i Top" grazie a `content_total`.

### 4.4 Partner, Tag e Target sono alternativi, non combinabili

Tre modi di selezionare gli stessi partner, mai due insieme. Non è una limitazione
tecnica: sono tre percorsi diversi verso lo stesso `partner_ids`, e combinarli
richiederebbe di decidere se l'intersezione è un AND o un OR — che è una domanda di
prodotto senza risposta ovvia.

Il rifiuto è dichiarato in **due posti**, entrambi *prima* di toccare il database:
`add_mutually_exclusive_group()` in `report.py`, e la catena `if/elif` in
`get_params()` (dashboard), dove l'ordine di precedenza è partner → tag → target.
Vedi §6: esiste uno stash che tentava la combinazione AND.

### 4.5 L'ordine delle KPI card si configura da database

Le 8 KPI card non sono più hardcoded: ordine, etichetta e visibilità stanno in
`brand_kpi_config` e si modificano dal pannello ⚙️ della dashboard (drawer con
SortableJS, salvataggio via `POST /api/kpi-config/save`).

> **Fonte: testimonianza.** La direttiva è del CTO, con riferimento esplicito alla
> filosofia **JasperReports** — il layout del report è un dato configurabile, non
> codice. Il nome non compare da nessuna parte nel repo: lo scrivo qui perché è la
> ragione per cui la feature esiste in questa forma, e senza il riferimento sembra
> complessità gratuita per otto card.

Due dettagli non ovvi: il salvataggio è **globale** (scrive su tutti i brand,
`WHERE kpi_key = …`, in transazione unica) benché la tabella sia per-brand; e
`/api/kpi-config/all` è un endpoint **separato** da `/api/kpi` perché il pannello ha
bisogno anche delle card nascoste, mentre la dashboard riceve solo le visibili. La
validazione è fail-fast: nessuna scrittura se un `kpi_key` è sconosciuto, duplicato o
mancante.

---

## 5. Note operative

### Avvio in locale

```bash
cd dashboard
../venv/bin/python app.py        # 127.0.0.1:5001
```

Serve **l'interprete del venv**: il `python3` di sistema non ha `pandas` e fallisce
all'import.

### ⚠️ NON c'è auto-reload

`app.run(..., debug=False)`: il reloader **non è attivo**.

- **Modifiche a codice Python** → riavviare il server **a mano**. Altrimenti si continua
  a testare la versione vecchia, convinti che il fix non funzioni. È l'errore che fa
  perdere più tempo in assoluto su questo progetto.
- **Modifiche a `static/app.js` o `style.css`** → non serve riavviare, serve un **hard
  refresh** del browser (`Cmd+Shift+R`): li serve Flask ma li tiene in cache il browser.

### Un solo server per volta

Capita di ritrovarsi più istanze Flask in LISTEN sulla 5001 (`SO_REUSEPORT`): le
richieste vengono servite in modo non deterministico, alcune da codice vecchio. Sintomo
tipico: lo stesso reload dà due risultati diversi a caso.

```bash
lsof -nP -iTCP:5001 -sTCP:LISTEN    # killare i duplicati, lasciarne uno
```

### Nessuna suite di test

Vale la pena ripeterlo qui, dove si lavora: **non c'è nulla che verifichi una
regressione al posto vostro** (§0). I test in `tests/` sono stati rimossi da `1c5ca2c`
e restano solo `.pyc` orfani. Ogni modifica ai calcoli va confrontata a mano fra
dashboard e PDF sugli stessi input.

### Query di ispezione: usare il ruolo di sola lettura

Per le query di diagnosi sul database usare il ruolo **`isual_readonly`**, non
l'utente applicativo: le indagini del §2 si fanno su dati di produzione, e un `UPDATE`
battuto per errore su tabelle che non sono nostre non è recuperabile da noi.

> **Fonte: testimonianza.** Il ruolo non compare da nessuna parte nel repo — né in
> codice, né in documentazione, né in commenti. È conoscenza operativa: se serve, va
> chiesto a chi amministra il database.

### `BRAND_COLORS_ENABLED`

`BRAND_COLORS_ENABLED=false` forza la palette ISUAL su tutti i brand, ignorando
`brand_settings`. È un **filtro in lettura, reversibile**: i colori nel database non
vengono toccati, si riaccende rimettendo il flag a `true` (o togliendolo — assente
significa attivo, così il comportamento storico resta invariato). Utile per demo e
confronti in cui i colori per-brand distraggono.

### Verifica ATTIVA del deploy su Render

Push su `main` = deploy automatico. **Non basta vedere il deploy verde**: non esiste un
endpoint di versione, quindi che il commit nuovo sia davvero in produzione si deduce
solo dal comportamento. Procedura:

1. **Health check** — `curl -s -o /dev/null -w "%{http_code} %{time_total}s" https://isual-analytics.onrender.com/`
   → atteso `200`. A servizio freddo la prima richiesta può metterci ~50s, a caldo ~0,4s.
2. **Endpoint dati** — `GET /api/kpi?brand_id=<uuid>&days=<n>`. I KPI stanno sotto
   `data`, non alla radice.
3. **Marcatore prima/dopo** — rieseguire lo stesso caso in locale e confrontare i
   valori: è l'unico modo di distinguere "il deploy ha preso il commit nuovo" da "sta
   ancora servendo il vecchio".

Sono tutte GET, sola lettura, sicure su produzione. **Verificare sempre anche il caso
con filtro partner/tag/target attivo**, non solo quello senza: le metriche di rete
(Amplification, Network Adoption) hanno guard che scattano solo lì, e un valore
sbagliato in quel ramo sembra perfettamente credibile (§4.1).

---

## 6. Lavori aperti / in coda

Nulla di quanto segue è un lavoro interrotto a metà: sono cose **deliberatamente non
fatte**, con la ragione accanto. Le prime due sono decisioni di prodotto, non compiti
tecnici.

### 6.1 Partner Leaderboard oltre ~30 righe (decisione di prodotto)

Oltre ~30 partner la `.table-card` della Leaderboard supera l'altezza di un A4 e la
paginazione degrada: `break-after: avoid` sul `.section-title` si ritorce contro — il
titolo viene spinto alla pagina dopo, la tabella non lo raggiunge comunque, e resta una
pagina con il solo titolo (misurato: +2 pagine, di cui 2 quasi vuote, su un report
sintetico da 8).

**Non toccare il CSS di paginazione per risolverlo** (§2.6): la soluzione è cappare le
righe, come già si fa su Top Content. Ma cappare significa **non mostrare dei partner
nel report**, quindi è una decisione da prendere con CTO e founder. Alla scala attuale
il caso non esiste: il brand più grosso in produzione (Claudio Uno) ha 9 partner attivi
e il report resta di 2 pagine.

### 6.2 Tag mono-partner: un nome esposto in Leaderboard (falla nota, non risolta)

La Partner Leaderboard è nascosta con `{% if not single_partner %}`, e `single_partner`
dipende dalla **richiesta** (§2.7). Quindi un filtro **Tag o Target che risolve a un solo
partner** lascia la Leaderboard visibile, con una riga sola e **il nome di quel partner
in chiaro**.

Conta perché il PDF può essere inviato via email direttamente al partner. Tutta la
sezione di contesto è progettata per non esporre partner identificati (media di rete
mostrata solo con **N ≥ 5 partner attivi**, ragionando sull'aggregato residuo N−1), ma
questa strada laterale li espone comunque e non passa da quella soglia.

**La correzione NON è toccare `single_partner`**, che ha una semantica deliberata e
documentata. Serve una condizione separata basata sul **risultato**: "la Leaderboard
mostra nomi solo se i partner risolti sono almeno N", coerente con la soglia di
anonimato già scelta.

### 6.3 Stash `resolve_filter` con combinazione AND — da riscrivere, non riapplicare

```
stash@{0}: WIP: resolve_filter combinazione AND (da completare: template + get_params + argparse)
```

Tentativo di rendere Partner/Tag/Target combinabili in AND (§4.4). **È vecchio di molti
commit e `report.py` nel frattempo è cambiato parecchio**: `git stash pop` produrrebbe
conflitti o, peggio, un merge pulito su una funzione che non è più quella di allora.

Va **riscritto guardandolo**, e prima ancora va deciso il comportamento: se combinare
Tag e Target significhi intersezione o unione dei partner. Da fare, se si fa, in tutti e
tre i punti che lo stash stesso elenca come mancanti — template, `get_params`, argparse.

### 6.4 `n_partners` è una colonna morta

`get_content_performance` calcola ancora
`COUNT(DISTINCT pub.partner_id) FILTER (…) AS n_partners`, ma **nessun template la
legge**: la colonna Partner del PDF mostra `partner_names` (i nomi, con `—` quando non
ce ne sono). È lo stesso tipo di colonna morta rimossa da `103cc30`, con lo stesso
rischio: qualcuno la trova, la crede autorevole e la usa.

**Segnalata e non rimossa di proposito**, essendo alla consegna: è una modifica che non
serve a nulla di ciò che funziona oggi, e va fatta da chi resta, con la possibilità di
verificarla.

### 6.5 `DIAGNOSI_BUG.md` va aggiornato o archiviato

Il documento dichiara ancora *"BUG 2 resta aperto"* (colonna PARTNER sempre 0 in Top
Content). **Non lo è più**: la diagnosi si riferiva a un template che stampava
`n_partners` e a `calc_content_score(df, top_n=5)`. Oggi il template stampa
`partner_names` e il taglio è a 3+3 con mutua esclusione (§4.3). BUG 1 ha già in testa
la sua nota di chiusura.

Chi lo legge come stato corrente diagnostica un bug chiuso. Vale la pena aggiungergli
una nota in testa, o spostarlo in una cartella `docs/storico/`.

### 6.6 Palette divergente sul report "Tutti i brand" (nota, non risolta)

Il PDF generato **senza `brand_id`** ha header blu navy `#1C2B46` con accento `#F24C27`;
ogni report con un brand selezionato è blu `#3B5BDB` con accento `#F08C00`. Due palette
divergenti, perché senza `brand_id` non si passa da `get_brand_settings()` ma da un dict
hardcoded in `report.py`.

Segnalata al founder il 30/07/2026, **decisione esplicita: annotare e nient'altro**. È
preesistente, non una regressione. Se un giorno si allinea, quella corretta è
`_ISUAL_COLORS`: il ramo hardcoded è quello sbagliato.

### 6.7 Piccola nota di robustezza sul pannello KPI

`renderSortableList()` in `static/app.js` costruisce le righe con
`innerHTML` interpolando `item.etichetta`. Oggi il valore arriva da `brand_kpi_config`,
che scriviamo solo noi con i nostri script, e il salvataggio non accetta etichette
libere: **il rischio pratico è nullo**. Ma è l'unico punto del pannello che non usa
`textContent`, e se un domani le etichette diventassero modificabili dall'utente
diventerebbe un vettore XSS. Il resto del codice recente (banner sync incluso) usa
`textContent` proprio per questo.

---

## Appendice A — Mappa file → responsabilità

| file | responsabilità | cosa NON c'è dentro |
|---|---|---|
| `database.py` | Tutto l'SQL, il caricamento credenziali (`python-dotenv`), la CTE `PARTNERS_CANONICI`, `brand_filter`, `get_sync_health` | Nessun calcolo su DataFrame: quello è `kpi.py` |
| `kpi.py` | Calcoli derivati con pandas: `_score_content`, `calc_content_score`, `calc_worst_content`, `calc_content_appendix`, `calc_partner_health`, `calc_channel_breakdown`, formattazioni condivise | Nessuna query, nessuna presentazione HTML |
| `report.py` | Orchestrazione PDF: `resolve_filter`, assemblaggio contesto Jinja2, `soglia_colore`, CLI (`--brand-id`, `--partner-id`/`--tag-id`/`--target-id` mutuamente esclusivi, `--days`, `--date-from/--date-to`, `--out`) | I calcoli (in `kpi.py`); il ramo colori "tutti i brand" è hardcoded qui — §6.6 |
| `templates/report.html` | Layout PDF, 7 sezioni + disclaimer, CSS di stampa incluse `.table-card` e la variante `.table-card--flow` | — |
| `dashboard/app.py` | Flask, ~22 endpoint `/api/`, `get_params()` (specchio di `resolve_filter`), validazione fail-fast del salvataggio KPI | I calcoli (in `kpi.py`); il `debug=False` è in fondo al file |
| `dashboard/templates/dashboard.html` | Markup dashboard, drawer KPI, `#sync-health-banner`, include SortableJS da CDN | — |
| `static/app.js` | Dashboard live in vanilla JS: `loadSyncHealth`, `renderKPIs`, drawer KPI, filtri | Nessuna soglia: `worst`/`degraded` arrivano già calcolati dal server |
| `static/style.css` | Stili dashboard, `.alert-*`, regole `#sync-health-banner` | Il CSS di stampa del PDF, che sta dentro `templates/report.html` |
| `create_brand_settings.py` | One-shot idempotente: crea e popola `brand_settings` (palette per brand). `--env-file` per scegliere l'ambiente | — |
| `create_brand_kpi_config.py` | One-shot idempotente: crea e popola `brand_kpi_config` (8 KPI, ordine canonico). `--env-file` | — |
| `update_logo_urls.py` | One-shot: aggiorna `logo_url` in `brand_settings`. **Da eseguire dopo** `create_brand_settings.py` | — |
| `dashboard/Procfile`, `dashboard/requirements.txt` | Deploy Render (gunicorn) | Nessun `render.yaml`, nessun workflow GitHub: la config sta nella dashboard di Render |
| `DIAGNOSI_BUG.md` | **Documento storico** (02/07/2026) | Non è lo stato corrente — §6.5 |
| `tests/` | **Vuota**: solo `.pyc` orfani, sorgenti rimossi da `1c5ca2c` | Non c'è nessun test — §0, §5 |

---

*Fine del documento. Per qualsiasi cosa non coperta qui, il criterio che ha funzionato
meglio in questi mesi è: verificare sullo stato reale — il database con una query, il
codice con `git log -S` — prima di fidarsi di qualunque documento, questo incluso.*
