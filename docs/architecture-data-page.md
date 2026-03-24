# Architecture de la Page Data

## Philosophie

La page Data traite les données de marché comme un **actif de première classe** — pas un simple input. C'est la fondation de tout le pipeline quantitatif. Un signal calculé sur des données manquantes ou corrompues est pire qu'inutile : il donne une fausse confiance.

Cette philosophie s'aligne avec de Prado (AFML, Ch. 2-3) : *"Data curation is the most underappreciated step in the investment research pipeline."*

---

## Structure de la Page

```
┌────────────────────────────────────────────────────────────────────┐
│                         Page /data                                 │
│                                                                    │
│  ┌──────────────────────┐  ┌────────────────────────────────────┐ │
│  │  Catalogue symboles  │  │   Panneau détail (StockDetailPanel)│ │
│  │                      │  │                                    │ │
│  │  [ATW] ★ 🟢          │  │  Chandelier OHLCV                 │ │
│  │  [BCP] ★ 🟡          │  │  Bande d'années + mois            │ │
│  │  [IAM] ★ 🔴          │  │  Calendrier de disponibilité      │ │
│  │  [MNG]   ⊘           │  │  10 dernières barres              │ │
│  │                      │  │  Métadonnées éditables             │ │
│  │  [+ Ajouter]         │  │                                    │ │
│  │  [📤 Upload Excel]   │  │                                    │ │
│  │  [🔄 Rafraîchir]     │  │                                    │ │
│  └──────────────────────┘  └────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
```

---

## Composants

### 1. Catalogue de Symboles (page.tsx)

**Rôle** : Vue unifiée de tous les symboles connus du système.

**Sources fusionnées** :
- `market_data_store` : symboles avec données OHLCV ingérées (ont un fichier Parquet dans MinIO)
- `stock_master` : symboles suivis mais pas encore ingérés (état "pending")

**Indicateurs visuels** :
- 🟢 Données fraîches (< 2 jours ouvrés de retard)
- 🟡 Données vieillissantes (2-7 jours)
- 🔴 Données très périmées (> 7 jours)
- ⊘ Pas encore de données

**Actions globales** :
- **Upload Excel** → ouvre `ExcelUploadDialog`
- **Rafraîchir tout** → `POST /market-data/refresh` → déclenche le worker RQ
- **Rafraîchir un symbole** → `POST /market-data/stocks/{symbol}/refresh`

### 2. ExcelUploadDialog (excel-upload-dialog.tsx)

**Rôle** : Importer des données OHLCV depuis des fichiers Excel.

**Workflow** :
```
Utilisateur                  Frontend                  Backend                 Worker
    │                           │                        │                       │
    │── Sélectionne .xlsx ────→│                        │                       │
    │                           │── POST /excel ────────→│                       │
    │                           │                        │── Stocke dans MinIO   │
    │                           │                        │── Enqueue job ───────→│
    │                           │                        │                       │── Détecte format
    │                           │←─ {dataset_id} ───────│                       │── Parse dates
    │                           │                        │                       │── Nettoie numériques
    │                           │── GET /status (poll)──→│                       │── Merge avec existant
    │                           │←─ {processing} ───────│                       │── Upsert dans DB
    │                           │── GET /status (poll)──→│←─ Rapport terminé ───│
    │                           │←─ {done, report} ─────│                       │
    │←─ Affiche résultats ─────│                        │                       │
```

**Formats supportés** :
| Format | Source | Colonnes | Nombres |
|--------|--------|----------|---------|
| BMCE Nouveau | Bourse de Casablanca (export récent) | Séance, Ouverture, +haut du jour... | Français (1 052,00) |
| BMCE Ancien | Bourse de Casablanca (export legacy) | Date, Ouvt, '+Haut... | Français avec apostrophes |
| Investing.com | Export web anglophone | Date, Dernier, Ouv., Plus Haut... | Anglais (1,052.00), suffixes K/M/B |

**Innovation — Parsing des dates ambiguës** :
Pour les dates comme `01/02/2023` (est-ce le 1er février ou le 2 janvier ?), le système utilise la programmation dynamique :
- Construit un graphe de toutes les interprétations possibles
- Pénalise : dates futures, séquences non monotones, gaps > 45 jours
- Choisit la séquence globalement la plus cohérente

### 3. StockDetailPanel (stock-detail-panel.tsx)

**Rôle** : Inspection complète d'un symbole — données, qualité, métadonnées.

**Sections** :

#### a. En-tête
- Badge du symbole
- Indicateur "Tracked" / source provider
- Plage de données (Début → Fin)
- Nombre de barres

#### b. Graphique Chandelier OHLCV
- Plotly.js : chandeliers (vert/rouge) + volume en subplot
- `rangebreaks` : masque les weekends et jours fériés marocains
- Vue par défaut : 1 an, zoom libre

#### c. Bande d'Années
Mini-calendrier montrant la couverture par mois :
```
2023:  Jan[22j] Fev[19j] Mar[23j] Avr[20j 1gap] ...
2024:  Jan[21j] Fev[20j] Mar[0j !!] ...
```
- Codes couleur par densité de données
- Les gaps sont mis en évidence

