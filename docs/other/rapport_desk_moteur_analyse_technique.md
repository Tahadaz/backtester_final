# 3 propositions de titre professionnel

1. **Moteur d'Analyse Technique et Dashboard de Signaux**
2. **Plateforme de Lecture et de Priorisation des Signaux Techniques**
3. **Signal Engine Actions - Synthese Metier pour le Desk**

\newpage

# Resume executif

Ce document presente une brique de lecture technique developpee dans le cadre d'un travail realise au contact du desk, avec un objectif clair: transformer des donnees de marche en signaux lisibles, comparables et justifiables. Le produit ne cherche pas a automatiser la decision d'investissement. Il vise a fournir au desk une base de lecture plus structuree, plus homogène et plus traçable qu'une analyse titre par titre non standardisee.

Le socle livre repose sur trois elements complementaires. D'abord, un moteur de signaux techniques applique un pipeline A-G a plusieurs familles d'indicateurs afin d'eliminer les variantes fragiles, retenir les plus robustes et produire un score final interpretable. Ensuite, la page **Signals** permet de comprendre le signal d'un titre a haut niveau puis de descendre jusqu'aux familles et aux variantes representatives. Enfin, le **dashboard V1** restitue une vue transversale de l'univers, par titre, par secteur, par indice et par horizon d'investissement.

L'interet pour le desk est double. Sur le plan methodologique, le moteur privilegie l'evaluation **out-of-sample** et la robustesse plutot qu'une simple recherche du "meilleur parametre" historique. Sur le plan operationnel, le dashboard permet d'identifier rapidement les titres a surveiller, de comparer les lectures entre horizons court, moyen et long terme, puis de revenir au detail explicatif si un cas merite une analyse plus fine.

Les snapshots produits le **10 avril 2026** illustrent bien cette utilite. A court terme, l'indice agrege ressort en **Achat** avec un score de **+28,71**, contre **+13,64** a moyen terme et **+3,92** a long terme, ce qui montre un environnement plus favorable tactiquement que structurellement. Le systeme ne produit donc pas un verdict unique et rigide; il met en evidence des lectures differentielles selon l'horizon, ce qui est plus utile pour un desk qu'un signal uniforme.

Le produit reste volontairement sobre dans son perimetre. Le coeur livre est centre sur l'analyse technique, la restitution et la priorisation. Les evolutions deja amorcees portent sur l'extension du nombre de familles d'indicateurs, l'enrichissement de l'exploration detaillee et l'approfondissement de certaines couches de lecture. La valeur actuelle du produit est toutefois deja concrete: rendre la lecture technique plus coherente, plus explicable et plus exploitable a l'echelle du desk.

\newpage

# Version finale redigee complete

## Page de garde

**Moteur d'Analyse Technique et Dashboard de Signaux**  
**Support de presentation a destination du desk**

Document de synthese consacre a la brique d'analyse technique du projet.  
Cette solution a ete developpee dans le cadre d'un travail mene en environnement de desk, avec une ambition simple: produire une lecture des signaux plus rigoureuse, plus lisible et plus utile a la priorisation des titres.

Perimetre presente:  
**OHLCV canonique -> Signal Engine -> page Signals -> Dashboard V1**

\newpage

## 1. Contexte et problematique metier

Sur un desk actions, la lecture technique doit repondre a deux contraintes qui sont souvent difficiles a concilier.

La premiere est une contrainte de vitesse. Le desk doit pouvoir parcourir un univers de titres, identifier rapidement les cas prioritaires et distinguer ce qui releve d'un simple bruit de marche de ce qui merite une attention immediate.

La seconde est une contrainte de fiabilite. Une lecture technique fondee uniquement sur quelques indicateurs choisis a la main peut etre incoherente d'un titre a l'autre, tres dependante du parametre retenu et peu traçable lorsqu'il faut justifier pourquoi un signal est considere comme exploitable.

