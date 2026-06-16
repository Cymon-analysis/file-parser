"""Construction des prompts système et utilisateur pour Gemini."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from cadrage.config import DOSSIER_EXTRACTION_TEMP, DOSSIER_NORMALISE
from cadrage.models import SourceContexte

CONSIGNE_ANTI_HALLUCINATION = """
ATTENTION : Tu as l'interdiction formelle d'inventer des noms de tables ou de colonnes.
Tu dois baser ton Dictionnaire de données, ta Matrice de Mapping et ton Code
(Sections 2, 3 et 4) UNIQUEMENT et STRICTEMENT sur les vrais fichiers et échantillons
fournis dans la section « DEBUT DES DONNEES REELLES CLIENT ».
Si une donnée n'est pas présente dans l'échantillon, ne l'invente pas — indique
explicitement « non documenté dans les sources » plutôt que d'halluciner.
N'utilise JAMAIS de tables génériques d'exemple (orders, products, customers, etc.)
sauf si elles apparaissent littéralement dans les sources fournies.
"""

MARQUEUR_DEBUT_PAYLOAD = "=== DEBUT DES DONNEES REELLES CLIENT ==="
MARQUEUR_FIN_PAYLOAD = "=== FIN DES DONNEES REELLES CLIENT ==="


def _resume_sources_hybrides(sources: list[SourceContexte]) -> str:
    nb_fichiers = sum(1 for s in sources if s.type_source == "fichier")
    nb_ddl = sum(1 for s in sources if s.type_source == "ddl")
    parties = []
    if nb_fichiers:
        parties.append(f"{nb_fichiers} fichier(s) local(aux)")
    if nb_ddl:
        parties.append(f"{nb_ddl} structure(s) BDD (DDL)")
    if not parties:
        return "Aucune source"
    if len(parties) == 2:
        return f"Mode hybride : {' + '.join(parties)}"
    return parties[0]


def extraire_contenu_echantillon(source: SourceContexte) -> str:
    """
    Récupère le contenu le plus complet disponible pour une source.
    Fallback : payload → original → aperçu → relecture disque (fichiers).
    """
    for candidat in (
        source.contenu_payload,
        source.contenu_original,
        source.echantillon_apercu,
    ):
        if candidat and candidat.strip():
            return candidat.strip()

    if source.type_source != "fichier":
        return ""

    rel = source.metadonnees.get("chemin_relatif", "")
    if not rel and source.identifiant.startswith("ingest:"):
        rel = source.identifiant.split(":", 1)[-1]

    chemins_candidats: list[Path] = []
    if rel:
        chemins_candidats.extend([
            DOSSIER_EXTRACTION_TEMP / rel,
            DOSSIER_NORMALISE / rel,
        ])
    if source.identifiant and not source.identifiant.startswith("ddl:"):
        chemins_candidats.append(DOSSIER_NORMALISE / source.identifiant)

    for chemin in chemins_candidats:
        try:
            if chemin.is_file():
                return chemin.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
    return ""


def extraire_ddl_source(source: SourceContexte) -> str:
    """Extrait la partie DDL d'une source base de données."""
    if source.type_source != "ddl":
        return ""
    contenu = extraire_contenu_echantillon(source)
    if not contenu:
        return ""
    if "## SCHÉMA DDL" in contenu:
        partie = contenu.split("## ÉCHANTILLON", 1)[0]
        return partie.replace("## SCHÉMA DDL", "").strip()
    if "CREATE TABLE" in contenu.upper():
        idx = contenu.upper().find("CREATE TABLE")
        avant_echantillon = contenu[idx:]
        for sep in ("## ÉCHANTILLON", "--- ÉCHANTILLON", "Format CSV"):
            if sep in avant_echantillon:
                return avant_echantillon.split(sep, 1)[0].strip()
        return avant_echantillon.strip()
    return contenu


def _libelle_type_source(source: SourceContexte) -> str:
    if source.type_source == "ddl":
        return "Base de données"
    return "Fichier"


