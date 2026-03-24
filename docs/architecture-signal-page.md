# Architecture de la Page Signal

## Philosophie

La page Signal implémente le principe de **Feature Analysis** de de Prado : évaluer et valider les signaux techniques **avant** de construire une stratégie. Le pipeline refuse de sélectionner "le meilleur" indicateur — au lieu de cela, il élimine les mauvais et combine les survivants en un ensemble pondéré.

> *"The goal is not to find the best strategy, but to eliminate the worst ones."*
> — Principe implicite du Deflated Sharpe Ratio (Bailey & de Prado, 2014)

---

## Structure de la Page

```
┌────────────────────────────────────────────────────────────────────┐
│                         Page /signals                              │
│                                                                    │
│  ┌─────────────┐  ┌──────────────────────────────────────────────┐│
│  │  Stock      │  │  En-tête : Symbole + HorizonSelector         ││
│  │  Sidebar    │  │  [Court terme] [Moyen terme] [Long terme]    ││
│  │             │  │                                               ││
│  │  ATW ●      │  │  Onglets :                                    ││
│  │  BCP ●      │  │  [Technique ✓] [Fondamentale] [Quant] [Perso]││
│  │  IAM ●      │  │                                               ││
│  │  ...        │  │  ┌──────────────────────────────────────────┐ ││
│  │             │  │  │      TechnicalAnalysisPanel              │ ││
│  │             │  │  │                                          │ ││
│  │             │  │  │  Niveau 0: Speedomètre agrégé           │ ││
│  │             │  │  │  Niveau 1: 4 cartes famille              │ ││
│  │             │  │  │  Niveau 2: Drilldown + représentants     │ ││
│  │             │  │  │                                          │ ││
│  │             │  │  └──────────────────────────────────────────┘ ││
│  └─────────────┘  └──────────────────────────────────────────────┘│
└────────────────────────────────────────────────────────────────────┘
```

---

## Composants Frontend

### 1. StockSidebar

**Rôle** : Sélection du symbole à analyser.
- Charge la liste depuis `GET /market-data/catalog`
- Filtre uniquement les symboles ayant des données canoniques
- Indicateur de chargement pendant le calcul du signal

### 2. HorizonSelector

**Rôle** : Choix de l'horizon d'investissement.

| Horizon | Fenêtres OOS | Max données | Usage |
|---------|-------------|-------------|-------|
| **Court terme** | Train 1 an, Test 3 mois | 5 ans | Trading actif |
| **Moyen terme** | Train 2 ans, Test 6 mois | 10 ans | Swing trading |
| **Long terme** | Train 3 ans, Test 1 an | 20 ans | Investissement |

L'horizon affecte :
- Les fenêtres de paramètres (SMA-3 à SMA-90 pour court terme vs SMA-20 à SMA-400 pour long terme)
- La durée d'évaluation OOS
- La quantité de données historiques utilisées

### 3. TechnicalAnalysisPanel (technical-analysis-panel.tsx)

**Rôle** : Cœur de la page — orchestre l'affichage des signaux pour les 4 familles.

**Navigation en 3 niveaux** :

#### Niveau 0 — Agrégé
- Speedomètre (Investing.com-style) montrant le score combiné des 4 familles
- Un seul chiffre : score agrégé pondéré de toutes les familles
- Clic → descend au niveau 1

#### Niveau 1 — Familles
4 cartes côte à côte :

```
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│     SMA      │ │     RSI      │ │    MACD      │ │     OBV      │
│              │ │              │ │              │ │              │
│  [ScoreBar]  │ │    N/A       │ │    N/A       │ │    N/A       │
│   +42.7%     │ │  (bientôt)   │ │  (bientôt)   │ │  (bientôt)   │
│   ACHAT      │ │              │ │              │ │              │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
```

- Les familles non implémentées affichent "N/A" (honnêteté méthodologique)
- Chaque carte utilise `useFamilyEnsemble()` pour charger les données
- Les 4 requêtes sont lancées **en parallèle**

#### Niveau 2 — Drilldown Famille (SmaFamilyDrilldown)
Affiche le détail complet d'une famille :

```
┌──────────────────────────────────────────────────────────┐
│  Pipeline : 30 testées → 18 viables → 11 compét. → 5 rep│
│  [PipelineStepper]                                       │
│                                                          │
│  Score : +42.7% — "3 reps BUY, 2 reps HOLD"            │
│                                                          │
│  Représentants :                                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────┐ ┌─────┐│
│  │ SMA-50  │ │SMA-100  │ │ SMA-20  │ │SMA-150│ │SMA-8││
│  │ ● BUY   │ │ ● BUY   │ │ ● SELL  │ │● HOLD │ │●HOLD││
│  │ w=0.36  │ │ w=0.33  │ │ w=0.30  │ │w=0.18 │ │w=.15││
│  └─────────┘ └─────────┘ └─────────┘ └───────┘ └─────┘│
│                                                          │
│  Cliquer sur un représentant → page /signals/variant/{id}│
└──────────────────────────────────────────────────────────┘
```