Le probleme concret adresse par le produit est donc le suivant: **comment industrialiser la lecture technique d'un univers actions sans tomber dans une logique de selection arbitraire ou de sur-interpretation des historiques**.

L'enjeu n'est pas de remplacer le jugement du desk. Il est de lui fournir un cadre de lecture plus robuste, qui permette:

- de comparer les titres sur une base commune;
- de distinguer plusieurs horizons de lecture;
- de comprendre rapidement d'ou vient un signal;
- de filtrer les indicateurs peu robustes avant qu'ils ne biaisent la decision.

Dans cette logique, le produit se positionne comme un **outil d'aide a la lecture et a la priorisation**, et non comme un moteur de decision autonome ou un systeme d'execution.

\newpage

## 2. Presentation de la solution

La solution repose sur deux surfaces complementaires.

La premiere est la page **Signals**. Elle sert a analyser un titre donne, a visualiser le score technique global, puis a descendre dans le detail des familles d'indicateurs et des variantes representatives qui composent le signal.

La seconde est le **dashboard V1**. Il transforme cette logique d'analyse en une logique de pilotage. Au lieu de raisonner uniquement titre par titre, le desk peut parcourir l'univers couvert, classer les actions, comparer les secteurs, lire la tonalite d'ensemble de l'indice et passer d'un horizon a l'autre.

Entre ces deux surfaces se trouve le coeur du produit: un **moteur de signaux techniques** fonde sur un pipeline A-G. Ce pipeline ne cherche pas a retenir le parametre historiquement le plus performant. Il genere plusieurs variantes, les evalue hors echantillon, mesure leur robustesse, elimine les variantes faibles ou redondantes, puis construit un signal final a partir des survivants.

Le socle publie aujourd'hui s'appuie sur **quatre familles coeur**:

- **SMA** pour la lecture de tendance;
- **MACD** pour la lecture de momentum;
- **RSI** pour la lecture d'oscillation;
- **OBV** pour la lecture du volume.

Ce choix est volontairement resserre. Il permet de couvrir plusieurs angles de lecture de marche tout en gardant une restitution lisible pour le desk. Une extension vers un univers plus large d'indicateurs existe deja comme perspective de la plateforme, mais elle ne constitue pas le coeur du livrable presente ici.

\newpage

## 3. Fonctionnement global et architecture

L'architecture fonctionnelle du perimetre presente peut se resumer ainsi:

**donnees de marche canoniques -> moteur de signaux -> restitution detaillee -> restitution de synthese**

### 3.1 Donnees d'entree

Le moteur consomme des donnees OHLCV canoniques par titre et par horizon d'analyse. Le produit ne repose donc pas sur une lecture ponctuelle du dernier chandelier seulement; il s'appuie sur un historique nettoye et exploitable.

### 3.2 Le pipeline A-G

Le moteur suit une chaine simple a expliquer, mais rigoureuse dans sa logique.

**A. Generation des candidats**  
Pour chaque famille, le systeme genere un ensemble de variantes parametriques. L'objectif n'est pas de parier d'avance sur un seul reglages, mais d'explorer un espace raisonnable de configurations.

**B. Evaluation out-of-sample**  
Chaque variante est evaluee par fenetres successives, selon une logique de type walk-forward. Le principe est de mesurer le comportement du signal sur des periodes non utilisees pour le calibrage, afin de reduire le risque d'illusion historique.

**C. Scoring de robustesse**  
Les resultats hors echantillon sont resumes en un score de fiabilite qui tient compte de la performance ajustee, de la stabilite dans le temps, de la regularite des resultats et du drawdown.

**D. Filtrage des survivants**  
Le systeme elimine les variantes qui ne sont pas suffisamment viables ou competitives. Cette etape evite de conserver des signaux qui existent seulement sur le papier.

**E. Reduction de redondance**  
Plusieurs variantes peuvent raconter pratiquement la meme histoire. Le moteur retire donc les variantes trop correlees pour eviter qu'un meme message soit compte plusieurs fois.

