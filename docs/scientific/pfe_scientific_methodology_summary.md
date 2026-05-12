# Synthèse scientifique des formules et méthodologies

Ce document résume la couche scientifique de l'application de dashboard et de moteur de signaux. Il sert de note d'accompagnement pour la soutenance PFE : l'objectif est d'expliquer comment les signaux sont produits, comment ils sont validés, comment l'Edge est évalué, et comment les résultats alimentent le dashboard et le blotter.

L'application doit être lue comme un outil d'aide à la décision. Elle ne prédit pas parfaitement le marché et ne route pas d'ordres automatiquement. Elle organise les données, teste les signaux sur des périodes hors échantillon, quantifie l'incertitude, puis expose une preuve exploitable par l'utilisateur.

## 1. Chaîne générale de décision

La chaine scientifique suit le parcours suivant :

```text
Donnees OHLCV
  -> indicateurs techniques / facteurs
  -> scores par barre
  -> validation OOS et WFO
  -> Edge statistique par signal courant
  -> dashboard de tri
  -> ticket / blotter de preparation
```

Les principaux principes sont :

- **causalite temporelle** : un signal a la date `t` utilise uniquement l'information disponible jusqu'a `t` ;
- **evaluation hors echantillon** : la performance presentee est calculee sur des fenetres qui n'ont pas servi a selectionner les parametres ;
- **couts de transaction** : les rendements nets integrent les couts, afin de penaliser les signaux qui tournent trop souvent ;
- **preuve statistique** : un signal n'est marque comme `Prouve` que si plusieurs tests convergent ;
- **decision humaine** : le dashboard propose une priorisation et une justification, mais la validation finale reste humaine.

## 2. Rendements et coûts

### 2.1 Rendement forward

Pour evaluer un signal observe a la date `T`, l'application calcule des rendements futurs selon plusieurs conventions :

| Methode | Entree | Sortie | Formule |
|---|---:|---:|---|
| `close_to_close` | `Close(T)` | `Close(T+h)` | `Close(T+h) / Close(T) - 1` |
| `open_to_open` | `Open(T+1)` | `Open(T+h+1)` | `Open(T+h+1) / Open(T+1) - 1` |
| `close_to_open` | `Close(T)` | `Open(T+h)` | `Open(T+h) / Close(T) - 1` |
| `open_to_close` | `Open(T+1)` | `Close(T+h)` | `Close(T+h) / Open(T+1) - 1` |

Pour le dashboard Edge, la logique operationnelle privilegie l'entree a l'ouverture suivante :

```text
Signal observe apres la cloture T
Entree de reference = Open(T+1)
Sortie de reference = Open ou Close selon le candidat de sortie choisi
```

### 2.2 Rendement action vs rendement action brute

Le dashboard distingue deux notions :

- **Stock E[R]** : rendement brut du titre sur l'horizon choisi ;
- **Action E[R]** : rendement du point de vue de l'action proposee par le signal.

Pour un signal acheteur :

```text
R_action = R_stock
```

Pour un signal vendeur ou bearish :

```text
R_action = - R_stock
```

Donc un signal `Vente` avec `Action E[R] > 0` signifie que le titre a historiquement baisse apres des signaux comparables. Cela ne veut pas dire que le rendement brut du titre etait positif.

### 2.3 Couts de transaction

Le rendement net soustrait un cout aller-retour :

```text
c = cost_bps_per_side / 10 000
R_net = R_gross - 2c
```

Dans la couche Edge dashboard, le cout par defaut est :

```text
cost_bps_per_side = 33 bps
```

Ce choix represente une hypothese prudente pour le marche actions marocain : courtage, spread et slippage.

### 2.4 Selection de l'horizon de detention

Le dashboard ne fixe pas un seul horizon exact. Il cherche le meilleur horizon net dans une bande :

| Horizon dashboard | Candidats |
|---|---:|
| weekly | `1..5` jours |
| monthly | `6..21` jours |
| quarterly | `22..63` jours |

La selection utilise :

