# Roadmap Weekend — Interview Trader Compte Propre, Desk International (BMCE Capital Markets)

**Interviewer :** Nabil Ayoub (Deputy Head of Capital Markets, profil actuariat/INSEA, ~20 ans BMCE Capital)
**Desk :** International — obligataire, FX, commodities
**Implication :** il valorisera les dérivations propres, l'honnêteté sur tes limites, et une lecture macro cohérente — pas la récitation.

---

## Hiérarchie des priorités

1. **Obligataire / taux** — cœur du desk, ton plus gros écart venant de l'equity. ~50% du temps.
2. **FX** — spécificités dirham indispensables. ~25%.
3. **Commodities** — mécanique des futures + contexte Maroc. ~10%.
4. **Narrative macro + idées de trades + mock** — ~15%.

---

## VENDREDI SOIR (2–3h) — Mise à jour macro

Objectif : construire ton "dashboard" mental des marchés au 12 juin 2026.

- **BCE (11 juin 2026)** : hausse de 25 pb, dépôt à 2,25% — première hausse depuis 2023. Cause : inflation zone euro 3,2% en mai, choc énergétique lié au conflit Iran / détroit d'Ormuz. Lis le communiqué BCE et la conf de presse Lagarde.
- **Fed** : statu quo à 3,50–3,75%, 4 dissensions en avril (record depuis 1992), biais hawkish. **FOMC les 16–17 juin** — prépare un avis sur ce qu'ils feront.
- **Pétrole** : Brent ~110–119$ (plus haut depuis 2022), prime géopolitique Ormuz. Vérifie les niveaux exacts dimanche soir.
- **BAM** : taux directeur 2,25% (statu quo depuis mars), inflation 2026 prévue ~0,8–1,6%, croissance 5,6%, déficit budgétaire 3,5% du PIB. Lis le communiqué du Conseil du 17 mars (prochain Conseil : juin — vérifie la date exacte).
- **L'angle gagnant** : la *divergence* — Fed/BCE face à une inflation énergétique importée vs BAM confortable grâce à une inflation domestique faible et une bonne campagne agricole. Qu'est-ce que ça implique pour la courbe MAD, le change, le portefeuille du desk ?

Livrable du soir : une page A4 manuscrite avec tous les niveaux clés (taux, Brent, or, EUR/USD, USD/MAD, EUR/MAD).

---

## SAMEDI — Obligataire & Taux (journée complète)

### Matin (4h) — Théorie rigoureuse (Hull ch. 4 + notes de cours)

- Prix d'une obligation : actualisation, prix pied de coupon (clean) vs prix plein coupon (dirty), coupon couru.
- Relation prix/taux : convexité de la courbe, pourquoi.
- **Duration** : Macaulay et modifiée — *sache les dériver* (dP/dy). DV01/PV01 : calcul et usage pour dimensionner une position.
- **Convexité** : dérivation, approximation ΔP ≈ −D·Δy + ½·C·(Δy)².
- Courbe des taux : taux zéro-coupon vs taux actuariels vs taux forward. **Bootstrapping** — fais-le à la main sur 3–4 maturités.
- Théories de la courbe (anticipations, prime de liquidité, habitat préféré).

### Après-midi (3h) — Marché obligataire marocain

- **BDT (bons du Trésor)** : maturités (13 sem. à 30 ans), adjudications hebdomadaires du Trésor (mardis), technique d'adjudication à la hollandaise (prix multiples), rôle des **IVT** (intermédiaires en valeurs du Trésor — BMCE Capital en fait partie).
- **Courbe de référence BAM** : publiée quotidiennement, comment elle est construite (transactions fermes + adjudications).
- Marché secondaire : OTC, liquidité concentrée sur certaines lignes ; **repo / pension livrée** comme outil de financement et de levier.
- Stratégies de courbe : **steepener / flattener**, butterfly, carry & roll-down — sache calculer le carry total d'une position BDT financée en repo.
- Contexte : besoin de financement du Trésor, trajectoire du déficit (3,5% en 2026), impact des levées sur la courbe.
- Swaps de taux (IRS) et FRA : mécanique, valorisation comme échange de jambes, usage en couverture de duration.

### Soir (1–2h) — Exercices

- 10 calculs : prix, YTM, duration, DV01, P&L d'une position pour ±25 pb.
- Question type : « La BCE vient de monter ses taux, BAM est en statu quo. Que fais-tu sur la courbe marocaine ? » Construis ta réponse structurée.

---

## DIMANCHE — FX, Commodities, Trades, Mock

### Matin (3h) — FX

