# Registre des risques

Le **Registre des risques** capture les risques d'architecture tout au long de leur cycle de vie — de l'identification à la mitigation, à l'évaluation résiduelle, à la surveillance et à la clôture (ou à l'acceptation formelle). Il vit comme l'onglet **Risque** du [module GRC](grc.md) à `/grc?tab=risk`.

## Alignement TOGAF

Le registre met en œuvre le processus de gestion des risques d'architecture de **TOGAF ADM Phase G — Implementation Governance** (TOGAF 10 §27) :

| Étape TOGAF | Ce que vous capturez |
|-------------|----------------------|
| Classification du risque | `Catégorie` (security, compliance, operational, technology, financial, reputational, strategic) |
| Identification du risque | `Titre`, `Description`, `Source` (manuelle ou promue depuis un constat TurboLens) |
| Évaluation initiale | `Probabilité initiale × Impact initial → Niveau initial` (dérivé automatiquement) |
| Mitigation | `Plan de mitigation`, `Propriétaire`, `Date cible de résolution` |
| Évaluation résiduelle | `Probabilité résiduelle × Impact résiduel → Niveau résiduel` (modifiable une fois la mitigation planifiée) |
| Surveillance / acceptation | Flux de `Statut` : identified → analysed → mitigation_planned → in_progress → mitigated → monitoring → closed (avec une branche `accepted` qui exige une justification explicite) |

## Créer un risque

Trois chemins mènent à la même boîte de dialogue **Créer un risque** — chaque variante pré-remplit des champs différents afin que vous puissiez modifier puis valider :

Les trois variantes incluent les champs **Propriétaire**, **Catégorie** et **Date cible de résolution** pour attribuer la responsabilité dès la création — sans avoir à rouvrir le risque.

La promotion est **idempotente** — une fois qu'un constat a été promu, son bouton bascule en **Ouvrir le risque R-000123** et navigue directement vers la page de détail du risque.

## Propriétaire → Todo + notification

Attribuer un **propriétaire** (à la création ou ultérieurement) crée automatiquement :

- Un **Todo système** sur la page Todos du propriétaire. La description est `[Risk R-000123] <titre>`, l'échéance reflète la date cible de résolution du risque, et le lien renvoie au détail du risque. Le Todo est marqué **fait** automatiquement lorsque le risque atteint `mitigated` / `monitoring` / `accepted` / `closed`.
- Une **notification de cloche** (`risk_assigned`) — visible dans le menu déroulant de la cloche et sur la page des notifications, avec un e-mail optionnel si l'utilisateur a activé cette préférence. L'auto-attribution déclenche aussi la cloche, afin que la trace reste cohérente entre les workflows d'équipe et personnels.

Effacer ou réattribuer le propriétaire maintient le Todo synchronisé — l'ancien est supprimé / réassigné.

## Lier les risques aux fiches

Les risques sont **plusieurs-à-plusieurs** avec les fiches. Un risque peut affecter plusieurs Applications ou Composants informatiques, et une fiche peut avoir plusieurs risques associés :

- Depuis la page de détail du risque : panneau **Fiches affectées** → rechercher et ajouter. Cliquez sur un `×` pour délier.
- Depuis n'importe quelle page de détail de fiche : un nouvel onglet **Risques** liste chaque risque associé à cette fiche, avec un retour en un clic vers le registre.

## Matrice des risques

La Vue d'ensemble Sécurité de TurboLens comme la page du Registre des risques affichent une carte thermique probabilité × impact 4×4. Les cellules sont **cliquables** — cliquez sur une cellule pour filtrer la liste en dessous sur ce compartiment, cliquez à nouveau (ou sur le × du chip) pour effacer. Dans le Registre des risques, vous pouvez basculer la matrice entre les vues **Initiale** et **Résiduelle** pour visualiser les progrès de la mitigation.

## Grille du registre

Le registre est une grille AG Grid qui reprend les standards de la page [Inventaire](inventory.md) : colonnes triables, filtrables et redimensionnables avec préférences utilisateur persistées (colonnes visibles, ordre de tri, état de la barre latérale). Un bouton **+ Nouveau risque** dans la barre d'outils ouvre le dialogue de création manuelle. **Exporter en CSV** télécharge l'ensemble filtré dans le même ordre de colonnes que l'écran — utile pour les dossiers d'audit ou pour partager le registre avec des parties prenantes sans compte Turbo EA.

## Propagation Risque ↔ Constat

Si un risque a été [promu depuis un constat TurboLens](turbolens.md#promote-a-finding-to-the-risk-register), les changements de statut se propagent **dans les deux sens** :

- Le constat porte un rétro-lien **Ouvrir le risque R-000123** dès la promotion (l'action est idempotente — cliquer à nouveau navigue vers le risque existant au lieu de créer un doublon).
- Quand le risque atteint `mitigated` / `monitoring` / `closed` / `accepted` (ou est supprimé), le moteur de rétro-propagation transitionne automatiquement chaque constat de conformité lié à la valeur correspondante (`mitigated` / `verified` / `accepted` / `in_review`). La justification d'acceptation capturée sur le risque est répercutée dans la note de revue du constat afin que la piste d'audit reste cohérente.

Cela maintient le Registre des risques (vue gouvernance) et la grille Conformité (vue opérationnelle) alignés sans entretien manuel.

## Flux de statut

La page de détail affiche toujours un unique bouton primaire **Étape suivante** et une petite rangée d'actions latérales, de sorte que le chemin séquentiel soit évident mais que les sorties de gouvernance restent à un clic :

| État actuel | Étape suivante (bouton primaire) | Actions latérales |
|---|---|---|
| identified | Démarrer l'analyse | Accepter le risque |
| analysed | Planifier la mitigation | Accepter le risque |
| mitigation_planned | Démarrer la mitigation | Accepter le risque |
| in_progress | Marquer comme atténué | Accepter le risque |
| mitigated | Démarrer la surveillance | Reprendre la mitigation · Clore sans surveillance |
| monitoring | Clore | Reprendre la mitigation · Accepter le risque |
| accepted | — | Rouvrir · Clore |
| closed | — | Rouvrir |

Graphe complet de transitions (forcé côté serveur) :

```
identified → analysed → mitigation_planned → in_progress → mitigated → monitoring → closed
       │           │             │                │            ▲           ▲
       └───────────┴─────────────┴────────────────┴──── accepted (justification requise)
                                                              │
                              reopen → in_progress ◄──────────┘
```

- **Accepter** un risque exige une justification d'acceptation. L'utilisateur, l'horodatage et la justification sont consignés dans l'enregistrement.
- **Rouvrir** un risque `accepted` / `closed` renvoie à `in_progress`. L'état `mitigated` autorise aussi une « Reprendre la mitigation » manuelle sans nécessiter une réouverture complète.

## Permissions

| Permission | Qui la reçoit par défaut |
|------------|---------------------------|
| `risks.view` | admin, bpm_admin, member, viewer |
| `risks.manage` | admin, bpm_admin, member |

Les lecteurs (viewers) peuvent voir le registre et les risques sur les fiches mais ne peuvent pas créer, modifier ou supprimer.