**F. Signal courant**  
Les variantes representatives restantes produisent un signal sur la derniere observation disponible.

**G. Ensemble final**  
Le signal de famille est construit en agregeant les variantes retenues, avec des poids lies a leur robustesse. Le systeme aboutit ainsi a un score interpretable, sur une echelle simple, plutot qu'a une juxtaposition d'indicateurs.

### 3.3 Surfaces utilisateur

La page **Signals** et le **dashboard** jouent deux roles distincts mais complementaires.

La page Signals repond a la question: **pourquoi ce titre a-t-il ce signal aujourd'hui ?**

Le dashboard repond a la question: **quels titres ou quels segments meritent l'attention du desk a cet horizon ?**

Cette separation est utile sur le plan metier. Elle permet de distinguer clairement le niveau d'explication analytique et le niveau de priorisation.

\newpage

## 4. Fonctionnalites cles

### 4.1 Lecture par horizon

Le produit distingue trois horizons:

- **court terme**;
- **moyen terme**;
- **long terme**.

Cette distinction n'est pas cosmetique. Les fenetres d'evaluation, la profondeur d'historique et la lecture du signal changent avec l'horizon. Le desk peut donc comparer un meme titre sous plusieurs angles temporels sans confondre un signal tactique avec une lecture plus structurelle.

### 4.2 Vue detaillee par titre

La page Signals propose une lecture par niveaux:

- un score technique global;
- une lecture par famille;
- un drill-down sur la famille selectionnee;
- un acces aux variantes representatives et a leur justification.

Cette profondeur de lecture est importante pour le desk. Un signal n'est pas seulement affiche; il peut etre explique.

### 4.3 Restitution transversale dans le dashboard

Le dashboard V1 fournit une lecture orientee exploitation:

- score global par titre;
- detail par famille;
- classement des actions;
- agregation par secteur;
- vue indice et breadth;
- niveaux techniques simples de lecture, autour du support, de la cloture et de la resistance;
- lien direct vers la page Signals pour passer de la synthese au detail.

Le dashboard transforme donc un moteur analytique en outil de tri, de comparaison et de priorisation.

### 4.4 Sorties concretes produites par l'application

Le produit genere des sorties qui ont un sens direct pour un public metier:

- un **score global** par titre;
- une **etiquette de lecture** simple, par exemple achat, neutre ou vente;
- des **scores par famille** pour comprendre l'origine du message;
- des **representants** et leur explication;
- une **vue secteur**;
- une **vue indice** avec repartition achat / neutre / vente;
- des **reperes de niveaux techniques** permettant de contextualiser le signal.

\newpage

## 5. Exemples de resultats et de valeur produite

Les snapshots exportes le **10 avril 2026** donnent une bonne image de la valeur operationnelle du produit.

### 5.1 Une lecture differenciee selon l'horizon

A court terme, l'indice agrege ressort en **Achat** avec un score de **+28,71**.  
La breadth associee est la suivante:

- **12 titres en achat**
- **3 titres neutres**
- **2 titres en vente**

A moyen terme, la lecture devient plus prudente: **+13,64**, soit **Neutre**.  
La breadth passe a:

- **7 titres en achat**
- **8 titres neutres**
- **2 titres en vente**

A long terme, le ton est encore plus modere: **+3,92**, soit toujours **Neutre**.  
La breadth devient:

- **3 titres en achat**
- **13 titres neutres**
- **1 titre en vente**

Pour le desk, cette difference est utile. Elle montre qu'un marche peut rester exploitable tactiquement sans pour autant envoyer un message fort sur un horizon plus long.

### 5.2 Un exemple titre: ADH a moyen terme

Sur le snapshot moyen terme du 10 avril 2026, **ADH** ressort en **Achat fort** avec un score global de **+75,0**.

La lecture detaillee montre:

