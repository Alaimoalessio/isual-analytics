# ISUAL Analytics — Documento di consegna

**Autore:** Alessio Alaimo (tirocinio ISUAL) · **Data:** settembre 2026
**Per chi:** chiunque prenda in mano il progetto dopo di me
**Repository:** `github.com/Alaimoalessio/isual-analytics` — branch `main`

Questo documento non spiega cosa fa il codice riga per riga: quello si legge dal codice, che è
commentato. Qui c'è quello che il codice non può dirti da solo: i punti dove è facile sbagliare senza
accorgersene, le scelte che sembrano errori ma sono volute, e le cose che dipendono da fornitori
esterni e non da noi.

Il progetto è stato costruito da zero. Le "trappole" descritte più avanti non sono difetti lasciati nel
codice: sono punti in cui, per come funziona il database o gli strumenti usati, è facile introdurre un
errore che non dà nessun messaggio d'errore — produce solo un numero sbagliato ma credibile. Sono
documentate perché chi lavorerà sul codice dopo di me può cascarci esattamente come è successo
durante lo sviluppo.

---

## 0. Da leggere per primo

Lo stato del progetto alla consegna: tutto è salvato e pubblicato, niente è lasciato a metà nel codice
attivo.

Tre cose da sapere prima di toccare qualsiasi cosa.

**Non esistono test automatici.** Un test automatico è un pezzo di codice che verifica da solo se il
resto funziona ancora dopo una modifica. In questo progetto non ce ne sono. Significa che ogni
modifica va controllata a mano. È la cosa più importante da tenere presente, perché quasi tutti i
problemi descritti nella sezione 2 producono numeri sbagliati ma plausibili, che a occhio non si notano
— un test li avrebbe intercettati.

**C'è un lavoro messo da parte che non va ripristinato così com'è.** In Git esiste uno "stash" (un
cassetto dove si tengono modifiche non finite) con un tentativo di far combinare i filtri tra loro. È
vecchio: il codice attorno è cambiato molto da allora, quindi va riscritto guardandolo, non ripristinato
con un comando. Dettagli nella sezione 6.

**Le credenziali non sono nel codice.** Il file `.env` con le password del database non è pubblicato (e
non deve esserlo). In produzione le credenziali stanno sul servizio di hosting (Render); in locale, nel
file di chi sviluppa.

**Nota sui due formati.** Questo documento esiste come file di testo nel repository (la versione
ufficiale) e come PDF/Word per comodità di lettura. Se si modifica il testo, le copie vanno rigenerate a
mano: non si aggiornano da sole. In caso di differenze, vale la versione nel repository.

---

## 1. Com'è fatto il progetto

Un solo database, e due modi di mostrarne i dati: la dashboard (nel browser) e il report in PDF.

**Da dove arrivano i dati.** L'integrazione con i social — cioè la pubblicazione dei contenuti e la
raccolta dei numeri (visualizzazioni, interazioni) — è gestita da un fornitore esterno, Coders51. I dati
raccolti finiscono in un database, che il nostro progetto legge soltanto: non lo scrive e non lo controlla.
Questo spiega molte delle difficoltà descritte più avanti: quando un numero non torna, spesso la causa
è nei dati in arrivo, non nel nostro codice.

- **Tabelle che leggiamo e basta:** quelle dei brand, dei partner, delle pubblicazioni, dei tag. Non le
  scriviamo mai, e la loro struttura può cambiare senza preavviso.
- **Tabelle nostre:** due, che gestiscono i colori/logo di ogni brand e la configurazione delle card KPI.
  Le creano tre piccoli script inclusi nel progetto.

**Il dettaglio che genera metà degli errori di conteggio.** Nella tabella delle pubblicazioni, ogni riga è
una combinazione di **contenuto + canale + partner**, non "un post". Lo stesso post pubblicato da 3
hotel su Facebook sono 3 righe. Chi lo dimentica conta tutto in eccesso.

I file principali:

| file | cosa contiene |
|---|---|
| `database.py` | tutte le richieste al database + il caricamento delle credenziali |
| `kpi.py` | i calcoli sui dati (punteggi, medie, raggruppamenti) |
| `report.py` | la costruzione del PDF |
| `dashboard/app.py` | il server web e i suoi endpoint |
| `static/app.js` | la dashboard interattiva nel browser |