### 4. SignalScoreBar (signal-score-bar.tsx)

**Rôle** : Affichage visuel du score d'une famille.

```
Label        Barre gradient                    Score
ACHAT    [▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓●░░░░░░░░░]      +42.7%
         rouge ←─────────────────→ vert
```

| Score | Label | Couleur |
|-------|-------|---------|
| > +50 | ACHAT FORT | Vert foncé |
| > +15 | ACHAT | Vert |
| ≥ -15 | NEUTRE | Gris |
| ≥ -50 | VENTE | Orange |
| < -50 | VENTE FORTE | Rouge |

3 tailles : `sm` (compact), `md` (standard), `lg` (header)

### 5. PipelineStepper (pipeline-stepper.tsx)

**Rôle** : Visualisation de l'entonnoir de filtrage (Couches A→E).

```
  ○ TESTÉES     ──→    ○ VIABLES    ──→    ○ COMPÉTITIFS  ──→   ● REPRÉSENTATIFS
   (30)         -12     (18)         -7      (11)          -6     (5)
   gris                  bleu                 indigo               émeraude
```

- Cercles colorés avec compteurs
- Flèches montrant les éliminations entre chaque étape
- Tooltips expliquant le critère de chaque filtre :
  - Viabilité : ≥ 40% fenêtres positives, ≥ 3 fenêtres valides
  - Compétitif : Top 60% par score, plancher à 0.25
  - Représentatif : |corrélation Pearson| < 0.85, max 10

### 6. Speedometer (speedometer.tsx)

**Rôle** : Jauge de type Investing.com pour le score global.

```
        Vente     Vente     Neutre    Achat     Achat
        Forte                                    Fort
          ╲         │         │         │         ╱
           ╲        │         │         │        ╱
            ╲       │         │         │       ╱
             ╲      │         │    ↗   │      ╱
              ────────────────●───────────────
                             ↑
                          Aiguille
                        Score: +42.7%
```

- SVG animé avec 5 zones colorées (rouge → vert)
- Aiguille pointant vers le score
- 3 tailles : `sm` (120×72), `md` (180×108), `lg` (260×156)

### 7. VariantDetailSheet (variant-detail-sheet.tsx)

**Rôle** : Panneau coulissant pour inspecter un représentant individuel.

Contenu :
- Badge de signal (BUY/SELL/HOLD)
- Contribution au score final (poids normalisé × signal)
- Cours actuel et valeur de l'indicateur
- Poids brut (score de fiabilité) et normalisé
- Explication texte (*"Close 150.25 > SMA-50 148.30 → BUY"*)

### 8. MethodologyModal (methodology-modal.tsx)

**Rôle** : Explication pédagogique de la méthodologie OOS.

6 sections :
1. Génération de l'univers (30 variantes par famille)
2. Entonnoir de filtrage (viable → compétitif → représentatif)
3. Scoring de fiabilité (4 composantes pondérées)
4. Agrégation pondérée (ensemble reliability-weighted)
5. Score agrégé ([-100, +100] → 5 labels)
6. Honnêteté (familles non implémentées = N/A)

---

## Page Détail Variante (/signals/variant/[id])

### Rôle
Inspection complète d'une variante individuelle — ses métriques OOS, sa position dans l'entonnoir, ses corrélations avec les autres variantes.

### Contenu

#### Métriques de Robustesse
```
┌──────────────┬──────────────┬──────────────┬──────────────┐
│ Sharpe Score │ Stabilité    │ Consistance  │ Drawdown     │
│ 0.72 (35%)   │ 0.80 (30%)   │ 0.65 (20%)   │ 0.88 (15%)   │
│              │              │              │              │
│ [████████░░] │ [████████░░] │ [██████░░░░] │ [█████████░] │
└──────────────┴──────────────┴──────────────┴──────────────┘
Score de fiabilité global : 0.75
```

#### Toutes les Variantes avec Raisons d'Élimination
| Variante | Score | Statut | Raison |
|----------|-------|--------|--------|
| SMA-50 | 0.78 | ● Sélectionné | Représentant #1 |
| SMA-48 | 0.75 | ✕ Redondant | Corrélé à SMA-50 (r=0.97) |
| SMA-100 | 0.71 | ● Sélectionné | Représentant #2 |
| SMA-5 | 0.18 | ✕ Non viable | 25% fenêtres positives (< 40%) |
| SMA-35 | 0.32 | ✕ Percentile | Score sous le seuil compétitif |

#### Matrice de Corrélation (Heatmap)
- Matrice N×N des corrélations Pearson entre toutes les variantes compétitives
- Les représentants sont marqués d'un badge
- Couleur : rouge (corrélation forte) → bleu (corrélation faible)

