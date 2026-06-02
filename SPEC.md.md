# Suivi Nutrition — Spec

## Vision

App mobile-first de suivi nutritionnel avec saisie vocale ou photo.
Design champêtre/bio inspiré de Yuka, coloré, avec illustrations de nourriture.
Accessible depuis le téléphone via Railway.

## Ce que l'app fait

* Saisie d'un repas par **dictée vocale** (Whisper API OpenAI) ou **photo** (Claude Vision)
* Claude extrait les aliments, quantités et calcule les macronutriments
* Enregistrement par repas : Petit déjeuner / Déjeuner / Goûter / Dîner
* 4 onglets :

  1. **Résumé** — calories du jour, macros, progression vers objectif
  2. **Macros** — détail protéines / glucides / lipides / fibres
  3. **Historique** — graphes calories + macros sur 7/30 jours
  4. **Profil** — taille, poids, objectif → calcul automatique apport recommandé

## Ce que l'app ne fait PAS (MVP)

* Pas de base de données alimentaire (Claude estime les macros)
* Pas de compte utilisateur / auth
* Pas de scan code-barres
* Pas de recettes

\---

## Stack

* Backend  : FastAPI + SQLite
* Frontend : HTML/JS vanilla, Tailwind CSS
* Transcription vocale : OpenAI Whisper API
* Vision : Anthropic API (Claude multimodal)
* Macros : Anthropic API (Claude texte)
* Déploiement : Railway

## UI/UX — Thème champêtre/bio

```bash
uipro init --ai claude
```

Style cible : **nature / bio / yuka-like**

