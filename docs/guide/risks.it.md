# Registro dei Rischi

Il **Registro dei Rischi** cattura i rischi dell'architettura lungo l'intero ciclo di vita — dall'identificazione alla mitigazione, dalla valutazione residua al monitoraggio e alla chiusura (o all'accettazione formale). Vive come la scheda **Rischio** del [modulo GRC](grc.md) a `/grc?tab=risk`.

## Allineamento a TOGAF

Il registro implementa il processo di gestione dei rischi di architettura della **Fase G del TOGAF ADM — Governance dell'implementazione** (TOGAF 10 §27):

| Passo TOGAF | Cosa catturate |
|-------------|----------------|
| Classificazione del rischio | `Categoria` (security, compliance, operational, technology, financial, reputational, strategic) |
| Identificazione del rischio | `Titolo`, `Descrizione`, `Origine` (manuale o promossa da una evidenza TurboLens) |
| Valutazione iniziale | `Probabilità iniziale × Impatto iniziale → Livello iniziale` (derivato automaticamente) |
| Mitigazione | `Piano di mitigazione`, `Proprietario`, `Data obiettivo di risoluzione` |
| Valutazione residua | `Probabilità residua × Impatto residuo → Livello residuo` (modificabile una volta pianificata la mitigazione) |
| Monitoraggio / accettazione | Flusso di `Stato`: identified → analysed → mitigation_planned → in_progress → mitigated → monitoring → closed (con un ramo laterale `accepted` che richiede una motivazione esplicita) |

## Creare un rischio

Tre percorsi confluiscono nello stesso dialogo **Crea rischio** — ciascuna variante precompila campi diversi in modo che possiate modificare e inviare:

Tutte e tre le varianti includono i campi **Proprietario**, **Categoria** e **Data obiettivo di risoluzione**, così da assegnare responsabilità già in fase di creazione — senza riaprire il rischio.

La promozione è **idempotente** — una volta promossa un'evidenza, il suo pulsante diventa **Apri rischio R-000123** e porta direttamente alla pagina di dettaglio del rischio.

## Proprietà → Todo + notifica

Assegnare un **proprietario** (in fase di creazione o successivamente) genera automaticamente:

- Un **Todo di sistema** nella pagina Todos del proprietario. La descrizione è `[Risk R-000123] <titolo>`, la scadenza riflette la data obiettivo del rischio e il link torna al dettaglio del rischio. Il Todo è marcato **completato** automaticamente quando il rischio raggiunge `mitigated` / `monitoring` / `accepted` / `closed`.
- Una **notifica nella campanella** (`risk_assigned`) — visibile nel menu a tendina della campanella e nella pagina notifiche, con e-mail opzionale se l'utente ha abilitato la preferenza. Anche l'autoassegnazione fa suonare la campanella, così la traccia è coerente fra flussi di team e personali.

Rimuovere o riassegnare il proprietario mantiene il Todo sincronizzato — il vecchio viene rimosso / riassegnato.

## Collegare rischi alle card

I rischi sono **molti-a-molti** con le card. Un rischio può interessare più Applicazioni o Componenti IT, e una card può avere più rischi collegati:

- Dalla pagina di dettaglio del rischio: pannello **Card interessate** → cercate e aggiungete. Cliccate una `×` per scollegare.
- Da qualsiasi pagina di dettaglio card: la nuova scheda **Rischi** elenca ogni rischio collegato a quella card, con un ritorno in un clic al registro.

## Matrice dei rischi

Sia la Panoramica Sicurezza di TurboLens sia la pagina del Registro dei Rischi mostrano una heatmap probabilità × impatto 4×4. Le celle sono **cliccabili** — cliccate su una per filtrare la lista sottostante su quel bucket, cliccate di nuovo (o sulla × del chip) per pulire. Nel Registro dei Rischi potete alternare la matrice fra le viste **Iniziale** e **Residua** per vedere visivamente il progresso della mitigazione.

## Griglia del registro

Il registro è un AG Grid che segue gli standard della pagina [Inventario](inventory.md): colonne ordinabili, filtrabili e ridimensionabili con preferenze utente persistite (colonne visibili, ordinamento, stato della sidebar). Il pulsante **+ Nuovo rischio** in barra strumenti apre il dialogo di creazione manuale. **Esporta CSV** scarica il set filtrato nello stesso ordine di colonne mostrato a schermo — utile per dossier di audit o per condividere il registro con stakeholder senza account Turbo EA.

## Propagazione Rischio ↔ Riscontro

Se un Rischio è stato [promosso da un riscontro TurboLens](turbolens.md#promote-a-finding-to-the-risk-register), i cambi di stato fluiscono **in entrambe le direzioni**:

- Il riscontro porta un back-link **Apri rischio R-000123** dal momento della promozione (l'azione è idempotente — un nuovo click naviga al rischio esistente invece di crearne un duplicato).
- Quando il Rischio raggiunge `mitigated` / `monitoring` / `closed` / `accepted` (o viene eliminato), il motore di back-propagation transiziona automaticamente ogni riscontro di conformità collegato al valore corrispondente (`mitigated` / `verified` / `accepted` / `in_review`). La motivazione di accettazione catturata sul Rischio viene rispecchiata nella nota di revisione del riscontro così che la pista di audit resti coerente.

Questo mantiene allineati il Registro dei Rischi (vista governance) e la griglia di Conformità (vista operativa) senza manutenzione manuale.

## Flusso di stato

La pagina di dettaglio mostra sempre un unico pulsante primario **Passo successivo** più una piccola riga di azioni laterali, così che il percorso sequenziale sia ovvio ma le vie di uscita di governance restino a un clic:

| Stato attuale | Passo successivo (pulsante primario) | Azioni laterali |
|---|---|---|
| identified | Avvia analisi | Accetta rischio |
| analysed | Pianifica mitigazione | Accetta rischio |
| mitigation_planned | Avvia mitigazione | Accetta rischio |
| in_progress | Segna come mitigato | Accetta rischio |
| mitigated | Avvia monitoraggio | Riprendi mitigazione · Chiudi senza monitoraggio |
| monitoring | Chiudi | Riprendi mitigazione · Accetta rischio |
| accepted | — | Riapri · Chiudi |
| closed | — | Riapri |

Grafo completo delle transizioni (forzato lato server):

```
identified → analysed → mitigation_planned → in_progress → mitigated → monitoring → closed
       │           │             │                │            ▲           ▲
       └───────────┴─────────────┴────────────────┴──── accepted (motivazione richiesta)
                                                              │
                              reopen → in_progress ◄──────────┘
```

- **Accettare** un rischio richiede una motivazione di accettazione. Utente, timestamp e motivazione vengono registrati sul record.
- **Riaprire** un rischio `accepted` / `closed` riporta a `in_progress`. Lo stato `mitigated` consente anche una «Riprendi mitigazione» manuale senza bisogno di una riapertura completa.

## Autorizzazioni

| Autorizzazione | Chi la riceve per impostazione predefinita |
|----------------|-------------------------------------------|
| `risks.view` | admin, bpm_admin, member, viewer |
| `risks.manage` | admin, bpm_admin, member |

I viewer possono vedere il registro e i rischi sulle card ma non possono creare, modificare o eliminare.
