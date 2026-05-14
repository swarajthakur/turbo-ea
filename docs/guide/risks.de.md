# Risikoregister

Das **Risikoregister** erfasst Architektur-Risiken über ihren gesamten Lebenszyklus — von der Identifikation über Minderung, Rest-Bewertung und Überwachung bis zum Abschluss (oder zur formalen Akzeptanz). Es lebt als Reiter **Risk** im [GRC-Modul](grc.md) unter `/grc?tab=risk`.

## TOGAF-Ausrichtung

Das Register setzt den Architektur-Risikomanagement-Prozess aus **TOGAF ADM Phase G — Implementation Governance** (TOGAF 10 §27) um:

| TOGAF-Schritt | Was Sie erfassen |
|---------------|------------------|
| Risiko-Klassifizierung | `Kategorie` (security, compliance, operational, technology, financial, reputational, strategic) |
| Risiko-Identifikation | `Titel`, `Beschreibung`, `Quelle` (manuell oder aus einem TurboLens-Befund übernommen) |
| Initial-Bewertung | `Initial-Wahrscheinlichkeit × Initial-Auswirkung → Initial-Level` (automatisch abgeleitet) |
| Minderung | `Minderungsplan`, `Eigentümer`, `Ziel-Erledigungsdatum` |
| Rest-Bewertung | `Rest-Wahrscheinlichkeit × Rest-Auswirkung → Rest-Level` (editierbar, sobald Minderung geplant ist) |
| Überwachung / Akzeptanz | `Status`-Workflow: identified → analysed → mitigation_planned → in_progress → mitigated → monitoring → closed (mit einem Seitenzweig `accepted`, der eine explizite Begründung verlangt) |

## Ein Risiko anlegen

Drei Pfade münden in denselben Dialog **Risiko anlegen** — jede Variante füllt unterschiedliche Felder vor, sodass Sie bearbeiten und absenden können:

Alle drei Varianten enthalten die Felder **Eigentümer**, **Kategorie** und **Ziel-Erledigungsdatum**, sodass Verantwortlichkeit bereits beim Anlegen zugewiesen werden kann — ohne das Risiko erneut zu öffnen.

Die Überführung ist **idempotent** — sobald ein Befund überführt wurde, ändert sich seine Schaltfläche zu **Risiko R-000123 öffnen** und navigiert direkt zur Risikodetailseite.

## Eigentümerschaft → Todo + Benachrichtigung

Einem Risiko einen **Eigentümer** zuzuweisen (sei es beim Anlegen oder später) bewirkt automatisch:

- Ein **System-Todo** auf der Todos-Seite des Eigentümers wird erstellt. Die Beschreibung lautet `[Risk R-000123] <Titel>`, das Fälligkeitsdatum spiegelt das Ziel-Erledigungsdatum des Risikos, und der Link springt zurück zur Risikodetailseite. Das Todo wird automatisch als **erledigt** markiert, sobald das Risiko `mitigated` / `monitoring` / `accepted` / `closed` erreicht.
- Eine **Glocken-Benachrichtigung** (`risk_assigned`) wird ausgelöst — sichtbar im Glocken-Dropdown und auf der Benachrichtigungsseite, mit optionalem E-Mail-Versand, sofern der Benutzer dies aktiviert hat. Auch Selbstzuweisung löst die Glocke aus, damit die Spur im Team- und im persönlichen Workflow konsistent ist.

Eigentümer entfernen oder neu zuweisen hält das Todo synchron — das alte wird entfernt/neu zugewiesen.

## Risiken mit Karten verknüpfen

Risiken stehen in einer **M:N-Beziehung** mit Karten. Ein Risiko kann mehrere Anwendungen oder IT-Komponenten betreffen, und eine Karte kann mehrere Risiken verknüpft haben:

- Von der Risikodetailseite aus: Panel **Betroffene Karten** → suchen und hinzufügen. Klicken Sie auf ein `×`, um die Verknüpfung zu lösen.
- Von jeder Kartendetailseite aus: ein neuer **Risiken**-Tab listet jedes mit dieser Karte verknüpfte Risiko, mit einem Ein-Klick-Weg zurück ins Register.

## Risikomatrix

