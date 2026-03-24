# Présentation 2 : Le Moteur de Signaux — Architecture Détaillée

## Du Candidat au Signal Final : Un Pipeline de Filtrage Rigoureux

---

## Slide 1 — Titre

**Signal Engine : Pipeline de Filtrage OOS en 7 Couches**
*De 120 variantes à un signal unique — sans overfitting*

Stage — [Nom de la banque d'investissement]
[Votre nom] — [Date]

---

## Slide 2 — Le Problème Fondamental

### Pourquoi ne pas juste prendre le "meilleur" indicateur ?

- **Biais de sélection** : Si on teste 100 variantes et qu'on prend la meilleure, on a de fortes chances de sélectionner du bruit
- **Bailey & de Prado (2014)** : Le *Deflated Sharpe Ratio* montre que tester N stratégies et choisir la meilleure donne un Sharpe gonflé proportionnellement à √(2 × ln(N))
- **Overfitting in-sample** : Un SMA-47 peut surperformer un SMA-50 purement par hasard sur la période de test

### La solution : un pipeline de filtrage progressif

Au lieu de choisir "le meilleur", on élimine les mauvais et on combine les survivants.

```
120 candidats ──→ ~18 viables ──→ ~11 compétitifs ──→ ~5 représentatifs ──→ 1 score
```

> *"The goal is not to find the best strategy, but to eliminate the worst ones and combine the survivors."*
> — Principe de construction d'ensemble (de Prado, Ch. 6)

---

## Slide 3 — Vue d'Ensemble du Pipeline

```
Couche A ─── Univers des Candidats ──────────── 30 variantes / famille
     │
Couche B ─── Évaluation OOS Walk-Forward ────── Sharpe, PnL, DD par fenêtre
     │
Couche C ─── Scoring de Robustesse ──────────── Score de fiabilité [0, 1]
     │
Couche D ─── Filtrage des Survivants ────────── Viable → Compétitif
     │
Couche E ─── Réduction de Redondance ────────── Corrélation Pearson < 0.85
     │
Couche F ─── Signal Courant ─────────────────── BUY / SELL / HOLD par variante
     │
Couche G ─── Ensemble Pondéré ───────────────── Score final [-100, +100]
```

**4 familles** × **30 variantes** = **120 candidats** évalués indépendamment

---

## Slide 4 — Couche A : Univers des Candidats

### Principe : Explorer systématiquement l'espace des paramètres

Chaque famille d'indicateurs génère **30 variantes** avec des paramètres prédéfinis adaptés à l'horizon.

| Famille | Archétype | Paramètres | Logique |
|---------|-----------|------------|---------|
| **SMA** | `price_vs_sma` | Fenêtre: [3..400] | Achat si prix > SMA, vente sinon |
| **RSI** | `rsi_level` | Période: [5..30], seuils: (30/70), (25/75), (20/80) | Mean-reversion : achat si RSI < seuil bas |
| **MACD** | `macd_cross` | Fast: [6..15], slow: [16..40], signal: [7..12] | Achat si ligne MACD > ligne signal |
| **OBV** | `obv_trend` | Période EMA: [3..400] | Achat si OBV > EMA(OBV) |

### Adaptation par horizon

| Horizon | Train | Test | Step | Max données | Fenêtres SMA |
|---------|-------|------|------|-------------|--------------|
| Court terme | 252 j (1 an) | 63 j (3 mois) | 21 j (1 mois) | 5 ans | [3, 5, 7..90] |
| Moyen terme | 504 j (2 ans) | 126 j (6 mois) | 42 j (2 mois) | 10 ans | [10, 15, 18..250] |
| Long terme | 756 j (3 ans) | 252 j (1 an) | 63 j (3 mois) | 20 ans | [20, 30, 40..400] |

**Pourquoi 30 variantes ?** Assez pour couvrir l'espace (de Prado recommande une grille dense), pas trop pour éviter l'explosion combinatoire.

**Identifiant déterministe** : Chaque variante a un `variant_id` stable (SHA-256 de famille + paramètres). Cela garantit la reproductibilité.

---

## Slide 5 — Couche B : Évaluation Walk-Forward OOS

### Le cœur de la rigueur : aucun regard vers le futur

```
Données historiques (ex: 5 ans pour horizon court)
├── [══TRAIN══][TEST]                    Fenêtre 1
├──      [══TRAIN══][TEST]               Fenêtre 2
├──           [══TRAIN══][TEST]          Fenêtre 3
├──                [══TRAIN══][TEST]     Fenêtre 4
└──                     [══TRAIN══][TEST] Fenêtre 5
                                          ↑
                                    Avance de "step" jours
```

**Protocole strict :**

1. Le signal est calculé **une seule fois** sur tout l'historique (pas recalculé par fenêtre)
2. La période **train** sert uniquement à réchauffer l'indicateur (warmup)
3. L'évaluation se fait **uniquement sur la période test** (out-of-sample)
4. Le rendement est calculé sur le bar **suivant** : `return[t] = close[t+1]/close[t] - 1`
5. Les coûts de transaction sont inclus : `cost_bps × |changement de signal|`

> **Référence** : Pardo, R. (2008) *The Evaluation and Optimization of Trading Strategies* — Ch. 7-9 définissent le Walk-Forward Analysis comme le gold standard de validation.

### Métriques par fenêtre

| Métrique | Calcul | Interprétation |
|----------|--------|----------------|
| `sharpe` | mean(ret) / std(ret) × √252 | Performance ajustée au risque |
| `max_drawdown` | max(peak - trough) / peak | Pire perte depuis un sommet |
| `total_return` | ∏(1 + ret) - 1 | Rendement total net |
| `cagr` | (1 + total_return)^(252/n_bars) - 1 | Rendement annualisé composé |
| `n_trades` | count(signal changes) | Activité de trading |
| `fraction_positive_bars` | bars positifs / total bars | Régularité des gains |

**Minimum requis** : ≥ 20 bars par fenêtre pour qu'elle soit valide.

---

## Slide 6 — Couche C : Scoring de Robustesse

### D'une série de fenêtres à un score unique de fiabilité

Le score de robustesse agrège les résultats OOS en **4 composantes** :

```
┌──────────────────────────────────────────────────────────────┐
│                   Score de Fiabilité [0, 1]                  │
│                                                              │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────┐│
│  │  Sharpe    │  │ Stabilité  │  │Consistance │  │Drawdown││
│  │  Score     │  │  Score     │  │  Score     │  │ Score  ││
│  │  (35%)     │  │  (30%)     │  │  (20%)     │  │ (15%) ││
│  └────────────┘  └────────────┘  └────────────┘  └────────┘│
└──────────────────────────────────────────────────────────────┘
```

| Composante | Poids | Calcul | Ce qu'elle capture |
|------------|-------|--------|-------------------|
| **Sharpe Score** | 35% | `clamp((mean_sharpe + 0.5) / 2.0)` | Performance absolue |
| **Stability Score** | 30% | `% de fenêtres avec Sharpe > 0` | Régularité dans le temps |
| **Consistency Score** | 20% | `clamp(1 - std_sharpe / (\|mean_sharpe\| + 0.1))` | Faible variance des résultats |
| **Drawdown Score** | 15% | `clamp(1 - mean_max_dd / 0.30)` | Protection du capital |

### Pourquoi ces poids ?

- **Sharpe (35%)** : La performance ajustée au risque est le critère principal (de Prado, Ch. 14)
- **Stabilité (30%)** : Un signal qui marche 90% du temps mais échoue à chaque crise est dangereux
- **Consistance (20%)** : Un Sharpe moyen de 1.0 est meilleur si les fenêtres donnent [0.8, 1.0, 1.2] plutôt que [-1.0, 1.0, 3.0]
- **Drawdown (15%)** : Contrainte de risque — un drawdown > 30% est considéré inacceptable

> **Source** : L'approche multi-critère est inspirée du *Multi-Factor Model* de Grinold & Kahn (2000) — *Active Portfolio Management*, qui pondère les signaux par information ratio, stabilité et turnover.

---

## Slide 7 — Couche D : Le Filtre "Viable → Compétitif"

### Deux niveaux d'élimination progressifs

```
TESTÉES (30)
    │
    ▼ Gate 1 : Viabilité
    │  ≥ 3 fenêtres valides
    │  ≥ 40% de fenêtres à Sharpe positif
    │
VIABLES (~18)
    │
    ▼ Gate 2a : Plancher absolu
    │  Score de fiabilité ≥ 0.25
    │
    ▼ Gate 2b : Percentile compétitif
    │  Top 60% par score de fiabilité
    │
COMPÉTITIFS (~11)
```

### Pourquoi ce filtre à deux étages ?

**Gate 1 — Viabilité** : Élimine les variantes qui ne produisent tout simplement pas de résultats exploitables.
- ≥ 3 fenêtres : minimum statistique pour juger la régularité
- ≥ 40% Sharpe positif : un signal qui perd la majorité du temps n'est pas utilisable

**Gate 2 — Compétitivité** :
- **Plancher absolu (0.25)** : Même dans une famille faible, on refuse les variantes dont le score est médiocre
- **Percentile relatif (top 60%)** : Sélection compétitive au sein des survivants

> **Raisonnement** : Ce double filtre évite deux pièges :
> 1. Garder des variantes médiocres juste parce qu'il n'y a pas mieux (le plancher l'empêche)
> 2. Rejeter toutes les variantes sauf la meilleure (le percentile garde de la diversité)

---

## Slide 8 — Couche E : Réduction de Redondance

### Problème : Les variantes similaires votent deux fois

Si SMA-48, SMA-50 et SMA-52 sont toutes compétitives, elles sont presque identiques. Les garder toutes biaiserait l'ensemble vers les SMA moyennes.

### Solution : Clustering glouton par corrélation

```
Algorithme :
1. Trier les compétitifs par score décroissant
2. Pour chaque variante (du meilleur au pire) :
   a. Calculer |corrélation de Pearson| avec chaque représentant déjà sélectionné
   b. Si TOUTES les corrélations < 0.85 → ajouter comme représentant
   c. Sinon → éliminer (tracer la raison : "corrélé à X avec r=0.93")
3. Maximum 10 représentants
```

**Exemple concret :**

```
SMA-50  (score 0.78) → SÉLECTIONNÉ (premier)
SMA-48  (score 0.75) → ÉLIMINÉ (corr=0.97 avec SMA-50)
SMA-100 (score 0.71) → SÉLECTIONNÉ (corr=0.45 avec SMA-50)
SMA-52  (score 0.69) → ÉLIMINÉ (corr=0.95 avec SMA-50)
SMA-20  (score 0.65) → SÉLECTIONNÉ (corr=0.38 avec SMA-50, 0.22 avec SMA-100)
```

### Pourquoi le seuil de 0.85 ?

- **< 0.70** : Trop agressif — on perd des signaux informatifs
- **> 0.90** : Trop permissif — on garde des quasi-duplicats
- **0.85** : Standard de la littérature pour le filtrage de features corrélées

> **Référence** : de Prado (2018), Ch. 8 — *Feature Importance* : "Highly correlated features should be clustered to avoid double-counting their contribution."

---

## Slide 9 — Couche F : Signal Courant

### Chaque représentant produit un vote

Pour chaque variante représentative, le système calcule le **signal actuel** sur la dernière barre de données :

| Famille | Logique | Signal |
|---------|---------|--------|
| **SMA** | Close > SMA → BUY, Close < SMA → SELL | +1, -1, 0 |
| **RSI** | RSI < seuil_bas → BUY, RSI > seuil_haut → SELL | +1, -1, 0 |
| **MACD** | Ligne MACD > Signal → BUY, sinon → SELL | +1, -1, 0 |
| **OBV** | OBV > EMA(OBV) → BUY, sinon → SELL | +1, -1, 0 |

**Chaque vote inclut :**
- Le signal (+1, -1, 0)
- Le poids = score de fiabilité de la Couche C
- L'explication : *"Close 150.25 > SMA-50 148.30 → BUY"*
- La valeur de l'indicateur (pour vérification)

---

## Slide 10 — Couche G : Ensemble Pondéré

### Le vote final : chaque représentant contribue selon sa fiabilité

```
                    Signal    Poids      Contribution
SMA-50              +1.0   ×  0.78   =    +0.78
SMA-100             +1.0   ×  0.71   =    +0.71
SMA-20              -1.0   ×  0.65   =    -0.65
                           ─────────
            Total poids :     2.14
            Score brut :     +0.84 / 2.14 = +0.393
            Score final :    +39.3%  (sur échelle [-100, +100])
```

### Échelle de décision

```
   -100         -50          -15          +15          +50         +100
    │            │            │            │            │            │
    ▼            ▼            ▼            ▼            ▼            ▼
 VENTE       VENTE        NEUTRE       ACHAT       ACHAT
 FORTE                                              FORT
```

| Seuil | Label | Signification |
|-------|-------|--------------|
| > +50 | **ACHAT FORT** | Consensus large : majorité des représentants achètent avec forte confiance |
| > +15 | **ACHAT** | Tendance haussière modérée |
| ≥ -15 | **NEUTRE** | Pas de consensus — les représentants se contredisent ou sont flat |
| ≥ -50 | **VENTE** | Tendance baissière modérée |
| < -50 | **VENTE FORTE** | Consensus large : majorité des représentants vendent |

### Pourquoi la pondération par fiabilité ?

- **Égalité des voix** (1 variante = 1 vote) donnerait trop de poids aux variantes médiocres qui ont passé le filtre de justesse
- **Pondération par fiabilité** : les variantes les plus robustes historiquement ont plus d'influence
- C'est le même principe que le *boosting* en machine learning : pondérer les weak learners par leur accuracy

> **Référence** : Breiman, L. (1996) *Bagging Predictors* — la combinaison pondérée de prédicteurs faibles réduit la variance et améliore la généralisation.

---

## Slide 11 — L'Entonnoir Complet (Exemple Réel)

### Famille SMA, Horizon Moyen Terme, Symbole ATW

```
  ┌───────────────────────────────┐
  │   TESTÉES : 30 variantes     │  SMA-10, SMA-15, ..., SMA-250
  │   (Couche A)                  │
  └──────────────┬────────────────┘
                 │  -12 éliminées (Sharpe négatif > 60% du temps)
                 ▼
  ┌───────────────────────────────┐
  │   VIABLES : 18 variantes     │  Passent la gate de viabilité
  │   (Couche C+D gate 1)        │
  └──────────────┬────────────────┘
                 │  -7 éliminées (score < 0.25 ou hors top 60%)
                 ▼
  ┌───────────────────────────────┐
  │   COMPÉTITIFS : 11 variantes │  Score ≥ 0.25, top 60%
  │   (Couche D gate 2)          │
  └──────────────┬────────────────┘
                 │  -6 éliminées (corrélation > 0.85 avec un meilleur)
                 ▼
  ┌───────────────────────────────┐
  │  REPRÉSENTATIFS : 5 variantes│  Diversifiés, non redondants
  │   (Couche E)                  │
  └──────────────┬────────────────┘
                 │  Pondération par fiabilité
                 ▼
  ┌───────────────────────────────┐
  │   SCORE FINAL : +42.7%       │  → ACHAT
  │   (Couche G)                  │  (3 BUY × fort poids + 2 HOLD)
  └───────────────────────────────┘
```

---

## Slide 12 — Honnêteté Méthodologique

### Ce que le système NE fait PAS

1. **Pas de cherry-picking** : On ne choisit jamais "le meilleur" indicateur
2. **Pas de look-ahead** : Le signal est calculé une fois, évalué uniquement dans le futur relatif
3. **Pas de fake signals** : Les familles non implémentées affichent "N/A", pas un score synthétique
4. **Pas de courbe ajustée** : Les seuils (0.85, 0.25, 40%) sont fixés a priori, pas optimisés sur les données

### Méthodologie déclarée

Chaque résultat est accompagné d'un `methodology_status` :
- `"robust_oos_ensemble"` : Pipeline complet avec ≥ 1 représentant
- `"provisional"` : Pas assez de données ou pas de survivants — résultat NEUTRE forcé

---

## Slide 13 — Interface Utilisateur

### Navigation en 3 niveaux

```
Niveau 0 : Vue d'ensemble
┌─────────────────────────────────────┐
│  [Speedomètre agrégé]              │
│  Score global : +31.2%  → ACHAT    │
└─────────────────────────────────────┘
        │ clic
        ▼
Niveau 1 : Familles
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ SMA      │ │ RSI      │ │ MACD     │ │ OBV      │
│ +42.7%   │ │  N/A     │ │  N/A     │ │  N/A     │
│ ACHAT    │ │          │ │          │ │          │
└──────────┘ └──────────┘ └──────────┘ └──────────┘
        │ clic sur SMA
        ▼
Niveau 2 : Drilldown famille
┌─────────────────────────────────────┐
│  Pipeline: 30 → 18 → 11 → 5       │
│                                     │
│  Représentants :                    │
│  ┌─────────┐ ┌─────────┐ ┌───────┐│
│  │ SMA-50  │ │ SMA-100 │ │SMA-20 ││
│  │ BUY     │ │ BUY     │ │ SELL  ││
│  │ w=0.36  │ │ w=0.33  │ │w=0.30 ││
│  └─────────┘ └─────────┘ └───────┘│
└─────────────────────────────────────┘
        │ clic sur variante
        ▼
Page détail variante (/signals/variant/{id})
┌─────────────────────────────────────┐
│  Métriques de robustesse            │
│  Fenêtres OOS individuelles         │
│  Matrice de corrélation (heatmap)   │
│  Raisons d'élimination par variante │
│  Graphiques : prix + indicateur     │
│  Equity curve, drawdown, trades     │
└─────────────────────────────────────┘
```

---

## Slide 14 — Composants Frontend

| Composant | Rôle | Données affichées |
|-----------|------|-------------------|
| **Speedometer** | Jauge Investing.com-style | Score [-100, +100] avec aiguille animée |
| **SignalScoreBar** | Barre de progression colorée | Score + label (ACHAT/VENTE/NEUTRE) |
| **PipelineStepper** | Entonnoir visuel | Testées → Viables → Compétitifs → Représentatifs |
| **SmaFamilyDrilldown** | Détail de famille | Grille de représentants + explication du score |
| **VariantDetailSheet** | Panneau coulissant | Poids, signal, indicateur, explication texte |
| **MethodologyModal** | Modale pédagogique | 6 sections expliquant la méthodologie OOS |

---

## Slide 15 — Extensibilité : Ajouter une Famille

### Processus en 3 étapes

```python
# 1. Enregistrer la famille (candidates.py)
@register_family("bollinger", n_variants=30)
def _bollinger_variants(horizon):
    return [VariantDef(..., archetype="bb_squeeze", params={"period": p, "std": s})
            for p, s in product(periods, stds)]

# 2. Enregistrer le signal (oos_eval.py)
@register_signal("bollinger", "bb_squeeze")
def _bollinger_signal(close, volume, params):
    upper, lower = bollinger_bands(close, params["period"], params["std"])
    signal = np.where(close < lower, +1.0, np.where(close > upper, -1.0, 0.0))
    return signal

# 3. C'est tout — le pipeline (Couches B→G) s'applique automatiquement
```

**Aucune modification** des couches de filtrage, de l'API, ou du frontend n'est nécessaire.

---

## Slide 16 — Fondements Théoriques

| Concept | Source | Application dans le pipeline |
|---------|--------|------------------------------|
| **Walk-Forward Analysis** | Pardo (2008), Ch. 7-9 | Couche B : fenêtres roulantes train/test |
| **Deflated Sharpe Ratio** | Bailey & de Prado (2014) | Justification du filtrage multi-étapes vs. sélection du "meilleur" |
| **Feature Clustering** | de Prado (2018), Ch. 8 | Couche E : réduction de redondance par corrélation |
| **Ensemble Methods** | Breiman (1996), Schapire (1990) | Couche G : combinaison pondérée de weak learners |
| **Multi-Factor Scoring** | Grinold & Kahn (2000) | Couche C : pondération multi-critères (Sharpe, stabilité, consistance, DD) |
| **OOS Evaluation** | White (2000), *Reality Check* | Pipeline entier : jamais d'évaluation sur données d'entraînement |
| **Transaction Costs** | de Prado (2018), Ch. 14 | Couche B : coûts inclus dans chaque évaluation de fenêtre |
| **Survivorship Bias** | Brown et al. (1995) | Couche D : filtre systématique, pas de sélection subjective |

---

## Slide 17 — Résumé

### Le pipeline en une phrase par couche

| Couche | Action | Justification |
|--------|--------|---------------|
| **A** | Générer 30 variantes/famille | Couvrir l'espace des paramètres |
| **B** | Walk-forward OOS | Aucun look-ahead |
| **C** | Score de fiabilité [0,1] | Agréger 4 dimensions de performance |
| **D** | Viable → Compétitif | Éliminer le bruit statistique |
| **E** | Corrélation < 0.85 | Pas de double comptage |
| **F** | Signal courant | BUY/SELL/HOLD par représentant |
| **G** | Ensemble pondéré | Score final robuste et diversifié |

### Garanties

- **Reproductible** : variant_id déterministe, paramètres figés
- **Transparent** : chaque variante inspectable, chaque élimination tracée
- **Conservateur** : en cas de doute, NEUTRE (pas de signal forcé)
- **Extensible** : `@register_family` + `@register_signal` = nouvelle famille sans toucher au core

---

## Slide 18 — Références Complètes

1. **de Prado, M.L. (2018)** *Advances in Financial Machine Learning*. Wiley.
   - Ch. 1 : Pipeline modulaire de recherche
   - Ch. 6-8 : Feature importance, ensemble methods
   - Ch. 11-12 : Backtesting pitfalls, overfitting
   - Ch. 14 : Transaction costs

2. **Pardo, R. (2008)** *The Evaluation and Optimization of Trading Strategies*. Wiley.
   - Ch. 7-9 : Walk-Forward Analysis

3. **Bailey, D.H. & de Prado, M.L. (2014)** *The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality*. Journal of Portfolio Management.

4. **Breiman, L. (1996)** *Bagging Predictors*. Machine Learning, 24(2).

5. **Grinold, R.C. & Kahn, R.N. (2000)** *Active Portfolio Management*. McGraw-Hill.

6. **White, H. (2000)** *A Reality Check for Data Snooping*. Econometrica, 68(5).

7. **Brown, S.J., Goetzmann, W., Ibbotson, R.G., Ross, S.A. (1995)** *Survivorship Bias in Performance Studies*. Review of Financial Studies.

---