def compiler_contexte_sources(sources: list[SourceContexte]) -> str:
    """
    Compile explicitement le contenu de toutes les sources sélectionnées
    dans un payload textuel structuré pour injection dans le prompt Gemini.
    """
    if not sources:
        return (
            f"{MARQUEUR_DEBUT_PAYLOAD}\n"
            "(AUCUNE SOURCE SÉLECTIONNÉE — le consultant doit cocher au moins une source)\n"
            f"{MARQUEUR_FIN_PAYLOAD}"
        )

    blocs: list[str] = [MARQUEUR_DEBUT_PAYLOAD]

    for source in sources:
        contenu = extraire_contenu_echantillon(source)
        ddl = extraire_ddl_source(source) if source.type_source == "ddl" else ""
        type_libelle = _libelle_type_source(source)

        bloc_lignes = [
            f"FICHIER/TABLE : {source.nom}",
            f"TYPE : {type_libelle}",
            f"IDENTIFIANT : {source.identifiant}",
            f"EXTENSION / FORMAT : {source.extension or 'n/a'}",
        ]
        if source.smart_sample_applique:
            bloc_lignes.append(
                f"SMART SAMPLING : OUI (réduction {source.reduction_pct:.0f}%)"
            )
        if ddl and ddl != contenu:
            bloc_lignes.extend([
                "DDL (SCHÉMA RÉEL) :",
                '"""',
                ddl,
                '"""',
            ])
        bloc_lignes.extend([
            "CONTENU (ÉCHANTILLON CONCRET) :",
            '"""',
            contenu if contenu else "(CONTENU VIDE — source non lisible)",
            '"""',
            "-----------------------------------------",
        ])
        blocs.append("\n".join(bloc_lignes))

    blocs.append(MARQUEUR_FIN_PAYLOAD)
    return "\n".join(blocs)


def valider_payload_sources(payload: str, nb_sources: int) -> list[str]:
    """Retourne la liste des problèmes détectés dans le payload compilé."""
    problemes: list[str] = []
    if nb_sources == 0:
        problemes.append("Aucune source sélectionnée pour l'analyse.")
        return problemes
    if MARQUEUR_DEBUT_PAYLOAD not in payload:
        problemes.append("Marqueur de début des données réelles absent du payload.")
    contenu_utile = payload.replace(MARQUEUR_DEBUT_PAYLOAD, "").replace(MARQUEUR_FIN_PAYLOAD, "")
    if len(contenu_utile.strip()) < 50:
        problemes.append(
            "Le payload des sources est quasi vide (< 50 caractères utiles). "
            "Vérifiez que les fichiers/DDL ont bien été ingérés."
        )
    if payload.count("(CONTENU VIDE") == nb_sources:
        problemes.append(
            "Toutes les sources sélectionnées ont un contenu vide — "
            "relancez l'ingestion ou la sélection."
        )
    return problemes


def construire_bloc_sources(sources: list[SourceContexte]) -> str:
    """Rétrocompatibilité — délègue au compilateur explicite."""
    return compiler_contexte_sources(sources)


def construire_catalogue_sources_graph(
    sources: list[SourceContexte],
    max_apercu_chars: int = 400,
) -> str:
    """
    Catalogue léger pour la pré-analyse graphe (sans payload complet).
    Réduit les tokens d'entrée et évite que le modèle génère un nœud par ligne.
    """
    morceaux: list[str] = []
    for s in sources:
        if s.type_source == "fichier":
            origine = "Fichier local normalisé"
        else:
            origine = (
                "Base de données (DDL + échantillon anonymisé LIMIT 50)"
                if s.metadonnees.get("avec_echantillon_bdd")
                else "Base de données (DDL reverse-engineered)"
            )
        apercu = (s.echantillon_apercu or "").strip()
        if len(apercu) > max_apercu_chars:
            apercu = apercu[:max_apercu_chars] + "…"
        morceaux.append(
            f"- id={s.identifiant!r} | nom={s.nom!r} | type={s.type_source} | "
            f"origine={origine} | taille={s.taille_octets} o\n"
            f"  aperçu: {apercu or '(vide)'}"
        )
    return "\n".join(morceaux)