**Un punto delicato.** La dashboard e il PDF **devono dare gli stessi numeri per gli stessi filtri**, ma
leggono i filtri in due punti diversi del codice (uno per la dashboard, uno per il PDF). Sono scritti
apposta per essere identici, ma non condividono lo stesso codice. Se qualcuno cambia la logica dei
filtri in uno solo dei due, dashboard e PDF iniziano a dare numeri diversi per lo stesso brand — e non
c'è nessun errore che lo segnali, ci si accorge solo confrontandoli. I calcoli veri e propri stanno invece in
un unico file condiviso (`kpi.py`): ogni logica che deve valere per entrambi va messa lì.

**La pubblicazione online.** Il progetto è ospitato su Render, collegato a GitHub: ogni modifica caricata
viene pubblicata automaticamente. Come verificare che sia andata a buon fine è spiegato nella
sezione 5.

---

## 2. Dove è facile sbagliare

Questa è la parte più utile del documento. Ogni punto qui sotto descrive un errore facile da introdurre
senza che il programma dia alcun avviso: il risultato è solo un numero sbagliato ma credibile. Per
ognuno: cosa succede, perché, e come accorgersene.

### 2.1 Numeri gonfiati nelle richieste con somme

**Cosa può succedere.** I tre numeri principali (persone raggiunte, visualizzazioni, interazioni) risultano
molto più alti del vero — moltiplicati di un fattore fisso. Nessun errore, solo cifre grandi e plausibili.

**Perché.** Se in una richiesta al database che fa delle somme si aggiunge un collegamento (JOIN) a
un'altra tabella con il criterio sbagliato, ogni riga viene contata più volte — una per ogni riga collegata.
Le somme escono gonfiate esattamente di quel fattore.

**Perché è difficile da notare.** Il conteggio dei post, lì accanto, resta giusto (usa un conteggio "senza
doppioni"). Quindi la cifra che si controlla d'istinto è corretta, mentre le tre accanto sono sbagliate — la
combinazione più insidiosa.

**Come accorgersene.** Ogni volta che si aggiunge un collegamento a una richiesta che contiene delle
somme: eseguirla con e senza quel collegamento e confrontare i risultati. Se le somme cambiano, il
collegamento sta moltiplicando le righe. Il fatto che il conteggio dei post resti uguale **non** è una
garanzia che vada tutto bene.

### 2.2 Lo stesso partner contato più volte

**Cosa può succedere.** Percentuali più basse del vero, menu a tendina con lo stesso nome ripetuto,
filtri che non restituiscono nulla.

**Perché.** Il database permette di avere due partner con lo stesso nome nello stesso brand, e le righe
vecchie non vengono mai cancellate. Il risultato sono gruppi di righe con lo stesso nome: di solito una
contiene i dati veri, le altre sono vuote. Non possiamo impedirlo, perché non è il nostro database.

**Come è gestito.** C'è una regola che, tra le righe con lo stesso nome, sceglie sempre la stessa come
quella "buona" (in pratica: quella con più contenuti pubblicati; a parità, la più vecchia). Questa regola va
applicata in **due modi opposti** a seconda del caso, e la differenza è voluta:

- Quando si devono **mostrare o contare** i partner (tendine, percentuali) → si **escludono** le copie.
- Quando si sta **seguendo un collegamento già esistente** (un tag, un target) → si **reindirizza** al
  partner giusto, invece di escluderlo. Se qui si escludessero le copie, un tag collegato a una copia
  vuota resterebbe senza nessun partner — peggio del problema di partenza.

**Come accorgersene.** Se un conteggio di partner non torna con quello che si vede nel sistema di
Coders51, o un filtro dà zero senza motivo, cercare i doppioni. Regola pratica: ogni nuova richiesta che
tocca i partner deve chiarire in quale dei due casi si trova — se mostra/conta, esclude; se segue un
collegamento, reindirizza.

### 2.3 Percentuale di adozione oltre il 100%

**Cosa può succedere.** Una percentuale che supera il 100 — impossibile, quindi almeno questo si nota
subito.

**Perché.** Sopra e sotto la frazione si contavano due gruppi diversi. Basta un partner "orfano" (una
pubblicazione che punta a un partner non più presente) per rompere l'equilibrio.

**Come è gestito.** Sopra e sotto la frazione usano ora la stessa identica regola, scritta una volta sola e
applicata a entrambi i lati. Così è impossibile che i due gruppi divergano.

**Come accorgersene.** Qualunque valore di adozione sopra il 100% significa che quella regola è stata
applicata a un solo lato. Se qualcuno modifica quella parte, va ricontrollato subito.

### 2.4 L'indicatore delle credenziali non dice se i dati arrivano

**Cosa può succedere.** I numeri di un social smettono di aggiornarsi per settimane o mesi, e niente lo
segnala. Le credenziali risultano valide mentre gli aggiornamenti falliscono.

**Perché.** Esiste un indicatore che dice se le credenziali di accesso al social sono valide. Ma
"credenziali valide" e "aggiornamenti che funzionano" sono due cose diverse: le prime possono restare
a posto mentre i secondi falliscono.

**Come è gestito.** Il segnale affidabile è un altro: ogni contenuto nel database ha la data dell'ultimo
aggiornamento dei suoi numeri. Se per un social quella data è ferma da settimane, quel social non
riceve più dati — a prescindere da cosa dicano le credenziali. Su questo è costruito un avviso che
compare in cima alla dashboard.

**Come accorgersene.** È esattamente ciò che l'avviso ora fa in automatico. A mano: controllare, per
ogni social, la data dell'ultimo aggiornamento reale dei contenuti. Se è vecchia di settimane, quel social
è fermo.

### 2.5 "Zero visualizzazioni" non significa "pubblicazione fallita"

**Cosa succede (e tornerà a farsi notare).** Tra i contenuti con i risultati peggiori compaiono post con
zero visualizzazioni. Sembrano pubblicazioni andate in errore.

**Non è un errore.** Le pubblicazioni davvero fallite sono già escluse. Questi sono contenuti pubblicati
con successo che semplicemente non hanno generato interazioni.

> **Decisione della founder (definitiva): questi contenuti devono restare visibili.** Un post pubblicato
> che non genera nessuna interazione è esattamente ciò che la sezione "contenuti peggiori" serve a far
> emergere. Un filtro per nasconderli era stato provato e poi tolto su sua indicazione. **Non va
> reintrodotto.**

**Come accorgersene.** Prima di indagare, controllare il periodo del report: questi contenuti compaiono
solo su periodi lunghi (90 giorni o più), nel report standard a 30 giorni ci sono altri contenuti. E se
qualcuno chiede di nasconderli, verificare che sia una decisione della founder e non un'impressione
("sembrano un errore").

### 2.6 L'impaginazione delle tabelle lunghe nel PDF

**Cosa può succedere.** Nel PDF una tabella lunga viene spinta a inizio pagina nuova, lascia mezza
pagina bianca, e si spezza comunque.

**Perché.** C'è una regola di impaginazione che tiene unite le tabelle corte (giusta per quelle da poche
righe). Ma applicata a una tabella più alta di una pagina non può tenerla unita: la sposta sperando che
basti, non basta, e la spezza lo stesso.