```text
1. maximiser Action E[R] net
2. en cas d'egalite : maximiser le hit rate
3. en cas d'egalite : preferer la detention la plus courte
```

Cette selection est une aide de tri historique, pas une garantie que le meme nombre de jours restera optimal dans le futur.

## 3. Signal Engine : évaluation OOS et ensemble

### 3.1 Signal discret

Chaque variante d'indicateur produit un signal discret :

```text
s_t ∈ {-1, 0, +1}
```

Interpretation generale :

- `+1` : biais acheteur / haussier ;
- `0` : neutre ou pas de position ;
- `-1` : biais vendeur / baissier.

Le contrat d'implementation impose :

- une valeur par barre ;
- pas de valeurs fractionnaires dans les variantes de base ;
- les periodes de warmup sont mises a `0` ;
- les `NaN` sont remplaces par `0`.

### 3.2 Fenetres Out-of-Sample

La validation OOS se fait par fenetres walk-forward. Les parametres par horizon sont :

| Horizon signal | Train | Test OOS | Step | Historique max |
|---|---:|---:|---:|---:|
| short | 252 barres | 63 barres | 63 | 5 ans |
| medium | 504 barres | 126 barres | 126 | 10 ans |
| long | 756 barres | 252 barres | 252 | 20 ans |

La logique est :

```text
Pour chaque fenetre :
  train = donnees de contexte / warmup
  test = donnees OOS posterieures
  score = performance uniquement sur test
```

Le `step = test` evite le chevauchement des fenetres OOS.

### 3.3 Rendement strategie par barre

Pour une position `p_t` et un rendement prix `r_t` :

```text
cost_t = cost_factor * |p_t - p_{t-1}|
R_strategy,t = p_t * r_t - cost_t
```

Avec :

```text
cost_factor = cost_bps / 10 000
```

Cette formule penalise les retournements frequents. Un signal qui change souvent doit generer plus de rendement brut pour compenser les frais.

### 3.4 Metriques par fenetre

Les principales metriques calculees sont :

```text
mean_return_net = mean(R_strategy)
Sharpe = sqrt(252) * mean(R_strategy) / std(R_strategy)
total_return = product(1 + R_strategy) - 1
CAGR = (1 + total_return)^(252 / n_bars) - 1
```

Le drawdown maximal est :

```text
equity_t = product_{i<=t}(1 + R_i)
peak_t = max_{i<=t}(equity_i)
drawdown_t = 1 - equity_t / peak_t
max_drawdown = max(drawdown_t)
```

### 3.5 Score de robustesse

Une variante doit d'abord passer une porte de viabilite :

```text
n_valid_windows >= 3
fraction_positive_windows >= 0.40
```

Ensuite, quatre composantes sont normalisees entre `0` et `1`.

```text
SharpeScore = clamp((mean_sharpe + 0.5) / 2.0, 0, 1)
StabilityScore = fraction_positive_windows
ConsistencyScore = clamp(1 - std_sharpe / (|mean_sharpe| + 0.1), 0, 1)
DrawdownScore = clamp(1 - mean_max_drawdown / 0.30, 0, 1)
```

Le score final est :

```text
Reliability =
  0.35 * SharpeScore
+ 0.30 * StabilityScore
+ 0.20 * ConsistencyScore
+ 0.15 * DrawdownScore
```

Interpretation :

- le Sharpe mesure la qualite rendement/risque ;
- la stabilite mesure la proportion de fenetres positives ;
- la consistance penalise les performances tres variables ;
- le drawdown evite de retenir des signaux trop dangereux.

### 3.6 Survivants et reduction de redondance

Le moteur garde les variantes qui respectent :

```text
is_viable = True
Reliability >= 0.25
```

Puis il conserve le top `60%` des variantes restantes.

Pour eviter de compter plusieurs fois le meme signal, il calcule la correlation de Pearson entre variantes :

```text
rho_ij = corr(signal_i, signal_j)
```

La selection est gloutonne :

```text
1. trier par Reliability decroissant
2. accepter la meilleure variante
3. accepter une nouvelle variante seulement si max |rho| <= 0.85
4. s'arreter a 10 representants maximum
```