def prompt_systeme(
    stack: str,
    instructions: str,
    mode_hybride: bool,
    avec_echantillons_bdd: bool = False,
) -> str:
    bloc_instructions = (
        f"\n\nINSTRUCTIONS SPÉCIFIQUES DU CONSULTANT (à respecter strictement) :\n"
        f"{instructions}"
        if instructions.strip()
        else ""
    )
    consigne_hybride = ""
    if mode_hybride:
        consigne_hybride = """
CONTEXTE HYBRIDE (FICHIERS LOCAUX + BASE DE DONNÉES) :
Les sources combinent des fichiers locaux normalisés ET des structures DDL extraites
d'une base de données. Tu dois analyser les deux mondes comme un tout cohérent.
Dans la section "MATRICE DE MAPPING DE FLUX", cartographie explicitement les flux
hybrides entre fichiers et tables BDD, par exemple :
  [Base BQ : Table 'fact_orders'] JOIN [Fichier Local : 'objectifs_2026.csv']
  -> Cible [Modèle dbt / Looker / SQL]
Identifie les clés de jointure logiques entre sources hétérogènes (fichier ↔ table).
"""
    consigne_echantillons = ""
    if avec_echantillons_bdd:
        consigne_echantillons = """
ÉCHANTILLONS DE DONNÉES BASE (ANONYMISÉS LOCALEMENT) :
Pour les tables issues d'une base de données, tu as accès au schéma DDL de la table
ET à un échantillon anonymisé des 50 premières lignes (colonnes PII masquées
localement avant envoi — valeurs affichées [DONNÉE_SENSIBLE_MASQUÉE]).
Utilise cet échantillon pour comprendre les valeurs possibles des colonnes
(ex: codes statuts, formats de chaînes, cardinalités observées) afin de rendre
le dictionnaire sémantique et le code de la couche cible (Looker, dbt, Power BI)
le plus précis et proche du réel possible, sans jamais supposer le contenu
des colonnes masquées.
"""

    return f"""Tu es un Architecte Data Senior et Expert Analytics Engineering.
Tu produis un livrable de cadrage technique ultra-précis, prêt à être utilisé
directement dans Cursor ou Claude Code pour implémenter la solution.

STACK TECHNIQUE CIBLE (syntaxe obligatoire pour la section code) :
{stack}
{bloc_instructions}
{consigne_hybride}{consigne_echantillons}
{CONSIGNE_ANTI_HALLUCINATION}
EXIGENCES DE FORMAT :
- Réponds UNIQUEMENT en Markdown valide, sans préambule ni commentaire hors document.
- Sois exhaustif, structuré et actionnable pour un Analytics Engineer.
- Les noms de champs, tables et métriques doivent être déduits des sources fournies.
- La section code doit utiliser STRICTEMENT la syntaxe de la stack cible.

STRUCTURE OBLIGATOIRE DU DOCUMENT :

# LIVRABLE DE CADRAGE - ARCHITECTURE TECHNIQUE TARGET

## 1. CONTEXTE & STRATÉGIE DE MODÉLISATION
(Synthèse métier, objectifs, grain analytique, modèle recommandé star/snowflake/etc.)

## 2. DICTIONNAIRE DE DONNÉES SÉMANTIQUE
(Tableau obligatoire avec colonnes :
 Nom | Type | Description métier | Règle de calcul | Source | Sensibilité RGPD / PII)

Pour la colonne "Sensibilité RGPD / PII" :
- Taguer automatiquement chaque champ sensible (Nom, Email, Téléphone, Adresse,
  Données Financières, Identifiant personnel, etc.).
- Indiquer "Non sensible" si applicable.
- Ajouter une recommandation de masquage ou d'anonymisation pour chaque PII.

## 2.b ANALYSE DES RELATIONS ET JOINTURES (MERMAID.JS)
- Détecter les clés primaires et étrangères logiques entre tables/fichiers.
- Inclure les relations hybrides fichier ↔ base de données si applicable.
- Générer un diagramme de relations valide au format Mermaid.js dans un bloc :
```mermaid
erDiagram
  ...
```
- Le diagramme doit être syntaxiquement valide pour st.mermaid().

## 3. MATRICE DE MAPPING DE FLUX
(Tableau : Source | Champ source | Cible | Transformation | Règle métier)

OBLIGATOIRE si sources hybrides : inclure des lignes de mapping croisé, par exemple :
  [Base BQ : fact_orders.order_id] JOIN [Fichier : objectifs_2026.csv.region]
  -> [Cible : modèle analytique / KPI régional]

## 4. CODE ET CONFIGURATION "READY-TO-VIBECODE"
(Extraits de code complets et commentés, adaptés à la stack {stack})

OBLIGATOIRE dans cette section :
1. Le code principal de la stack cible (LookML, dbt YAML/SQL, DAX Power BI, SQL BigQuery...).
2. Un bloc de TESTS DE QUALITÉ DE DONNÉES adapté à la stack :
   - dbt : tests unique, not_null, accepted_values dans schema.yml
   - LookML : tests ou assertions dans les dimensions
   - Power BI : règles DAX d'alerte ou mesures de contrôle qualité
   - SQL BigQuery : contraintes CHECK ou requêtes de validation

## 5. ÉVALUATION DE LA COMPLEXITÉ ET SCOPING COMMERCIAL
- Score de complexité globale de la mission (1 à 5, avec justification).
- Liste des 3 principaux risques techniques/sémantiques identifiés
  (ex: "Clés d'unions ambiguës", "Absence de dictionnaire sur table financière")."""