Sowohl die Sicherheits-Übersicht von TurboLens als auch die Risikoregister-Seite rendern eine 4×4-Heatmap Wahrscheinlichkeit × Auswirkung. Zellen sind **klickbar** — ein Klick filtert die Liste darunter auf diesen Bucket, ein weiterer Klick (oder das × des Chips) löscht den Filter. Im Risikoregister können Sie die Matrix zwischen **Initial**- und **Rest**-Ansicht umschalten, damit sich der Fortschritt der Minderung visuell zeigt.

## Register-Grid

Das Register ist ein AG-Grid, das den Standards der [Inventar](inventory.md)-Seite folgt: sortierbare, filterbare und in der Breite anpassbare Spalten mit persistierten Nutzereinstellungen (sichtbare Spalten, Sortierung, Sidebar-Zustand). Über die Symbolleiste öffnest du mit **+ Neues Risiko** den manuellen Anlage-Dialog. **CSV exportieren** lädt die gefilterte Menge in derselben Spaltenreihenfolge herunter, die auf dem Bildschirm sichtbar ist — nützlich für Audit-Pakete oder für die Weitergabe an Stakeholder ohne Turbo-EA-Login.

## Risiko ↔ Befund-Propagation

Wenn ein Risiko aus einem TurboLens-Befund [überführt](turbolens.md#promote-a-finding-to-the-risk-register) wurde, fließen Statusänderungen **in beide Richtungen**:

- Der Befund trägt ab dem Moment der Überführung einen Rückverweis **Risiko R-000123 öffnen** (die Aktion ist idempotent — ein erneuter Klick navigiert zum bestehenden Risiko statt ein Duplikat anzulegen).
- Erreicht das Risiko `mitigated` / `monitoring` / `closed` / `accepted` (oder wird gelöscht), transitioniert die Back-Propagation-Engine automatisch jeden verknüpften Compliance-Befund passend (`mitigated` / `verified` / `accepted` / `in_review`). Die im Risiko erfasste Akzeptanzbegründung wird in die Prüfnotiz des Befunds gespiegelt, damit der Audit-Pfad konsistent bleibt.

So bleiben das Risikoregister (Governance-Sicht) und das Compliance-Grid (operative Sicht) ohne manuelle Pflege aufeinander abgestimmt.

## Statusworkflow

Die Detailseite zeigt immer eine einzige primäre Schaltfläche **Nächster Schritt** sowie eine kleine Zeile mit Seitenaktionen, damit der sequenzielle Pfad klar ist, Governance-Ausstiege aber einen Klick entfernt bleiben:

| Aktueller Status | Nächster Schritt (primär) | Seitenaktionen |
|---|---|---|
| identified | Analyse starten | Risiko akzeptieren |
| analysed | Minderung planen | Risiko akzeptieren |
| mitigation_planned | Minderung starten | Risiko akzeptieren |
| in_progress | Als gemindert markieren | Risiko akzeptieren |
| mitigated | Überwachung starten | Minderung fortsetzen · Ohne Überwachung schliessen |
| monitoring | Schliessen | Minderung fortsetzen · Risiko akzeptieren |
| accepted | — | Wiedereröffnen · Schliessen |
| closed | — | Wiedereröffnen |

Vollständiger Übergangsgraph (serverseitig erzwungen):

```
identified → analysed → mitigation_planned → in_progress → mitigated → monitoring → closed
       │           │             │                │            ▲           ▲
       └───────────┴─────────────┴────────────────┴──── accepted (Begründung erforderlich)
                                                              │
                              reopen → in_progress ◄──────────┘
```

- **Akzeptieren** eines Risikos erfordert eine Akzeptanz-Begründung. Benutzer, Zeitstempel und Begründung werden auf dem Datensatz erfasst.
- **Wiedereröffnen** eines `accepted`- / `closed`-Risikos führt zurück zu `in_progress`. Bei `mitigated` ist zudem ein manuelles «Minderung fortsetzen» verfügbar, ohne dass ein vollständiges Wiedereröffnen nötig ist.

## Berechtigungen

| Berechtigung | Wer erhält sie standardmässig |
|--------------|-------------------------------|
| `risks.view` | admin, bpm_admin, member, viewer |
| `risks.manage` | admin, bpm_admin, member |

Viewer sehen das Register und Risiken auf Karten, können aber nicht anlegen, bearbeiten oder löschen.