- **SMA**: tres haussier;
- **MACD**: fort momentum haussier;
- **OBV**: forte accumulation;
- **RSI**: neutre, sans variante survivante a ce stade.

Cet exemple est interessant car il illustre bien la logique du moteur. Le systeme ne force pas artificiellement un consensus parfait. Il peut produire un signal global fort tout en montrant qu'une famille, ici le RSI, n'apporte pas de conviction suffisante. Pour un desk, cette nuance est plus utile qu'un simple "vert partout".

### 5.3 Une lecture de priorisation

A court terme, les meilleurs scores du snapshot comprennent notamment:

- **AKT** a **+75,0**
- **CDM** a **+75,0**
- **ADH** a **+75,0**
- **LHM** a **+50,0**
- **IAM** a **+50,0**

Dans le meme temps, les lectures les plus faibles comprennent par exemple:

- **ADI** a **-31,96**
- **CFG** a **-25,0**

Ce type de sortie permet au desk de faire rapidement deux choses:

1. identifier les titres a surveiller en priorite;
2. repérer les dossiers a surveiller dans un sens plus defensif ou plus prudent.

### 5.4 Une vue sectorielle exploitable

Le produit ne s'arrete pas a la lecture par titre. Il produit aussi une synthese par secteur.

Par exemple:

- a court terme, la **Sante** ressort en **Achat** a **+50,0**;
- a moyen terme, l'**Immobilier** ressort en **Achat** a **+36,27**;
- a long terme, la lecture reste plus reservee, avec peu de secteurs franchement directionnels.

Cette vue sectorielle apporte un niveau de lecture supplementaire pour le desk: elle permet de voir si les signaux positifs sont disperses ou concentres, et si une logique de rotation apparait.

\newpage

## 6. Valeur ajoutee pour le desk

La valeur du produit pour le desk peut se resumer en cinq points.

### 6.1 Une lecture plus homogène

Le moteur applique la meme logique de construction a l'ensemble des titres couverts. Cela reduit les differences de traitement d'un dossier a l'autre et facilite les comparaisons.

### 6.2 Une meilleure priorisation

Le dashboard permet de passer d'une lecture dispersee a une vue ordonnee. Le desk peut se concentrer plus vite sur les titres ou segments qui ressortent reellement.

### 6.3 Une meilleure explicabilite

Le produit ne livre pas seulement un score. Il permet de remonter aux familles contributrices, puis aux variantes representatives, ce qui facilite la discussion et la justification de la lecture.

### 6.4 Une lecture multi-horizon

Le produit aide a separer le tactique du plus structurel. Pour un desk, cette distinction est precieuse, car elle evite de melanger des messages qui n'ont pas le meme horizon d'exploitation.

### 6.5 Une discipline methodologique utile

Le recours a l'evaluation **out-of-sample** et au filtrage par robustesse apporte une discipline qui a du sens metier. Le systeme essaie de limiter le risque de sur-interpreter un indicateur simplement parce qu'il "a bien marche" sur l'historique retenu.

En pratique, cela ne supprime pas le risque de faux signal. En revanche, cela donne au desk un cadre plus defensif, plus standardise et plus transparent pour lire la technique.

\newpage

## 7. Limites actuelles et perspectives

Le produit est utile dans son perimetre actuel, mais plusieurs limites doivent etre posees clairement.

### 7.1 Limites actuelles

La premiere limite est de perimetre. Le coeur publie est volontairement centre sur **quatre familles**. Ce choix renforce la lisibilite, mais il ne couvre pas encore toute la richesse des lectures techniques possibles.

La deuxieme limite concerne la donnees. Comme pour tout systeme de lecture de marche, la qualite et la fraicheur des donnees conditionnent directement la qualite du signal.

La troisieme limite est d'usage. Le produit est un outil d'aide a l'analyse. Il ne doit pas etre lu comme une consigne d'execution. La decision finale doit rester contextualisee par le desk, en tenant compte du flux, de la liquidite, du contexte fondamental et de la dynamique de marche du moment.