#### d. Calendrier de Disponibilité
Grille mensuelle (7 colonnes = Lun-Dim) :
| État | Couleur | Signification |
|------|---------|---------------|
| `present_data` | 🟩 Émeraude | Barre OHLCV existe |
| `missing_expected_day` | 🟨 Ambre | Jour ouvré attendu, pas de données → **"GAP"** |
| `weekend` | ⬜ Gris | Samedi/Dimanche |
| `market_holiday` | 🟦 Bleu ciel | Jour férié marocain confirmé |
| `tentative_market_holiday` | 🟪 Fuchsia | Jour férié probable mais non officiel |

#### e. 10 Dernières Barres
Table OHLCV pour vérification rapide (les valeurs aberrantes sont visibles immédiatement).

#### f. Métadonnées Éditables
- Nom d'affichage (lecture seule)
- ISIN (format `MA[A-Z0-9]{10}`)
- Secteur (dropdown)
- URL Bourse de Casablanca
- Bouton "Auto-remplir depuis la Bourse" → scrape la page officielle

---

## Backend : Pipeline d'Ingestion

### Invariants de Données

1. **Format canonique** : Toutes les données OHLCV sont stockées en Parquet, float64, DatetimeIndex UTC
2. **Clé S3** : `market_data/{symbol}/1D.parquet` — une seule vérité par symbole/timeframe
3. **Pas de suppression** : Les anciennes données ne sont jamais effacées, seulement mises à jour si elles diffèrent
4. **Pas de dates futures** : Filtrées systématiquement avant merge
5. **Dédoublonnage** : `keep='last'` sur le DatetimeIndex

### Merge Delta

```
Données existantes (Parquet)  +  Nouvelles données (Excel/API)
         │                                │
         └──────────┬─────────────────────┘
                    │
         ┌──────────▼──────────┐
         │  Pour chaque date :  │
         │                      │
         │  Nouvelle date ?     │ ──→ INSERT
         │  Date existante ?    │ ──→ UPDATE seulement si O/H/L/C/V
         │                      │     diffère de > 0.1%
         │  Date absente du     │ ──→ CONSERVER (pas de suppression)
         │  nouveau fichier ?   │
         └──────────────────────┘
```

### Scheduling Automatique

```
Cron : Lun-Ven à 18:00 Africa/Casablanca
  │
  ▼
Pour chaque symbole actif dans stock_master :
  │
  ├── Source "bourse_direct" → Scrape page officielle
  ├── Source "yahoo" → yfinance avec mapping symbole (ex: ATW → ATW.CS)
  │
  ▼
Merge delta avec Parquet existant → Upsert dans market_data_store
```

---

## Calendrier des Jours Fériés Marocains

Le fichier `casablanca_exchange_holidays.json` contient les fermetures de la Bourse de Casablanca :

- **Confirmés** : Fête du Trône, Aid al-Fitr, Aid al-Adha, Jour de l'Indépendance, etc.
- **Provisoires** : Dates qui dépendent du calendrier lunaire (annoncées 1-2 jours avant)

Ce calendrier est utilisé :
1. Dans le graphique chandelier (masquer les gaps de weekends/jours fériés)
2. Dans le calendrier de disponibilité (distinguer "gap" de "fermeture normale")
3. Dans le calcul de fraîcheur (ne pas compter les jours fériés comme retard)

---

## Endpoints API

| Méthode | Route | Rôle |
|---------|-------|------|
| GET | `/market-data/catalog` | Liste fusionnée de tous les symboles |
| POST | `/market-data/excel` | Upload d'un fichier Excel |
| GET | `/market-data/uploads/{id}/status` | Polling du statut d'ingestion |
| GET | `/market-data/stocks/{symbol}/ohlcv-preview` | Dernières N barres |
| GET | `/market-data/stocks/{symbol}/ohlcv-history` | Historique complet |
| GET | `/market-data/stocks/{symbol}/availability-calendar` | Calendrier jour par jour |
| POST | `/market-data/refresh` | Rafraîchir tous les symboles actifs |
| POST | `/market-data/stocks/{symbol}/refresh` | Rafraîchir un symbole |
| GET | `/market-data/stocks/{symbol}/bourse-lookup` | Scrape métadonnées Bourse de Casa |
| GET | `/market-data/health` | Résumé de fraîcheur globale |
| GET | `/market-data/upload-format-reference` | Documentation des formats acceptés |

---

## Raisonnement Architectural

### Pourquoi une page Data dédiée ?

1. **Séparation des responsabilités** (de Prado) : La qualité des données est un problème distinct de l'analyse des signaux
2. **Observabilité** : On ne peut pas corriger ce qu'on ne voit pas — le calendrier montre immédiatement les gaps
3. **Autonomie** : L'utilisateur peut vérifier et corriger les données avant de lancer tout calcul
4. **Contexte marocain** : La Bourse de Casablanca a des formats d'export spécifiques, des jours fériés islamiques (dates variables), et des symboles sans tickers standardisés — tout cela nécessite un traitement dédié

### Pourquoi le merge delta ?

- **Idempotence** : Réimporter le même fichier ne crée pas de doublons
- **Préservation de l'historique** : On ne perd jamais de données anciennes
- **Correction** : Si un cours est corrigé par la Bourse, il est mis à jour automatiquement (différence > 0.1%)

### Pourquoi le scheduling à 18h ?

- La Bourse de Casablanca clôture à 15h30
- Les données officielles sont publiées entre 16h et 17h30
- 18h00 laisse une marge de sécurité pour que les sources soient à jour

---