Le seuil `0.85` signifie que deux signaux partagent environ :

```text
rho^2 = 0.85^2 = 72.25%
```

de leur variance. Ils sont donc largement redondants.

### 3.7 Ensemble pondere par fiabilite

Le score courant d'une famille est :

```text
score_raw = sum(w_i * s_i) / sum(w_i)
score_pct = 100 * score_raw
```

Avec :

```text
w_i = Reliability_i
s_i ∈ {-1, 0, +1}
```

Le resultat est borne entre `-100` et `+100`. Il est ensuite transforme en label :

| Score agrege | Label global |
|---:|---|
| `> 50` | Achat fort |
| `15..50` | Achat |
| `-15..15` | Neutre |
| `-50..-15` | Vente |
| `< -50` | Vente forte |

## 4. Edge Evaluation : preuve statistique du signal courant

La couche Edge repond a la question :

> Lorsque le signal courant tombe dans ce bucket aujourd'hui, que s'est-il passe historiquement sur les observations OOS comparables ?

### 4.1 Buckets de score

Les scores continus sont classes en cinq buckets :

| Bucket | Condition |
|---|---:|
| `strong_sell` | score `< -50` |
| `sell` | `-50 <= score < -15` |
| `hold` | `-15 <= score <= 15` |
| `buy` | `15 < score <= 50` |
| `strong_buy` | score `> 50` |

La direction associee est :

```text
buy / strong_buy       -> long
sell / strong_sell     -> short / bearish research
hold                   -> none
```

### 4.2 Echantillon Edge

L'Edge aligne :

```text
(date, score_t, forward_return_{t,h})
```

Puis il filtre :

```text
1. dates OOS uniquement
2. bucket identique au bucket courant
3. lookback maximum = 3 ans
4. observations recentes jusqu'a N_TARGET = 60
5. plafond absolu EDGE_MAX_OBSERVATIONS = 100
```

Le minimum pour prouver un Edge est :

```text
N_MIN = 30 observations
```

### 4.3 Esperance et decomposition

Pour les rendements action `R_i` :

```text
Action E[R] = mean(R_i)
```

La decomposition d'esperance est :

```text
p_win = nombre(R_i > 0) / n
p_loss = 1 - p_win
avg_win = mean(R_i | R_i > 0)
avg_loss = mean(R_i | R_i <= 0)
Expectancy = p_win * avg_win + p_loss * avg_loss
```

Dans l'implementation, les rendements nuls sont traites comme des pertes pour rester conservateur.

### 4.4 Hit rate et intervalle de Wilson

Le hit rate est :

```text
hit_rate = nombre(R_gross > 0) / n
```

L'intervalle de confiance de Wilson pour une proportion est :

```text
p_hat = k / n
z = quantile_normal(1 - alpha/2)

denom = 1 + z^2 / n
center = (p_hat + z^2 / (2n)) / denom
half_width = z * sqrt(p_hat(1-p_hat)/n + z^2/(4n^2)) / denom

CI = [center - half_width, center + half_width]
```

Le gate Edge demande :

```text
Wilson lower bound > 0.50
```

Ce critere est plus strict que `hit_rate > 50%`, car il tient compte de la taille d'echantillon.

### 4.5 Edge ratio et profit factor

L'Edge ratio mesure le rendement moyen par unite de dispersion :

```text
EdgeRatio = mean(R) / std(R)
```

Le profit factor est :

```text
ProfitFactor = sum(R_i > 0) / abs(sum(R_i < 0))
```

Si aucune perte n'existe, le profit factor n'est pas defini et reste `None`.

### 4.6 Bootstrap de moyenne

Pour l'intervalle de confiance sur `Action E[R]`, l'application resample les rendements avec remplacement :

```text
Pour b = 1..B :
  sample_b = tirage avec remplacement de n rendements
  mean_b = mean(sample_b)

CI_95% = [quantile(mean_b, 2.5%), quantile(mean_b, 97.5%)]
```

