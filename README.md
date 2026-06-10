# Normaliseur de fichiers pour IA (NotebookLM)

Transforme un dossier de fichiers hétérogènes (`sources_brutes/`) en fichiers
texte et CSV standardisés UTF-8 (`sources_normalisees/`), lisibles sans
ambiguïté par une IA comme NotebookLM.

**Règle générale : 1 fichier en entrée → 1 fichier en sortie** (découpé en
plusieurs parties uniquement s'il dépasse la limite de mots de NotebookLM).

## Prérequis

- Windows, macOS ou Linux
- [Python 3.10+](https://www.python.org/downloads/) — sous Windows :

```powershell
winget install Python.Python.3.12
```

(puis ouvrez un nouveau terminal pour que la commande `python` soit reconnue)

## Installation

```powershell
git clone <URL_DU_DEPOT>
cd file_parser
pip install -r requirements.txt
```

## Utilisation

1. Créez un dossier `sources_brutes/` à la racine du projet (s'il n'existe pas).
2. Déposez-y vos fichiers à convertir (les sous-dossiers sont parcourus).
3. Lancez :

```powershell
python normaliser.py
```

4. Récupérez les fichiers convertis dans `sources_normalisees/` et importez-les
   comme sources dans NotebookLM (ignorez `_MANIFEST.csv`, c'est le journal des
   conversions).

### Options

```powershell
python normaliser.py --entree mon_dossier --sortie mon_dossier_normalise
python normaliser.py --max-mots 200000   # seuil de découpage (0 = désactivé)
```

## Règles de conversion

| Type d'entrée | Sortie |
|---|---|
| `.xlsx` `.xlsm` `.xls` | 1 feuille : un CSV UTF-8 ; plusieurs feuilles : un seul `.txt` avec chaque feuille au format CSV, délimitée par `>>> FEUILLE : nom` |
| `.csv` `.tsv` | CSV ré-encodé UTF-8, séparateur normalisé en virgule |
| `.pdf` | `.txt` avec texte extrait, page par page |
| `.docx` | `.txt` avec titres (`#`), paragraphes et tableaux (`a \| b \| c`) |
| `.pptx` | `.txt` avec texte par diapositive |
| `.html` `.htm` | `.txt` sans balises |
| `.sql` `.md` `.json` `.xml` `.yaml`, code (`.py`, `.js`, `.qvs`, ...) | `.txt` ré-encodé UTF-8 (`fichier__ext.txt`) |
| `.zip` | un seul `.txt` consolidé, chaque fichier interne délimité par `>>> FICHIER : chemin` ; les binaires sont ignorés |
| Autres extensions | Ignorées (listées dans le manifeste) |

## Découpage automatique

NotebookLM accepte environ 500 000 mots par source. Tout fichier de sortie
dépassant `--max-mots` (400 000 par défaut) est automatiquement découpé en
plusieurs parties (`fichier_partie_1_sur_3.txt`, ...), avec coupes sur des
lignes entières. Pour un CSV, la ligne d'en-tête est répétée dans chaque
partie ; pour un `.txt`, chaque partie commence par un bandeau `PARTIE x / y`.

## Sortie

- Chaque fichier `.txt` commence par un en-tête de métadonnées (fichier source,
  type d'origine, date de conversion).
- Les noms de fichiers sont normalisés en ASCII minuscule (sans accents ni espaces).
- Un fichier `_MANIFEST.csv` récapitule chaque conversion (source, catégorie,
  statut, fichiers produits, erreur éventuelle).

## Codes de retour

- `0` : tout s'est bien passé
- `1` : dossier d'entrée introuvable
- `2` : au moins un fichier a provoqué une erreur (les autres sont quand même convertis)

## Confidentialité

Les dossiers `sources_brutes/` et `sources_normalisees/` sont exclus du dépôt
via `.gitignore` : vos données ne sont jamais publiées, seul le code l'est.