* Palette : vert sauge (#7D9B76), beige chaud (#F5F0E0), orange doux (#F4A35A), rose pêche (#F9C784)
* Fond : texture papier kraft légère
* Typographie : "Nunito" (arrondi, friendly) + "Playfair Display" pour les titres
* Illustrations SVG de nourriture (fruits, légumes, assiettes) en décoration
* Cards avec coins arrondis genereux (border-radius: 20px)
* Ombres douces pastel
* Boutons style "tampon bio" avec icônes alimentaires
* Animations : bounce léger sur les macros, confetti si objectif atteint

\---

## Calcul apport recommandé (onglet Profil)

### Métabolisme de base (Harris-Benedict)

```
Homme : BMR = 88.36 + (13.4 × poids\\\_kg) + (4.8 × taille\\\_cm) - (5.7 × âge)
Femme : BMR = 447.6 + (9.2 × poids\\\_kg) + (3.1 × taille\\\_cm) - (4.3 × âge)
```

### Objectifs

|Objectif|Calories|Protéines|Glucides|Lipides|
|-|-|-|-|-|
|Prise de masse|BMR × 1.15|2g/kg|50% kcal|25% kcal|
|Perte de graisse|BMR × 0.85|2.2g/kg|40% kcal|25% kcal|
|Recomposition|BMR × 1.0|2g/kg|45% kcal|25% kcal|

\---

## Schéma base de données

```sql
-- Profil utilisateur
profile (
  id          INTEGER PRIMARY KEY,
  name        TEXT,
  gender      TEXT,        -- 'homme' / 'femme'
  age         INTEGER,
  weight\\\_kg   REAL,
  height\\\_cm   REAL,
  goal        TEXT,        -- 'masse' / 'graisse' / 'recompo'
  -- Calculés automatiquement :
  target\\\_kcal REAL,
  target\\\_prot REAL,
  target\\\_carb REAL,
  target\\\_fat  REAL,
  updated\\\_at  TEXT
)

-- Repas
meals (
  id          INTEGER PRIMARY KEY,
  date        TEXT NOT NULL,   -- YYYY-MM-DD
  meal\\\_type   TEXT NOT NULL,   -- 'petit\\\_dej' / 'dejeuner' / 'gouter' / 'diner'
  description TEXT,            -- ce que l'utilisateur a dicté/photographié
  items       TEXT,            -- JSON \\\[{name, qty\\\_g, kcal, prot, carb, fat}]
  total\\\_kcal  REAL,
  total\\\_prot  REAL,
  total\\\_carb  REAL,
  total\\\_fat   REAL,
  created\\\_at  TEXT
)
```

\---

## Endpoints API

|Méthode|Route|Description|
|-|-|-|
|GET|/today|Résumé du jour (tous repas + totaux)|
|GET|/meals/{date}/{meal\_type}|Repas d'un type pour une date|
|POST|/meals/voice|Upload audio → Whisper → Claude → macros|
|POST|/meals/photo|Upload image → Claude Vision → macros|
|POST|/meals/confirm|Confirme et enregistre un repas|
|DELETE|/meals/{id}|Supprime un repas|
|GET|/history|Historique 7/30 jours pour graphes|
|GET|/profile|Récupère le profil|
|POST|/profile|Crée/met à jour le profil|

\---

## Workflow saisie vocale

```
1. Utilisateur appuie sur 🎤 dans un repas
2. Enregistrement audio (MediaRecorder API)
3. Upload audio → POST /meals/voice
4. Backend → OpenAI Whisper API → texte
5. Texte → Claude :
   "Identifie les aliments et quantités dans : '{texte}'
    Retourne JSON : \\\[{name, qty\\\_g, kcal, prot\\\_g, carb\\\_g, fat\\\_g}]"
6. Affichage des aliments détectés pour confirmation
7. Utilisateur valide → POST /meals/confirm
```

## Workflow photo

```
1. Utilisateur prend une photo du repas
2. Upload image → POST /meals/photo
3. Backend → Claude Vision :
   "Identifie tous les aliments visibles et estime les quantités.
    Retourne JSON : \\\[{name, qty\\\_g, kcal, prot\\\_g, carb\\\_g, fat\\\_g}]"
4. Affichage pour confirmation
5. Utilisateur valide → POST /meals/confirm
```

## Prompt Claude — Analyse nutritionnelle

```
Tu es un expert en nutrition. Analyse ce repas et retourne 
UNIQUEMENT un JSON valide, sans texte autour :
\\\[
  {
    "name": "nom de l'aliment",
    "qty\\\_g": 150,
    "kcal": 165,
    "prot\\\_g": 31,
    "carb\\\_g": 0,
    "fat\\\_g": 3.6
  }
]
Utilise des valeurs nutritionnelles standard pour 100g.
Si la quantité n'est pas précisée, estime une portion normale.
```

\---

## Structure du projet

```
nutrition/
├── SPEC.md
├── CLAUDE.md                ← uipro init --ai claude
├── backend/
│   ├── main.py              ← FastAPI + routes
│   ├── database.py          ← SQLite + CRUD
│   ├── ai.py                ← OpenAI Whisper + Anthropic Claude
│   └── \\\_\\\_init\\\_\\\_.py
├── frontend/
│   ├── index.html           ← app principale (4 onglets)
│   └── app.js               ← logique JS
├── Dockerfile
├── railway.toml
├── requirements.txt
└── .env
```

\---

## Variables d'environnement

```
```

## Dépendances Python

```
fastapi>=0.111.0
uvicorn\\\[standard]>=0.29.0
anthropic>=0.28.0
openai>=1.0.0
python-multipart>=0.0.9
python-dotenv>=1.0.0
```

Pas de torch, pas de pyannote — tout via API. Installation en 30 secondes.

\---

## Ordre de développement (sprints)

**Sprint 1 — BDD + profil (1h)**
database.py : tables profile + meals, CRUD, calcul macros recommandés.

**Sprint 2 — Backend API (1h)**
main.py : tous les endpoints. Tester sur /docs.

**Sprint 3 — IA (1h)**
ai.py :

* transcribe\_voice(audio) → OpenAI Whisper → texte
* analyze\_food\_text(text) → Claude → JSON macros
* analyze\_food\_photo(image\_b64) → Claude Vision → JSON macros

**Sprint 4 — Frontend onglet Résumé + saisie (2h)**
Page principale, 4 onglets navigation, modal saisie (voix/photo),
cards repas avec historique du jour. Consulter ui-ux-pro-max SKILL.md.

**Sprint 5 — Frontend onglets Macros + Historique + Profil (2h)**
Graphes Chart.js pour l'historique, formulaire profil, calcul automatique objectifs.

**Total estimé : 7h**

\---

## Coût estimé mensuel

* Railway : \~2-3$/mois
* OpenAI Whisper : \~0.50$/mois (usage quotidien)
* Claude API : \~0.10$/mois
* **Total : \~3-4$/mois**

\---

## Règles Claude Code

* Lire SPEC.md avant de commencer
* Un sprint à la fois, attendre validation
* Consulter CLAUDE.md avant tout composant UI
* Single page app (SPA) : tout dans index.html + app.js
* Mobile-first : optimisé pour écran 390px
* Ne jamais committer .env