Dans Edge, le nombre d'iterations par defaut est `2000`.

### 4.7 Monte Carlo Luck Test

Le test Monte Carlo repond a la question :

> La performance observee peut-elle etre expliquee par une sequence aleatoire de rendements centres ?

Hypothese nulle :

```text
H0 : les rendements n'ont pas d'esperance exploitable
```

Procedure :

```text
1. observer la metrique M_obs sur R
2. centrer les rendements : R_centered = R - mean(R)
3. resampler R_centered par bootstrap simple ou block bootstrap
4. calculer M_b pour chaque simulation
5. p_value = proportion(M_b >= M_obs) si M_obs >= 0
```

Pour Edge, la metrique utilisee est principalement :

```text
total_return = product(1 + R_i) - 1
```

Quand l'horizon de detention est superieur a un jour, le test peut utiliser un block bootstrap stationnaire pour mieux respecter l'autocorrelation temporelle.

### 4.8 Label Shuffle Test

Le label-shuffle teste si le bucket courant porte vraiment de l'information.

Hypothese nulle :

```text
H0 : l'association entre bucket de score et rendement futur est arbitraire
```

Procedure :

```text
1. garder les forward returns
2. melanger les labels de bucket
3. recalculer la moyenne du bucket courant
4. comparer la moyenne observee a la distribution shuffle
```

Si le bucket `Vente` donne une moyenne positive en rendement action, mais que des buckets melanges donnent souvent une moyenne equivalente, alors le bucket n'est pas informatif.

### 4.9 Correction des tests multiples

L'application applique une correction simple de type Bonferroni :

```text
p_adj = min(1, p_raw * m)
```

Avec :

```text
m = multiple_testing_count
```

Le but est de ne pas declarer un Edge uniquement parce que plusieurs variantes ou horizons ont ete testes.

### 4.10 Gates pour Edge prouve

Un Edge net est marque comme prouve seulement si tous les gates passent :

```text
n >= 30
Wilson lower bound > 0.50
Monte Carlo p_adj < 0.05
Label Shuffle p_adj < 0.05
Freshness gate = OK
Action E[R] net > 0
```

En notation logique :

```text
proven_edge_net =
  gate_n
  AND gate_wilson
  AND gate_mc_net
  AND gate_label_shuffle_net
  AND gate_freshness_net
```

Les constantes principales sont :

| Constante | Valeur |
|---|---:|
| `N_MIN` | 30 |
| `N_TARGET` | 60 |
| `EDGE_MAX_OBSERVATIONS` | 100 |
| `WILSON_LB_THRESHOLD` | 0.50 |
| `MC_PVALUE_THRESHOLD` | 0.05 |
| `LABEL_SHUFFLE_PVALUE_THRESHOLD` | 0.05 |
| `PROOF_MAX_LOOKBACK_YEARS` | weekly 1 an, monthly 2 ans, quarterly 3 ans |
| `FRESHNESS_LOOKBACK_YEARS` | weekly 3 mois, monthly 6 mois, quarterly 1 an |
| `FRESHNESS_MIN_N` | 10 |
| `DEFAULT_COST_BPS_PER_SIDE` | 33 bps |

## 5. Monte Carlo, bootstrap et robustesse de chemin

### 5.1 Bootstrap stationnaire

Le bootstrap stationnaire de Politis-Romano preserve mieux la dependance temporelle qu'un tirage i.i.d.

Principe :

```text
1. choisir un point de depart aleatoire
2. continuer le bloc avec probabilite 1 - p
3. demarrer un nouveau bloc avec probabilite p
4. repeter jusqu'a obtenir T observations
```

L'esperance de longueur de bloc est :

```text
E[block_length] = 1 / p
```

Dans certaines routines, `p = 0.05`, soit environ `20` observations par bloc.

### 5.2 Fan chart Monte Carlo

Pour les backtests de signaux, l'application genere des chemins d'equite simulés :

```text
1. resampler les rendements de strategie
2. construire equity_path_b,t = product_{i<=t}(1 + R_{b,i})
3. calculer les percentiles par date : p05, p25, p50, p75, p95
```