**Come è gestito.** Per l'unica tabella che può superare la pagina è stata usata una regola diversa, che
le permette di continuare sulla pagina successiva ripetendo le intestazioni delle colonne. Resta un caso
aperto (la classifica dei partner oltre le 30 righe circa), descritto nella sezione 6.

**Come accorgersene.** Non si vede a schermo: si vede solo generando il PDF con un brand che abbia
abbastanza dati. Un report a 30 giorni su un brand piccolo non arriva mai al problema. Prima di toccare
l'impaginazione, generare un report lungo sul brand più grande.

### 2.7 La regola più importante: "niente filtro" non è "filtro vuoto"

Questo non è un errore già capitato: è la convenzione che tiene chiuse tutte le precedenti, ed è la
prima cosa che si rischia di rompere.

Nel codice ci sono due situazioni diverse che vanno trattate in modo opposto:

- **Nessun filtro attivo** → mostra tutti i partner.
- **Filtro attivo che non trova nessuno** → mostra zero risultati.

Il caso che le distingue: un tag a cui non è collegato nessun partner. Deve mostrare **zero**, non tutto.
Se qualcuno confonde le due cose (trattando "lista vuota" come "nessun filtro"), un tag vuoto mostra i
dati dell'intero brand invece di zero — un risultato che sembra perfettamente normale e non dà nessun
errore.

**Come accorgersene.** Dopo ogni modifica ai filtri, fare questa prova: selezionare un tag che non ha
partner. Se la dashboard mostra i dati dell'intero brand invece di zero, la regola è stata rotta.

---

## 3. Cose che dipendono da Coders51, non da noi