#### Fenêtres OOS Individuelles
Table détaillant chaque fenêtre walk-forward :
| Fenêtre | Train | Test | Sharpe | PnL | Max DD | Trades |
|---------|-------|------|--------|-----|--------|--------|
| 1 | Jan 2020 - Dec 2021 | Jan - Jun 2022 | 0.85 | +3,240 MAD | -4.2% | 12 |
| 2 | Mar 2020 - Feb 2022 | Mar - Aug 2022 | 1.12 | +5,100 MAD | -2.8% | 9 |
| ... | | | | | | |

#### Graphiques (via /variant-backtest)
- **Prix + indicateur + signal** : Cours en chandelier, SMA en overlay, flèches BUY/SELL
- **Equity curve OOS** : Courbe de capital sur toutes les fenêtres test
- **Drawdown** : Profondeur et durée des pertes
- **Par fenêtre** : Zoom sur chaque période test avec trades individuels

---

## Backend : Signal Engine

### Pipeline (core/quant_core/signal_engine/)

```
ensemble.py  ←── Point d'entrée : run_family_ensemble_full()
    │
    ├── candidates.py      Couche A : génération des 30 variantes
    ├── oos_eval.py         Couche B : walk-forward evaluation
    ├── robustness.py       Couche C : scoring multi-critères
    ├── survivor.py         Couche D : filtrage viable → compétitif
    ├── redundancy.py       Couche E : élimination par corrélation
    ├── current_signal.py   Couche F : signal courant par représentant
    └── ensemble.py         Couche G : agrégation pondérée
```

### Domain Models (domain.py)

| Modèle | Rôle | Champs clés |
|--------|------|-------------|
| `VariantDef` | Définition d'une variante | variant_id, family, archetype, params |
| `OOSWindowResult` | Résultat d'une fenêtre OOS | sharpe, max_drawdown, total_return, pnl, n_trades |
| `VariantRobustnessSummary` | Score de fiabilité | reliability_score, is_viable, 4 composantes |
| `VariantCurrentSignal` | Signal actuel | signal (+1/-1/0), explanation, indicator_value |
| `FamilyCombinedSignal` | Résultat ensemble | family_score_pct, representatives, funnel counts |

### Extensibilité

Ajouter une nouvelle famille nécessite uniquement :
1. `@register_family("nouvelle_famille", n_variants=30)` dans `candidates.py`
2. `@register_signal("nouvelle_famille", "archetype")` dans `oos_eval.py`

Le reste du pipeline (Couches B→G) s'applique automatiquement sans modification.

---

## Endpoints API

| Méthode | Route | Rôle | Cache |
|---------|-------|------|-------|
| POST | `/strategy/signal/sma-ensemble` | Signal SMA (legacy) | 5 min |
| POST | `/strategy/signal/family-ensemble` | Signal de n'importe quelle famille | 5 min |
| POST | `/strategy/signal/variant-detail` | Détail + corrélation + éliminations | — |
| POST | `/strategy/signal/variant-backtest` | Trades, equity curve, graphiques | 10 min |

### Chargement des données
- `load_ohlcv_for_symbol(db, symbol, timeframe)` charge le Parquet depuis MinIO
- Le cache API est en mémoire process (dict avec TTL)
- Clé de cache : `(family, symbol, horizon, timeframe, cost_bps)`

---

## Raisonnement Architectural

### Pourquoi un pipeline à 7 couches plutôt qu'une seule évaluation ?

1. **Couche A** existe car l'exploration systématique de l'espace des paramètres est plus rigoureuse que le choix subjectif
2. **Couche B** (WFA) est le gold standard de validation OOS (Pardo, 2008) — elle empêche le look-ahead bias
3. **Couche C** agrège en multi-critères car un seul Sharpe est insuffisant (un Sharpe de 2.0 avec un drawdown de 50% est dangereux)
4. **Couche D** filtre progressivement car il est important d'avoir un plancher absolu ET une sélection relative
5. **Couche E** élimine la redondance car sans elle, l'ensemble serait dominé par des variantes quasi-identiques
6. **Couche F** est séparée car le signal courant doit être calculé sur les données les plus récentes, pas sur les fenêtres OOS
7. **Couche G** pondère par fiabilité car l'equal-weighting donnerait trop de pouvoir aux survivants marginaux

### Pourquoi l'honnêteté méthodologique ?

- Afficher "N/A" pour les familles non implémentées plutôt qu'un score provisoire
- Forcer NEUTRE quand il n'y a pas assez de données ou pas de survivants
- Déclarer `methodology_status: "provisional"` quand les conditions ne sont pas remplies
- Tracer chaque élimination avec sa raison explicite

Cela s'inscrit dans la culture de rigueur des institutions financières réglementées : **mieux vaut ne rien dire que de dire quelque chose de faux**.

### Pourquoi la navigation en 3 niveaux ?

- **Niveau 0** : Le décideur veut un chiffre et une direction → Speedomètre
- **Niveau 1** : L'analyste veut savoir quelle famille contribue quoi → 4 cartes
- **Niveau 2** : Le quant veut inspecter chaque variante et comprendre les éliminations → Drilldown + page détail

Chaque niveau s'adresse à un profil utilisateur différent, du plus synthétique au plus granulaire.

---