Les statistiques de sortie incluent :

```text
terminal_return = equity_T - 1
CAGR = equity_T^(252/T) - 1
Sharpe = sqrt(252) * mean(R) / std(R)
MaxDrawdown = max(1 - equity_t / peak_t)
VaR95 = quantile(terminal_return, 5%)
CVaR95 = mean(terminal_return | terminal_return <= VaR95)
P(terminal > 0) = proportion des chemins positifs
```

Cette couche repond a une question de robustesse :

> Si les rendements observes etaient rearranges ou resamples dans des sequences plausibles, le chemin reste-t-il acceptable ?

### 5.3 Bootstrap par trades

Pour une distribution de PnL par trade :

```text
1. tirer n trades avec remplacement
2. composer la courbe d'equite
3. estimer l'esperance par trade, la CI 95%, VaR, CVaR et probabilite terminale positive
```

Cette methode est utile quand le nombre de trades est suffisant. En dessous d'un echantillon raisonnable, le resultat doit etre interprete comme fragile.

## 6. Walk-Forward Optimization

La WFO repond a la question :

> Les parametres choisis sur une periode in-sample se transferent-ils sur une periode future out-of-sample ?

### 6.1 Structure IS/OOS

Pour chaque fold :

```text
1. choisir une fenetre IS
2. evaluer plusieurs variantes sur IS
3. selectionner la meilleure variante selon l'objectif
4. appliquer cette variante sur OOS
5. stocker rendement, Sharpe, drawdown et trades OOS
```

La discipline essentielle est :

```text
IS < OOS dans le temps
OOS jamais utilise pour choisir le gagnant du fold
```

### 6.2 PROM : objectif pessimiste d'optimisation

La fonction objectif utilisee pour classer les parametres de strategie est PROM, Pessimistic Return on Margin :

```text
PROM =
  [AW * (#WT - sqrt(#WT)) - AL * (#LT + sqrt(#LT))]
  / Capital
```

Avec :

- `#WT` : nombre de trades gagnants ;
- `AW` : gain moyen des trades gagnants ;
- `#LT` : nombre de trades perdants ;
- `AL` : perte moyenne absolue des trades perdants ;
- `Capital` : capital alloue.

Interpretation :

- les gains sont reduits par `sqrt(#WT)` ;
- les pertes sont augmentees par `sqrt(#LT)` ;
- les petits echantillons sont fortement penalises ;
- un seul trade gagnant donne une information quasi nulle.

PROM evite que l'optimiseur selectionne un parametrage chanceux base sur peu de trades.

### 6.3 Walk-Forward Efficiency

La WFE mesure le transfert entre IS et OOS :

```text
WFE = annualized_OOS_return / annualized_IS_return
```

Avec annualisation composee :

```text
annualized_return = product(1 + R_i)^(252 / n_bars) - 1
```

Interpretation :

| WFE | Lecture |
|---:|---|
| `>= 80%` | transfert excellent |
| `50%..80%` | transfert acceptable |
| `30%..50%` | transfert marginal |
| `< 30%` | risque fort d'overfitting |

Le seuil academique retenu est :

```text
WFE >= 50%
```

### 6.4 Robustness ratio et dominance d'un fold

Le ratio de robustesse est :

```text
RobustnessRatio = nombre(folds OOS rentables) / nombre(folds OOS)
```

La dominance d'une seule fenetre est :

```text
SingleWindowDominance =
  max(|OOS_return_i|)
  / sum(|OOS_return_i|)
```

Si une seule fenetre explique plus de la moitie du resultat, la performance est consideree fragile.

### 6.5 Score composite WFO

Dans la couche WFO signal, le score composite est :

```text
Composite =
  0.40 * WFE_norm
+ 0.30 * Robustness_norm
+ 0.20 * Sharpe_norm
+ 0.10 * Drawdown_norm
```

Avec :