I punti seguenti **non si possono risolvere dal nostro lato**. Sono qui perché il costo peggiore non è il
limite in sé, ma il tempo che si perde a cercare nel nostro codice la causa di qualcosa che nel nostro
codice non c'è.

**Il database dice che qualcosa è rotto, ma non perché.** Esiste un elenco dei fallimenti degli
aggiornamenti, ma non contiene il motivo del fallimento (credenziale scaduta? permesso mancante?
social che ha cambiato le sue regole?). Ogni diagnosi parte quindi da un'ipotesi non verificabile. È per
questo che l'avviso descritto in 2.4 misura *l'effetto* (i dati che non si aggiornano) invece della *causa*:
la causa non è disponibile.

**LinkedIn è rimasto fermo per circa dieci mesi, da ottobre 2025 ad agosto 2026.** LinkedIn aveva
cambiato il modo di fornire i dati; la raccolta si è interrotta. Nessun allarme: le credenziali restavano
valide e i dati già raccolti restavano visibili, quindi la dashboard mostrava numeri semplicemente fermi.
Coders51 ha poi sistemato il collegamento ad agosto 2026, ed è servita la riconnessione manuale di
alcuni account. (Date e causa come riferite da Coders51; la ripartenza l'ho verificata sui dati.)

**Le comunicazioni ufficiali dei social sui loro cambiamenti arrivano a Coders51, non a ISUAL.** È
il punto che rende strutturale tutto il resto: ISUAL non ha modo di sapere in anticipo che
un'integrazione sta per rompersi. La prima notizia arriva dai dati che si fermano, cioè settimane o mesi
dopo. L'unica difesa sotto il nostro controllo è accorgersene presto — di nuovo, l'avviso.

---

## 4. Scelte fatte apposta (da non "correggere")

Decisioni volute che, senza la spiegazione accanto, sembrano errori. Chi le "sistema" senza leggere
questa sezione le rompe.

**Amplification Factor è una percentuale, non un moltiplicatore.** Indica quanta parte del reach
totale arriva dalla rete dei partner, in percentuale. Prima era un moltiplicatore ("la rete moltiplica per
3"), ma dava risultati assurdi quando un brand non aveva un reach proprio da mettere al
denominatore. La percentuale ha una scala chiusa (0–100%) e funziona sempre. Attenzione: con un
filtro partner attivo il reach del brand esce dal calcolo, e la formula darebbe un 100% credibile ma falso;
per questo, con qualsiasi filtro attivo, la card mostra "N/A" invece di un numero.

**Su questa card non c'è il colore verde/rosso, ed è voluto.** È una metrica che dice *da dove* arriva
il reach, non *se* il reach è stato buono. Una percentuale bassa significa solo che il brand pubblica
molto in proprio: colorarla di rosso suggerirebbe di pubblicare meno in proprio, che non è un consiglio
sensato.

**"Migliori" e "Peggiori" contenuti non mostrano mai lo stesso contenuto.** Sono ricavati dalla
stessa classifica ordinata, prendendo i primi e gli ultimi: così è impossibile che uno stesso contenuto
finisca in entrambi.

**Partner, Tag e Target si usano uno alla volta, non insieme.** Non è un limite tecnico: sono tre modi
diversi di selezionare gli stessi partner, e combinarli richiederebbe di decidere se l'incrocio è un "e" o un
"o" — una scelta di prodotto senza risposta ovvia. C'è un tentativo di combinarli lasciato in sospeso
(sezione 6).

**L'ordine delle card KPI si configura dal database, non dal codice.** Ordine, etichetta e visibilità
delle card stanno in una tabella e si modificano da un pannello nella dashboard, senza toccare il codice.

---

## 5. Come si lavora sul progetto

Per avviarlo in locale serve l'interprete Python dell'ambiente virtuale del progetto (il Python di sistema
non ha le librerie necessarie e dà errore).

**Non c'è il ricaricamento automatico.** Dopo una modifica al codice, il server va fermato e riavviato a
mano: altrimenti si continua a vedere la versione vecchia, convinti che la modifica non funzioni. È
l'errore che fa perdere più tempo. Per le modifiche ai file del browser (JavaScript, stili) invece basta un
ricaricamento forzato della pagina.

**Un solo server per volta.** Può capitare di avviare più server sulla stessa porta senza accorgersene:
le richieste vengono servite un po' dall'uno e un po' dall'altro, alcune da codice vecchio. Se lo stesso
ricaricamento dà due risultati diversi a caso, è questo. Controllare e lasciarne attivo uno solo.

**Per le verifiche sul database usare l'utente di sola lettura.** Le indagini si fanno su dati di
produzione: un comando di scrittura battuto per sbaglio su tabelle che non sono nostre non è
recuperabile. L'utente di sola lettura non può scrivere, quindi elimina il rischio.

**Dopo aver pubblicato online, verificare che il sito si sia davvero aggiornato.** Vedere il deploy
"verde" non basta: conviene generare un report o aprire la dashboard e controllare che il
comportamento sia quello nuovo. In particolare, verificare sempre anche il caso **con un filtro attivo**,
non solo quello senza: alcune metriche hanno comportamenti speciali che scattano solo con i filtri, e lì
un valore sbagliato sembra credibile.

---

## 6. Cosa resta da fare

Nessuna di queste è un lavoro interrotto a metà: sono cose lasciate da fare di proposito, con la ragione
accanto. Le prime due sono decisioni di prodotto, non compiti puramente tecnici.

**La classifica dei partner si impagina male oltre le 30 righe circa.** La soluzione tecnica sarebbe
mostrarne solo una parte, ma questo significa non mostrare dei partner nel report: è una decisione da
prendere con CTO e founder. Con i clienti attuali il problema non si presenta (il brand più grande ha 9
partner).

**Un nome di partner potrebbe finire in un PDF che non dovrebbe mostrarlo.** Il report è costruito
per non far riconoscere i singoli partner. Ma se si filtra per un tag o target che contiene un solo partner,
la classifica compare lo stesso con una riga sola e il nome in chiaro. Conta perché quel PDF può essere
inviato via email proprio al partner. La correzione va fatta con attenzione, verificando il risultato.

**Il tentativo di combinare i filtri (in sospeso) va riscritto, non ripristinato.** Il lavoro messo da parte
è vecchio e il codice attorno è cambiato: recuperarlo con un comando creerebbe problemi. Va riscritto
guardandolo, e prima ancora va deciso cosa deve significare combinare due filtri (incrocio o unione).

**Un dato calcolato ma non usato.** Una delle richieste calcola ancora un valore che nessuna parte del
report legge più. È innocuo, ma è lo stesso tipo di "residuo" che può trarre in inganno chi lo trova.
Segnalato e non rimosso, essendo alla consegna: è una pulizia che chi resta può fare verificando il
risultato.

**Due colori diversi in un caso particolare.** Il report che mostra tutti i brand insieme usa una tonalità
di blu diversa dagli altri report. Segnalato alla founder, che ha deciso di lasciarlo così per ora. È
preesistente, non una regressione.

---

## Appendice — Mappa dei file

| file | cosa fa | cosa NON c'è dentro |
|---|---|---|
| `database.py` | Tutte le richieste al database, il caricamento delle credenziali, la regola dei partner "canonici", l'avviso sui social fermi | Nessun calcolo sui dati: quelli sono in `kpi.py` |
| `kpi.py` | I calcoli sui dati: punteggi dei contenuti, salute dei partner, raggruppamenti per canale, formattazioni | Nessuna richiesta al database, nessuna grafica |
| `report.py` | La costruzione del PDF: lettura dei filtri, assemblaggio, colori | I calcoli (stanno in `kpi.py`) |
| `templates/report.html` | L'aspetto del PDF: le sezioni e gli stili di stampa | — |
| `dashboard/app.py` | Il server web e i suoi endpoint, la lettura dei filtri per la dashboard | I calcoli (stanno in `kpi.py`) |
| `dashboard/templates/dashboard.html` | La struttura della dashboard, il pannello KPI, l'avviso sui social | — |
| `static/app.js` | La dashboard interattiva nel browser | Nessun calcolo: arriva tutto già pronto dal server |
| `static/style.css` | Gli stili della dashboard | Gli stili di stampa del PDF (sono dentro il file del report) |
| I tre script di creazione | Creano e popolano le due tabelle nostre (colori/logo e configurazione KPI). Lo script dei logo va eseguito per ultimo | — |
| File di deploy | La configurazione per la pubblicazione su Render | — |

---

*Il criterio che ha funzionato meglio in questi mesi: prima di fidarsi di qualunque documento —
compreso questo — conviene controllare com'è la situazione davvero, guardando il database o il
codice. Il database cambia in continuazione, quindi qualsiasi documento invecchia.*
