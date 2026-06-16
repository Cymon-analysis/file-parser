# File Parser — Normalisation & Cadrage Analytics Engineering

Outil en deux parties pour les missions de Data / Analytics Engineering :

1. **Normalisation** (`normaliser.py`) — transforme des fichiers hétérogènes
   (`sources_brutes/`) en TXT/CSV UTF-8 (`output_normalise/`).
2. **Cadrage v5** (`app.py`) — mode hybride + **mindmap interactive** (streamlit-vis-network).

## Prérequis

- Python 3.10+
- Clé API [Gemini](https://aistudio.google.com/apikey)
- (Optionnel) `NOTION_TOKEN` + `NOTION_PAGE_ID` pour l'export Notion
- (Optionnel) Drivers BDD : PostgreSQL, Snowflake ou BigQuery selon le dialecte

## Installation

```powershell
git clone https://github.com/Cymon-analysis/file-parser.git
cd file-parser
pip install -r requirements.txt
```

## Étape A — Normaliser les fichiers

```powershell
python normaliser.py
```

## Étape B — Application de cadrage (v5)

```powershell
pip install streamlit-vis-network
$env:GEMINI_API_KEY = "votre_cle_api"
streamlit run app.py
```

### Workflow en 4 étapes

1. **Sources hybrides** — fichiers locaux +/ou DDL BDD (échantillons anonymisés)
2. **Tokens & coût** — estimation Gemini
3. **Mindmap interactive** — pré-analyse graphe JSON, édition drag-and-drop, ajout/suppression de relations
4. **Livrable final** — génération Markdown basée sur le graphe validé + export Notion

## Architecture modulaire

```
cadrage/
  config.py           # constantes
  models.py           # SourceContexte
  sampling.py         # Smart Sampling FinOps
  sources_fichiers.py # scan output_normalise/
  db_schema.py        # extraction DDL lecture seule
  cache_semantique.py # cache MD5
  prompts.py          # prompts Gemini enrichis
  gemini_client.py    # API Gemini
  mermaid_utils.py    # extraction diagramme
  notion_export.py    # export Notion
app.py                # interface Streamlit
```

## Confidentialité

`sources_brutes/`, `output_normalise/` et `.cadrage_cache.json` sont exclus du dépôt.