```text
WFE_norm = clamp(WFE, 0, 1)
Robustness_norm = clamp(RobustnessRatio, 0, 1)
Sharpe_norm = clamp(mean_oos_sharpe / 2, 0, 1)
Drawdown_norm = clamp(1 - |worst_fold_drawdown|, 0, 1)
```

Le score est ensuite multiplie par `100`.

### 6.6 Grades WFO

Le grade de robustesse combine WFE et robustesse :

| Grade | Condition |
|---|---|
| A | `WFE >= 0.65` et `Robustness >= 0.75` |
| B | `WFE >= 0.55` et `Robustness >= 0.60` |
| C | `WFE >= 0.50` et `Robustness >= 0.50` |
| D | `WFE >= 0.40` ou `Robustness >= 0.40` |
| F | sinon |

### 6.7 Consensus WFO global

Les categories WFO reussies sont combinees avec des poids proportionnels a leur score composite :

```text
w_c = Composite_c / sum(Composite_c)
RawScore = sum(w_c * Score_c)
```

Le score peut ensuite etre module par support/resistance :

```text
GlobalScore = RawScore * SR_modifier
```

Le modificateur est borne :

```text
SR_modifier ∈ [0.5, 1.5]
```

Exemples :

- proche support + signal haussier : boost ;
- proche support + signal baissier : dampen ;
- proche resistance + signal baissier : boost ;
- proche resistance + signal haussier : dampen.

## 7. Deflated Sharpe Ratio et tests multiples

### 7.1 Sharpe observe

Le Sharpe observe est :

```text
SR_hat = mean(R - R_f) / std(R)
```

Selon le contexte, il peut etre annualise par `sqrt(252)`.

### 7.2 Probabilistic Sharpe Ratio

Le PSR estime la probabilite que le vrai Sharpe depasse un benchmark `SR*` :

```text
PSR = Phi(
  sqrt(T - 1) * (SR_hat - SR*) /
  sqrt(1 - skew * SR_hat + ((kurtosis - 1) / 4) * SR_hat^2)
)
```

Il corrige l'interpretation du Sharpe pour l'asymetrie, la kurtosis et la taille d'echantillon.

### 7.3 Deflated Sharpe Ratio

Le DSR utilise comme benchmark le Sharpe maximum attendu sous tests multiples :

```text
SR* = E[SR_max(N)]
DSR = PSR(SR_hat, SR*)
```

Dans une implementation equivalente, le benchmark est approxime par :

```text
benchmark = sqrt(2 * log(N_variants)) * SR_std
DSR_stat = (observed_sharpe - benchmark) / SR_std
p_value = 1 - Phi(DSR_stat)
```

Le but est d'eviter de prendre un Sharpe eleve pour une preuve, alors qu'il peut etre le maximum chanceux parmi de nombreux essais.

## 8. Analytics : IC, hit rate et FDR

### 8.1 Information Coefficient

L'Information Coefficient mesure l'association entre score et rendement futur. L'application utilise une correlation de Spearman :

```text
IC = corr_rank(signal_t, forward_return_{t,h})
```

Spearman est robuste aux transformations monotones et se concentre sur le rang plutot que sur les niveaux exacts.

### 8.2 Newey-West

Quand les rendements forward se chevauchent, les observations sont autocorrelees. L'erreur standard de Newey-West corrige cette dependance :

```text
Var_NW(mean) =
  gamma_0 / T
  + (2 / T) * sum_{k=1..L} (1 - k/(L+1)) * gamma_k
```

Le t-stat conditionnel devient :

```text
t = (mean_conditional - mean_unconditional) / sqrt(Var_NW)
```

### 8.3 Benjamini-Hochberg FDR

Pour controler les faux positifs parmi plusieurs signaux, la procedure BH trie les p-values :

```text
p_(1) <= p_(2) <= ... <= p_(m)
```

Puis elle cherche le plus grand `k` tel que :

```text
p_(k) <= (k / m) * q
```

Toutes les hypotheses `1..k` sont retenues comme significatives. Le niveau utilise dans les docs facteur est :

```text
q = 0.10
```

