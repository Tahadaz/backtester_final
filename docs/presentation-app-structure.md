# Présentation 1 : Architecture Générale de la Plateforme

## Structure Inspirée des Trading Desks Quantitatifs

---

## Slide 1 — Titre

**Plateforme de Backtesting Quantitatif**
*Architecture modulaire inspirée de Marcos López de Prado — Advances in Financial Machine Learning*

Stage — [Nom de la banque d'investissement]
[Votre nom] — [Date]

---

## Slide 2 — Le Problème

**Comment les quant desks échouent :**

- Le backtesting classique mélange données, signaux, stratégie et exécution dans un seul pipeline
- Résultat : **overfitting**, **look-ahead bias**, résultats non reproductibles
- De Prado (Ch. 1) : *"The rate of false discoveries in the financial literature is alarmingly high"*

**Ce que de Prado propose :**

- Séparer les responsabilités en **méta-étapes indépendantes**
- Chaque étape produit un livrable validé avant de passer à la suivante
- La même structure que les desks quantitatifs des fonds institutionnels

---

## Slide 3 — La Structure de Production de de Prado

De Prado décrit 5 étapes dans la chaîne de production d'une stratégie quantitative (Ch. 1, Fig. 1.1) :

```
1. Data Curation    →  Données propres, vérifiées, sans biais
2. Feature Analysis →  Signaux techniques, fondamentaux, alternatifs
3. Strategy Design  →  Règles d'entrée/sortie, sizing, contraintes
4. Backtesting      →  Validation walk-forward, métriques OOS
5. Deployment       →  Exécution live, monitoring, feedback loop
```

**Principe clé** : Chaque étape est un **module indépendant** avec des entrées/sorties bien définies. Un data scientist ne touche pas au code d'exécution. Un portfolio manager ne modifie pas le pipeline de données.

> *"The key to avoiding false discoveries is to structure your research process as a production chain."*
> — de Prado, AFML, Ch. 1

---

## Slide 4 — Notre Implémentation : 4 Pages

```
┌─────────┐     ┌─────────┐     ┌──────────┐     ┌───────────┐
│  DATA   │ ──→ │ SIGNAL  │ ──→ │ STRATEGY │ ──→ │ BACKTEST  │
│  Page   │     │  Page   │     │   Page   │     │   Page    │
└─────────┘     └─────────┘     └──────────┘     └───────────┘
   Curate         Analyse         Construire       Valider
```

| Page | Rôle de Prado | Livrable | Statut |
|------|---------------|----------|--------|
| **Data** | Data Curation | OHLCV propre, calendrier validé | ✅ Complet |
| **Signal** | Feature Analysis | Score ensemble [-100, +100] par famille | ✅ Phase 1 |
| **Strategy** | Strategy Design | Règles d'entrée/sortie paramétrées | 🔜 À venir |
| **Backtest** | Backtesting | Métriques OOS, equity curve, PnL | 🔜 À venir |

---

## Slide 5 — Pourquoi Cette Séparation ?

### 1. Éviter l'overfitting (de Prado, Ch. 11-12)

- Si les signaux sont validés **avant** la construction de la stratégie, on ne peut pas ajuster les paramètres de signal pour flatter le backtest
- La page Signal utilise l'évaluation **out-of-sample** (walk-forward) indépendamment du backtest final

### 2. Réutilisabilité

- Un même signal validé peut alimenter **plusieurs stratégies**
- Les données de la page Data sont utilisées par Signal, Strategy et Backtest sans transformation

### 3. Traçabilité

- Chaque décision est visible et inspectable à chaque étape
- On peut identifier **où** un résultat a échoué : données manquantes ? Signal faible ? Mauvaise stratégie ?

### 4. Collaboration (structure desk)

- **Data Engineer** → Page Data (qualité, ingestion, scheduling)
- **Quant Researcher** → Page Signal (indicateurs, robustesse, ensemble)
- **Portfolio Manager** → Page Strategy + Backtest (règles, risque, allocation)

---

## Slide 6 — Page Data : Curation des Données

**Philosophie** : Les données sont un actif de première classe, pas un input passif.

```
Sources               Ingestion               Stockage Canonique
┌──────────┐         ┌──────────────┐         ┌──────────────┐
│ Excel    │───┐     │ Détection    │         │ Parquet      │
│ (BMCE)   │   │     │ automatique  │         │ OHLCV        │
├──────────┤   ├────→│ de format    │────────→│ UTC, float64 │
│ Bourse   │   │     │ + nettoyage  │         │ par symbole  │
│ Direct   │───┘     │ + validation │         │ dans MinIO   │
├──────────┤         └──────────────┘         └──────────────┘
│ Yahoo    │───→  Refresh quotidien 18h
└──────────┘
```

**Fonctionnalités clés :**
- Upload Excel multi-format (BMCE nouveau, BMCE ancien, Investing.com)
- Parsing intelligent des dates ambiguës (DD/MM vs MM/DD) via programmation dynamique
- Calendrier de disponibilité avec jours fériés marocains
- Refresh automatique quotidien après clôture (18h Casablanca)
- Merge delta : les nouvelles données écrasent uniquement si elles diffèrent (>0.1%)

---

## Slide 7 — Page Signal : Analyse des Features

**Philosophie** : Chaque signal est évalué **avant** d'être utilisé. Pas de signal sans preuve OOS.

```
30 variantes     Évaluation OOS    Filtre de         Ensemble
par famille      Walk-Forward      Robustesse        Pondéré
┌─────────┐     ┌──────────────┐   ┌───────────┐    ┌──────────┐
│ SMA-3   │     │ Train│Test   │   │ Viable?   │    │ Score    │
│ SMA-5   │────→│ Train│Test   │──→│ Compétitif│───→│ [-100,   │
│ ...     │     │ Train│Test   │   │ Représent.│    │  +100]   │
│ SMA-400 │     │ (rolling)    │   │ (corr<85%)│    │          │
└─────────┘     └──────────────┘   └───────────┘    └──────────┘
```

**Pipeline en 7 couches (A→G)** — voir Présentation 2 pour le détail complet.

**Familles supportées** : SMA, RSI, MACD, OBV (extensible via décorateur `@register_family`)

---

## Slide 8 — Page Strategy (À Venir)

**Objectif** : Construire des règles de trading à partir des signaux validés.

```
Signaux Validés      Règles Paramétrées      Stratégie Composite
┌─────────────┐     ┌──────────────────┐     ┌────────────────┐
│ SMA: BUY    │     │ Entrée: si score │     │ Logique        │
│ RSI: SELL   │────→│   > seuil_achat  │────→│ combinée       │
│ MACD: BUY   │     │ Sortie: si score │     │ + sizing        │
│ OBV: NEUTRAL│     │   < seuil_vente  │     │ + stop-loss    │
└─────────────┘     └──────────────────┘     └────────────────┘
```

**Ce qui est prévu :**
- Combiner les scores de plusieurs familles de signaux
- Définir des seuils d'entrée/sortie
- Ajouter des contraintes de risque (max drawdown, position sizing)
- Walk-forward optimization des paramètres de stratégie

---

## Slide 9 — Page Backtest (À Venir)

**Objectif** : Valider la stratégie complète avec des métriques OOS rigoureuses.

```
Stratégie         Walk-Forward           Métriques
Complète          Optimization           Finales
┌──────────┐     ┌──────────────────┐   ┌──────────────┐
│ Règles   │     │ Fold 1: Train→OOS│   │ Sharpe: 1.24 │
│ + Sizing │────→│ Fold 2: Train→OOS│──→│ CAGR: 12.3%  │
│ + Risk   │     │ Fold N: Train→OOS│   │ MaxDD: -8.7% │
└──────────┘     └──────────────────┘   │ Win%: 58%    │
                                        └──────────────┘
```

**Principes de validation (de Prado, Ch. 12) :**
- Combinatorial Purged Cross-Validation (CPCV) pour éviter le leakage
- Walk-Forward Analysis comme standard de validation
- Deflated Sharpe Ratio pour corriger le biais de sélection

---

## Slide 10 — Stack Technique

```
┌──────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js 14)                  │
│  React + TypeScript + Tailwind + shadcn/ui + Plotly.js   │
├──────────────────────────────────────────────────────────┤
│                    API (FastAPI + Python)                 │
│           Pydantic schemas + SWR caching                 │
├──────────────────────────────────────────────────────────┤
│                  CORE (quant_core Python)                 │
│    Signal Engine │ Optimize │ Portfolio │ WFO │ Numba    │
├──────────────────────────────────────────────────────────┤
│                   INFRASTRUCTURE                         │
│  PostgreSQL 16 │ Redis (RQ) │ MinIO (S3) │ Docker       │
└──────────────────────────────────────────────────────────┘
```

| Composant | Technologie | Rôle |
|-----------|-------------|------|
| Base de données | PostgreSQL 16 | Runs, datasets, stock master, market data |
| File d'attente | Redis + RQ | Jobs async (ingestion, refresh, backtest) |
| Stockage objets | MinIO (S3) | Parquets OHLCV, artefacts de runs |
| Frontend | Next.js 14 | SPA avec App Router, SWR polling |
| Backend | FastAPI | REST API, validation Pydantic |
| Calcul | Numba JIT | Kernels optimisés pour backtest (38x speedup) |

---

## Slide 11 — Flux de Données End-to-End

```
Excel/Bourse/Yahoo
       │
       ▼
  ┌─────────────────┐
  │   Ingestion     │  Worker RQ → Parquet → MinIO
  │   (Data Page)   │  Validation + calendrier marocain
  └────────┬────────┘
           │  OHLCV propre (UTC, float64)
           ▼
  ┌─────────────────┐
  │  Signal Engine  │  30 variantes × 4 familles
  │  (Signal Page)  │  OOS walk-forward → robustesse → ensemble
  └────────┬────────┘
           │  Score [-100, +100] + attribution par variante
           ▼
  ┌─────────────────┐
  │   Strategy      │  Règles + sizing + contraintes
  │  (Strategy Page)│  (à venir)
  └────────┬────────┘
           │  Stratégie paramétrée
           ▼
  ┌─────────────────┐
  │   Backtest      │  WFO + métriques OOS
  │  (Backtest Page)│  Equity curve + trade ledger
  └─────────────────┘
```

---

## Slide 12 — Références et Crédibilité

### Ouvrages

| Référence | Concept utilisé |
|-----------|----------------|
| **de Prado, M.L. (2018)** *Advances in Financial Machine Learning* | Pipeline modulaire, CPCV, Deflated Sharpe |
| **de Prado, M.L. (2020)** *Machine Learning for Asset Managers* | Feature importance, signal quality |
| **Pardo, R. (2008)** *The Evaluation and Optimization of Trading Strategies* | Walk-Forward Analysis, OOS testing |
| **Bailey, D.H. & de Prado, M.L. (2014)** *The Deflated Sharpe Ratio* | Correction du biais de sélection |

### Principes appliqués

1. **Séparation des méta-étapes** (de Prado, Ch. 1) → 4 pages indépendantes
2. **Walk-Forward Analysis** (Pardo) → Évaluation OOS rolling
3. **Feature importance avant backtest** (de Prado, Ch. 8) → Signal validé avant stratégie
4. **Ensemble methods** (de Prado, Ch. 6-8) → Agrégation pondérée par robustesse
5. **Data quality first** (de Prado, Ch. 2-3) → Page Data comme fondation

---

## Slide 13 — Conclusion

**Ce que cette architecture garantit :**

1. **Pas de look-ahead bias** — les signaux sont évalués en walk-forward strict
2. **Pas d'overfitting** — la séparation signal/stratégie empêche l'ajustement circulaire
3. **Traçabilité complète** — chaque variante est inspectable (OOS windows, trades, corrélation)
4. **Extensibilité** — nouvelles familles de signaux via `@register_family`, sans changer le core
5. **Rigueur institutionnelle** — calendrier marocain, merge delta, scheduling automatique

> *"Investment firms that do not structure their research as a modular production chain are likely to produce a large number of false discoveries."*
> — Marcos López de Prado, Advances in Financial Machine Learning

---