- Conventions : cotation au certain/incertain, bid/ask, cross rates.
- **Parité couverte des taux d'intérêt (CIP)** : F = S·(1+r_dom·T)/(1+r_for·T) — dérivation par arbitrage, points de swap (points de terme).
- **FX swaps** : jambe spot + jambe forward, usage en gestion de trésorerie devises.
- **Régime du dirham** (à maîtriser parfaitement) :
  - Panier 60% EUR / 40% USD, bande de fluctuation ±5% (élargissements 2018 et 2020).
  - Cours de référence BAM, mécanisme d'intervention (adjudications de devises).
  - **Flexibilisation** : étape annoncée pour 2026 — sortie progressive de l'ancrage panier vers un ancrage par le taux directeur et la politique monétaire (ciblage d'inflation), sans flottement total. Jouahri : « techniquement prêts », ajustements du taux directeur 2–3×/an dans ce régime. Marché des swaps de devises développé depuis 2025. Position du FMI (flottement) vs prudence BAM.
  - Flux structurels MAD : transferts MRE (>100 Mds MAD/an), tourisme, facture énergétique en USD, phosphates.
- Options de change : Garman-Kohlhagen (extension de Black-Scholes que tu connais), usage des Greeks en FX.

### Après-midi (2–3h) — Commodities + idées de trades

- Pricing des futures : coût de portage, F = S·e^((r+u−y)T), convenience yield.
- **Contango / backwardation** : définition, lien avec les stocks et le convenience yield ; roll yield pour une position.
- Benchmarks : Brent vs WTI (et pourquoi le spread), or (valeur refuge, lien taux réels).
- Contexte actuel : choc Ormuz, Brent >110$, backwardation probable (prime de rareté spot) — vérifie la structure de la courbe.
- Angle Maroc : importateur net d'énergie et de blé → sensibilité du déficit courant et de l'inflation ; OCP/phosphates côté exports.
- **Prépare 3 idées de trades** (une par classe d'actifs), chacune avec : thèse, instrument, point d'entrée, stop, objectif, taille (via DV01 ou % de capital), risques. Exemples de thèses à travailler :
  1. *Taux MAD* : statu quo BAM + inflation faible vs pression haussière importée → vue sur une partie de la courbe BDT.
  2. *FX* : divergence BCE (hausse) / Fed (pause) → EUR/USD, et implication mécanique sur USD/MAD via le panier.
  3. *Commodities* : pétrole — prime géopolitique vs libérations de réserves stratégiques (IEA/SPR) ; ou or vs taux réels.

### Soir (2h) — Mock + comportemental

- **Mock technique** : 15 questions à voix haute, en français, chrono. Inclure : dérive la duration modifiée ; explique la CIP ; pourquoi le contango ; que fait la BCE en juillet ; un trade et défends-le sous contre-arguments.
- **Comportemental** (réviser, pas réapprendre) : présentation Present→Past→Future, motivation 3 couches réorientée *desk international*, STAR-L travail d'équipe (stage equity), faiblesse perfectionnisme.
- **Adapter ta thèse de marché** : « la valeur est socialement construite » fonctionne encore mieux en macro — crédibilité des banques centrales, primes de peur géopolitiques, anticipations auto-réalisatrices sur les courbes. Prépare 2 phrases qui font le pont equity → taux/FX.
- Discipline d'élocution : limiter les « donc », une idée = une phrase, structurer (1, 2, 3).

---

## Questions pièges probables (desk international, profil quant)

1. Dérive la duration modifiée à partir du prix. Pourquoi la convexité est-elle toujours « ton amie » en position longue ?
2. Le Trésor annonce une levée massive la semaine prochaine : impact sur la courbe ? Sur ton portefeuille ?
3. CIP : si le forward EUR/MAD ne respecte pas la parité, construis l'arbitrage pas à pas.
4. Pourquoi la BCE monte alors que l'inflation marocaine est < 1% ? BAM doit-elle suivre ?
5. Brent à 115$ : conséquences pour le Maroc (inflation, compte courant, dirham, courbe BDT) ?
6. Contango vs backwardation : où est le pétrole aujourd'hui et pourquoi ?
7. Différence entre trading compte propre et market-making ? Comment gères-tu une position perdante ?
8. Qu'est-ce que la VaR ? Ses limites ? (réponse honnête sur les queues de distribution — il appréciera)
9. La flexibilisation du dirham : risques et opportunités pour un desk de trading ?
10. Brainteaser/proba probable — révise espérance, Bayes, calcul mental rapide.

---

## Check-list finale (veille de l'entretien)

- [ ] Re-vérifier tous les niveaux de marché du jour (Brent, or, EUR/USD, USD/MAD, 10 ans US, courbe BDT).
- [ ] Résultat du FOMC 16–17 juin si l'entretien est après.
- [ ] Relire ta page dashboard + tes 3 idées de trades.
- [ ] 30 min de mock oral en français.
- [ ] Teams testé, tenue, CV sous les yeux.

**Ressources :** Hull ch. 4 (taux), ch. 5 (forwards/futures), ch. 7 (swaps), ch. 17 (options de change) ; site BAM (communiqués, courbe de référence, statistiques de change) ; Trésor (calendrier des adjudications) ; communiqué BCE du 11 juin ; minutes Fed d'avril.