## 9. Portfolio, sizing et blotter

### 9.1 Kelly Criterion

Le sizing Kelly utilise :

```text
f* = W - (1 - W) / R
```

Avec :

- `W` : probabilite de gain ou hit rate ;
- `R` : ratio gain moyen / perte moyenne.

Forme equivalente :

```text
q = 1 - W
f* = (W * R - q) / R
```

Si `f* <= 0`, le systeme considere qu'il n'y a pas d'avantage exploitable.

Dans le dashboard, un cap Kelly peut etre derive de l'expectancy nette :

```text
R = avg_win / |avg_loss|
kelly_full = max(0, (p_win * R - (1 - p_win)) / R)
kelly_cap = kelly_full * kelly_fraction_user
```

### 9.2 Position sizing par risque

Pour une entree `entry_price` et un stop `stop_price` :

```text
risk_per_share = |entry_price - stop_price|
capital_at_risk = account_equity * modified_kelly
shares = floor(capital_at_risk / risk_per_share)
position_value = shares * entry_price
trade_risk = shares * risk_per_share
```

### 9.3 HRP : Hierarchical Risk Parity

La base d'allocation utilise HRP. Les etapes sont :

```text
1. calculer les rendements historiques
2. calculer correlation et covariance
3. transformer correlation en distance
4. clustering hierarchique
5. quasi-diagonalisation
6. allocation recursive par variance de cluster
```

La distance correlationnelle est :

```text
d_ij = sqrt((1 - corr_ij) / 2)
```

La variance d'un cluster est calculee via des poids inverse-variance :

```text
ivp_i = (1 / sigma_i^2) / sum_j(1 / sigma_j^2)
cluster_variance = w' * Cov_cluster * w
```

L'allocation entre deux sous-clusters gauche et droite est :

```text
alpha_left = 1 - var_left / (var_left + var_right)
alpha_right = 1 - alpha_left
```

### 9.4 Contraintes du ticket dashboard

Le ticket combine :

- capital total ;
- cash buffer ;
- poids HRP ;
- cap Kelly ;
- cap par position ;
- cap par secteur ;
- cap de liquidite via participation ADV ;
- statut Edge ;
- zone d'entree.

La taille finale est :

```text
target_size_mad =
  min(
    deployable_capital * final_weight,
    ADV20 * adv_participation_pct
  )

shares = floor(target_size_mad / entry_price)
```

Le rendement attendu en MAD est :

```text
ExpectedReturnMAD = size_mad * ActionE[R]_net
```

## 10. Niveaux techniques : ATR, pivots, support/résistance

### 10.1 True Range et ATR

Le True Range de Wilder est :

```text
TR_t = max(
  High_t - Low_t,
  |High_t - Close_{t-1}|,
  |Low_t - Close_{t-1}|
)
```

L'ATR est la moyenne glissante :

```text
ATR_n = mean(TR_{t-n+1..t})
ATR_ratio = ATR_n / Close_t
```

Dans l'application, `ATR(14)` sert a mesurer la volatilite et a construire des zones d'entree, stops et modulations support/resistance.

### 10.2 Pivots classiques

Les pivots journaliers sont :

```text
PP = (High_prev + Low_prev + Close_prev) / 3
S1 = 2 * PP - High_prev
R1 = 2 * PP - Low_prev
S2 = PP - (High_prev - Low_prev)
R2 = PP + (High_prev - Low_prev)
```

### 10.3 Swing highs / swing lows

Un swing high est un point dont le `High_i` domine ses voisins :

```text
High_i > High_j pour j dans [i-left, i+right], j != i
```

Un swing low est l'inverse :

```text
Low_i < Low_j pour j dans [i-left, i+right], j != i
```

Les niveaux sont classes par proximite au prix courant, recence et nombre de touches.

### 10.4 Fibonacci retracement

Sur un swing dominant `[low, high]`, les niveaux de retracement sont :

```text
Level(r) = High - r * (High - Low)
```

Avec :

```text
r ∈ {0.236, 0.382, 0.500, 0.618, 0.786}
```