### 7.2 Perspectives

Les evolutions les plus naturelles sont les suivantes:

- etendre progressivement le nombre de familles d'indicateurs tout en conservant la meme discipline de robustesse;
- enrichir encore l'exploration detaillee de certaines familles;
- approfondir certaines couches de lecture experimentales;
- renforcer encore la restitution comparative entre titres, secteurs et horizons.

La bonne logique d'evolution n'est pas d'ajouter de la complexite pour elle-meme. Elle est de conserver ce qui fait deja la valeur du produit aujourd'hui: **une lecture technique plus structuree, plus explicable et plus utile pour la priorisation**.

## Conclusion

Le produit presente ici repond a un besoin concret du desk: passer d'une lecture technique fragmentee a une lecture plus industrialisee, sans perdre la capacite d'expliquer ce que dit le signal.

Le moteur de signaux apporte la rigueur methodologique. La page Signals apporte l'explicabilite. Le dashboard apporte la synthese et la priorisation.

Pris ensemble, ces trois elements constituent une brique credible et deja utile pour un environnement de desk actions: non pas un moteur de decision autonome, mais un outil de lecture qui aide a mieux voir, mieux comparer et mieux justifier.

\newpage

# Version concise - note de support

## Moteur d'analyse technique et dashboard de signaux

Le produit presente une brique d'aide a la lecture technique concue pour transformer des donnees de marche en signaux lisibles, comparables et justifiables. Il ne cherche pas a automatiser la decision du desk. Son objectif est d'ameliorer la qualite de lecture, la priorisation et la traçabilite des signaux.

Le coeur de la solution repose sur un **pipeline A-G**:

- generation de variantes d'indicateurs;
- evaluation **out-of-sample** par logique walk-forward;
- scoring de robustesse;
- filtrage des variantes faibles;
- reduction de redondance;
- calcul du signal courant;
- agregation finale en un score interpretable.

Le socle actuellement livre s'appuie sur **quatre familles coeur**:

- SMA pour la tendance;
- MACD pour le momentum;
- RSI pour l'oscillation;
- OBV pour le volume.

La solution est exposee a travers deux surfaces:

- la page **Signals**, pour analyser un titre en detail;
- le **dashboard V1**, pour prioriser l'univers par titre, secteur, indice et horizon.

Le dashboard apporte une valeur directe pour le desk:

- lecture globale par titre;
- comparaison multi-horizon;
- lecture par famille;
- synthese sectorielle;
- breadth de marche;
- lien direct entre synthese et detail explicatif.

Les snapshots du **10 avril 2026** illustrent cette utilite. L'indice agrege ressort en **Achat** a court terme (**+28,71**), puis **Neutre** a moyen terme (**+13,64**) et a long terme (**+3,92**). Le systeme distingue donc une tonalite tactique plus favorable qu'une lecture plus structurelle.

Exemple concret: a moyen terme, **ADH** ressort en **Achat fort** (**+75,0**), avec une contribution positive de la tendance, du momentum et du volume, tandis que le RSI reste neutre. Cette restitution est utile car elle combine conviction et nuance.

La valeur ajoutee du produit tient a trois points:

- il standardise la lecture technique;
- il aide a prioriser rapidement les titres;
- il permet de remonter du score global vers une justification analytique.

Les principales limites sont connues: perimetre publie encore centre sur 4 familles, dependance a la qualite des donnees et necessite de conserver le jugement du desk comme arbitre final.

\newpage

# Version tres courte - note remise au desk

Le produit presente une brique d'analyse technique destinee a aider le desk a lire et a prioriser les signaux de marche de facon plus homogène et plus traçable.

Il repose sur un moteur qui teste plusieurs variantes d'indicateurs, les evalue hors echantillon, elimine les variantes fragiles ou redondantes, puis construit un score final interpretable. Le socle actuellement mis en avant repose sur quatre familles coeur: **SMA, MACD, RSI et OBV**.