def construire_contexte_mission(
    sources: list[SourceContexte],
    projet_titre: str,
    perimetre_metier: str,
    stack: str,
) -> str:
    """Contexte projet sans les données brutes (injectées via payload_sources)."""
    resume = _resume_sources_hybrides(sources)
    return f"""Génère le livrable de cadrage complet à partir des éléments suivants.

PROJET : {projet_titre}
PÉRIMÈTRE MÉTIER : {perimetre_metier}
STACK CIBLE : {stack}
MODE DE CAPTURE : {resume}
DATE DE GÉNÉRATION : {datetime.now().strftime("%Y-%m-%d %H:%M")}
NOMBRE DE SOURCES SÉLECTIONNÉES : {len(sources)}

Les données réelles (fichiers, DDL, échantillons) sont fournies dans la section
« {MARQUEUR_DEBUT_PAYLOAD} » ci-dessous. Tu DOIS t'appuyer exclusivement sur ces données."""


def prompt_utilisateur(
    sources: list[SourceContexte],
    projet_titre: str,
    perimetre_metier: str,
    stack: str,
) -> str:
    contexte_mission = construire_contexte_mission(
        sources, projet_titre, perimetre_metier, stack,
    )
    payload_sources = compiler_contexte_sources(sources)
    return f"{contexte_mission}\n\n{payload_sources}"


def est_mode_hybride(sources: list[SourceContexte]) -> bool:
    types = {s.type_source for s in sources}
    return "fichier" in types and "ddl" in types


def a_echantillons_bdd(sources: list[SourceContexte]) -> bool:
    return any(
        s.type_source == "ddl" and s.metadonnees.get("avec_echantillon_bdd")
        for s in sources
    )


def prompt_systeme_avec_graphe(
    stack: str,
    instructions: str,
    mode_hybride: bool,
    avec_echantillons_bdd: bool,
    graph_data: dict,
) -> str:
    base = prompt_systeme(stack, instructions, mode_hybride, avec_echantillons_bdd)
    graphe_json = json.dumps(graph_data, ensure_ascii=False, indent=2)
    return base + f"""

GRAPHE DE RELATIONS VALIDÉ PAR LE CONSULTANT (STRUCTURE CONTRACTUELLE) :
Le consultant a validé interactivement la mindmap suivante AVANT génération du livrable.
Tu dois transcrire FIDÈLEMENT cette structure dans le document Markdown :
- Section 2 (Dictionnaire) : refléter chaque nœud et ses métadonnées (label, group, details, kpi).
- Section 2.b (Mermaid) : reproduire les relations du graphe validé.
- Section 3 (Matrice de Mapping) : chaque arête du graphe = une ligne de mapping
  (respecter les labels de jointure et types : jointure, transformation, agrégation, mapping).
- Section 4 (Code) : implémenter la stack cible en respectant les jointures validées.

GRAPHE JSON VALIDÉ :
```json
{graphe_json}
```

Ne modifie pas la topologie du graphe sans justification explicite dans les risques (section 5).
"""


def prompt_utilisateur_avec_graphe(
    sources: list[SourceContexte],
    projet_titre: str,
    perimetre_metier: str,
    stack: str,
    graph_data: dict,
) -> str:
    contexte_mission = construire_contexte_mission(
        sources, projet_titre, perimetre_metier, stack,
    )
    payload_sources = compiler_contexte_sources(sources)
    return (
        f"{contexte_mission}\n\n"
        f"{payload_sources}\n\n"
        f"GRAPHE RELATIONS AJUSTÉ PAR LE CONSULTANT (à respecter strictement) :\n"
        f"```json\n{json.dumps(graph_data, ensure_ascii=False, indent=2)}\n```"
    )