Le support est le niveau le plus proche sous le prix courant. La resistance est le niveau le plus proche au-dessus.

## 11. Limites scientifiques

Les mecanismes ci-dessus reduisent plusieurs biais classiques :

- sur-apprentissage historique ;
- selection du meilleur signal par chance ;
- ignorance des couts ;
- confiance excessive dans un petit echantillon ;
- redondance d'indicateurs ;
- fragilite d'un seul chemin de backtest.

Mais ils ne suppriment pas l'incertitude :

- un Edge historique peut se degrader ;
- les regimes de marche peuvent changer ;
- les couts reels peuvent depasser l'hypothese ;
- le dashboard travaille en donnees daily, pas en intraday ;
- le short selling peut etre non executable selon les contraintes de marche ou de mandat.

La bonne interpretation est donc :

```text
Le systeme ne prouve pas qu'un trade futur sera gagnant.
Il prouve que le signal courant dispose, ou non, d'une evidence historique OOS suffisamment robuste pour meriter une analyse prioritaire.
```

## 12. Carte des fichiers sources

| Sujet | Source principale |
|---|---|
| Methode Edge | `docs/EDGE_METHOD.md` |
| Implementation Edge | `core/quant_core/research/edge.py` |
| Score history et buckets | `core/quant_core/research/score_history.py` |
| Wilson CI | `core/quant_core/research/stats/hit_rate.py` |
| IC, Newey-West | `core/quant_core/research/stats/ic.py` |
| Bootstrap, PSR, DSR | `core/quant_core/research/stats/robustness.py` |
| Signal Engine OOS | `docs/signal-generation/03-oos-evaluation.md` |
| Robustesse Signal Engine | `docs/signal-generation/04-robustness-scoring.md` |
| Survivor filtering | `docs/signal-generation/05-survivor-filtering.md` |
| Redondance | `docs/signal-generation/06-redundancy-reduction.md` |
| Ensemble courant | `docs/signal-generation/07-current-signal-and-ensemble.md` |
| WFO signal | `core/quant_core/signal_engine/wfo_signal.py` |
| Consensus WFO global | `core/quant_core/signal_engine/wfo_global.py` |
| PROM | `core/quant_core/wfo/prom.py` |
| WFE | `core/quant_core/wfo/wfe.py` |
| DSR et block bootstrap WFO | `core/quant_core/wfo/statistical.py` |
| Monte Carlo backtest signal | `core/quant_core/signal_engine/backtest_mc.py` |
| Kelly WFO | `core/quant_core/wfo/sizing.py` |
| Allocation HRP | `core/quant_core/strategy_plan/allocation.py` |
| Sizing Kelly | `core/quant_core/strategy_plan/sizing.py` |
| ATR et niveaux | `core/quant_core/strategy_plan/levels.py` |
| Blotter dashboard | `docs/DAILY_BLOTTER_METHOD.md` |

## 13. Références académiques et professionnelles

- Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. Wiley.
- Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
- Bailey, D. H. & Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio." *Journal of Portfolio Management*.
- Harvey, C. R., Liu, Y. & Zhu, H. (2016). "...and the Cross-Section of Expected Returns." *Review of Financial Studies*.
- Wilson, E. B. (1927). "Probable Inference, the Law of Succession, and Statistical Inference." *Journal of the American Statistical Association*.
- Politis, D. N. & Romano, J. P. (1994). "The Stationary Bootstrap." *Journal of the American Statistical Association*.
- Kelly, J. L. (1956). "A New Interpretation of Information Rate." *Bell System Technical Journal*.
- Thorp, E. O. (2006). "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market."
- Grinold, R. C. & Kahn, R. N. (2000). *Active Portfolio Management*. McGraw-Hill.
- Newey, W. K. & West, K. D. (1987). "A Simple Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix." *Econometrica*.
- Wilder, J. W. (1978). *New Concepts in Technical Trading Systems*.
- Murphy, J. J. (1999). *Technical Analysis of the Financial Markets*.
- Elder, A. (1993). *Trading for a Living*.