Deux surfaces rendent ce moteur exploitable:

- la page **Signals**, pour comprendre le signal d'un titre;
- le **dashboard V1**, pour classer les actions, lire les secteurs, observer la breadth de l'indice et comparer les horizons.

La valeur pour le desk est concrete: meilleure priorisation, meilleure lisibilite et meilleure capacite a justifier la lecture technique.

\newpage

# Proposition de mise en page page par page

## Page 1 - Couverture

- Titre du document
- Sous-titre court: support de presentation pour le desk
- 3 lignes de contexte maximum
- bloc de perimetre: `OHLCV canonique -> Signal Engine -> Signals -> Dashboard V1`

## Page 2 - Contexte et enjeu

- probleme metier
- pourquoi une lecture standardisee des signaux est utile
- ce que le produit cherche a resoudre

## Page 3 - Presentation de la solution

- schema simple du pipeline A-G
- description des 4 familles coeur
- articulation entre moteur, page Signals et dashboard

## Page 4 - Fonctionnement global

- explication simple des etapes A a G
- focus sur la logique out-of-sample et la robustesse
- encadre court sur la lecture multi-horizon

## Page 5 - Fonctionnalites et exemples

- points forts fonctionnels
- exemples issus du snapshot du 10 avril 2026
- cas titre: ADH moyen terme
- cas indice: comparaison court / moyen / long terme

## Page 6 - Valeur pour le desk

- priorisation
- comparabilite
- explicabilite
- vue sectorielle et indice

## Page 7 - Limites et perspectives

- limites actuelles
- cadre d'utilisation
- perspectives d'extension
- conclusion courte

\newpage

# Captures d'ecran et figures a integrer

## Captures d'ecran prioritaires

1. **Dashboard V1 - vue actions, horizon court terme**  
   Montrer le classement des titres, les colonnes par famille et le signal technique global.

2. **Dashboard V1 - vue actions, horizon moyen ou long terme**  
   Utiliser une deuxieme capture pour montrer qu'un meme univers change de tonalite selon l'horizon.

3. **Dashboard V1 - vue secteurs**  
   Utile pour illustrer la capacite de synthese par segment de marche.

4. **Dashboard V1 - vue indice / breadth**  
   A integrer pour montrer la lecture agregée du marche.

5. **Page Signals - niveau global**  
   Capture du score technique global d'un titre avec la lecture par familles.

6. **Page Signals - drill-down d'une famille**  
   Idealement une famille claire visuellement, pour montrer les variantes testees, viables, competitives et representatives.

7. **Page Signals - detail d'un representant ou d'une variante**  
   A utiliser pour montrer qu'un signal est justifiable et pas seulement affiche.

## Figures a creer ou simplifier dans le document

1. **Schema fonctionnel simple**
   `OHLCV -> Pipeline A-G -> Signals -> Dashboard`

2. **Schema A-G sur une ligne**
   `Candidats -> Eval OOS -> Robustesse -> Filtrage -> Redondance -> Signal courant -> Ensemble`

3. **Mini tableau de comparaison multi-horizon**
   - court terme: +28,71, Achat
   - moyen terme: +13,64, Neutre
   - long terme: +3,92, Neutre

4. **Mini tableau d'exemple titre**
   - ADH moyen terme
   - SMA: positif
   - MACD: positif
   - RSI: neutre
   - OBV: positif
   - score global: +75,0

\newpage

# Notes de redaction pour usage immediat

- Garder des paragraphes courts.
- Ne pas parler du code, des fichiers ni des routes internes dans la version imprimee, sauf si tu veux une annexe technique.
- Mentionner le stage uniquement en ouverture, en une phrase.
- Eviter toute formulation de type promesse de performance.
- Toujours parler de **lecture**, **priorisation**, **aide a l'analyse** et **robustesse methodologique**.

