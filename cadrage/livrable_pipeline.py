"""Génération itérative du livrable de cadrage (section par section)."""

from __future__ import annotations

import json
from collections.abc import Callable

from google import genai

from cadrage.gemini_client import generer_section
from cadrage.models import SourceContexte
from cadrage.prompts import (
    CONSIGNE_ANTI_HALLUCINATION,
    compiler_contexte_sources,
    construire_catalogue_sources_graph,
    construire_contexte_mission,
    extraire_contenu_echantillon,
    prompt_systeme_avec_graphe,
)

CLES_SECTIONS = ("section_1", "section_2", "section_3", "section_4")


def livrable_vide() -> dict[str, str]:
    return {cle: "" for cle in CLES_SECTIONS}


def compiler_livrable_complet(livrable: dict[str, str]) -> str:
    """Fusionne les 4 sections en un document Markdown unique."""
    parties = [
        "# LIVRABLE DE CADRAGE - ARCHITECTURE TECHNIQUE TARGET",
    ]
    for cle in CLES_SECTIONS:
        contenu = (livrable.get(cle) or "").strip()
        if contenu:
            parties.append(contenu)
    return "\n\n".join(parties)


def statut_sections(livrable: dict[str, str]) -> dict[str, bool]:
    return {cle: bool((livrable.get(cle) or "").strip()) for cle in CLES_SECTIONS}


def toutes_sections_completes(livrable: dict[str, str]) -> bool:
    return all(statut_sections(livrable).values())


def _contexte_sections_precedentes(livrable: dict[str, str]) -> str:
    morceaux: list[str] = []
    for cle, titre in (
        ("section_1", "Section 1 — Contexte & Stratégie"),
        ("section_2", "Section 2 — Dictionnaire de données"),
        ("section_3", "Section 3 — Couche sémantique"),
    ):
        contenu = (livrable.get(cle) or "").strip()
        if contenu:
            morceaux.append(f"### {titre}\n{contenu[:12000]}")
    return "\n\n".join(morceaux)


def _graphe_json(graph_data: dict | None) -> str:
    if not graph_data:
        return "(aucun graphe validé)"
    return json.dumps(graph_data, ensure_ascii=False, indent=2)


def _prompt_systeme_section(
    stack: str,
    instructions: str,
    mode_hybride: bool,
    avec_echantillons_bdd: bool,
    graph_data: dict | None,
) -> str:
    if graph_data:
        return prompt_systeme_avec_graphe(
            stack, instructions, mode_hybride, avec_echantillons_bdd, graph_data,
        )
    from cadrage.prompts import prompt_systeme
    return prompt_systeme(stack, instructions, mode_hybride, avec_echantillons_bdd)


def generer_section_1_contexte(
    client: genai.Client,
    sources: list[SourceContexte],
    livrable: dict[str, str],
    *,
    projet_titre: str,
    perimetre_metier: str,
    stack: str,
    instructions: str,
    mode_hybride: bool,
    avec_echantillons_bdd: bool,
    graph_data: dict | None,
) -> str:
    prompt_sys = _prompt_systeme_section(
        stack, instructions, mode_hybride, avec_echantillons_bdd, graph_data,
    ) + """

MISSION POUR CET APPEL : génère UNIQUEMENT la section suivante du livrable, sans autre section.

## 1. CONTEXTE & STRATÉGIE DE MODÉLISATION
- Synthèse métier et objectifs
- Grain analytique recommandé
- Modèle de données cible (star, snowflake, etc.)
- Liste nominative des sources réelles analysées (noms exacts)

Réponds en Markdown. Pas de dictionnaire détaillé ni de code dans cette réponse.
"""
    catalogue = construire_catalogue_sources_graph(sources, max_apercu_chars=800)
    prompt_user = (
        f"{construire_contexte_mission(sources, projet_titre, perimetre_metier, stack)}\n\n"
        f"CATALOGUE DES SOURCES RÉELLES :\n{catalogue}\n\n"
        f"GRAPHE VALIDÉ :\n```json\n{_graphe_json(graph_data)}\n```"
    )
    return generer_section(
        client, prompt_sys, prompt_user,
        max_output_tokens=8192,
        label_debug="section_1_contexte",
    )


def generer_section_2_dictionnaire(
    client: genai.Client,
    sources: list[SourceContexte],
    livrable: dict[str, str],
    *,
    stack: str,
    instructions: str,
    mode_hybride: bool,
    avec_echantillons_bdd: bool,
    graph_data: dict | None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> str:
    """Boucle sur chaque source : un appel Gemini par table/fichier."""
    prompt_sys = _prompt_systeme_section(
        stack, instructions, mode_hybride, avec_echantillons_bdd, graph_data,
    ) + f"""

MISSION POUR CET APPEL : génère UNIQUEMENT des lignes de tableau Markdown pour le dictionnaire
de données de LA SOURCE indiquée.

Format de sortie STRICT (pas de titre de section, pas de prose) :
| Nom | Type | Description métier | Règle de calcul | Source | Sensibilité RGPD / PII |
| ... une ligne par champ/colonne réellement présent dans l'échantillon ... |

{CONSIGNE_ANTI_HALLUCINATION}
- N'invente aucune colonne absente de l'échantillon.
- Utilise les noms exacts de la source.
"""
    contexte_precedent = _contexte_sections_precedentes(livrable)
    lignes_globales: list[str] = [
        "## 2. DICTIONNAIRE DE DONNÉES SÉMANTIQUE",
        "",
        "| Nom | Type | Description métier | Règle de calcul | Source | Sensibilité RGPD / PII |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    total = len(sources)

    for index, source in enumerate(sources, start=1):
        if on_progress:
            on_progress(index, total, source.nom)

        payload_source = compiler_contexte_sources([source])
        contenu = extraire_contenu_echantillon(source)
        if not contenu.strip():
            lignes_globales.extend([
                "",
                f"### Source : {source.nom}",
                "",
                f"_Échantillon vide — source non lisible ({source.identifiant})_",
            ])
            continue

        prompt_user = (
            f"Génère les lignes du tableau Markdown du dictionnaire de données "
            f"UNIQUEMENT pour la source : **{source.nom}** "
            f"(identifiant : `{source.identifiant}`).\n\n"
            f"{payload_source}\n\n"
        )
        if contexte_precedent:
            prompt_user += f"CONTEXTE DÉJÀ VALIDÉ :\n{contexte_precedent[:6000]}\n\n"

        bloc = generer_section(
            client, prompt_sys, prompt_user,
            max_output_tokens=8192,
            label_debug=f"section_2_dictionnaire_{source.identifiant}",
        )
        lignes_table = _extraire_lignes_tableau(bloc)
        lignes_globales.extend([
            "",
            f"### Source : {source.nom}",
            "",
            *lignes_table,
        ])

    return "\n".join(lignes_globales)


def generer_section_3_code(
    client: genai.Client,
    sources: list[SourceContexte],
    livrable: dict[str, str],
    *,
    projet_titre: str,
    perimetre_metier: str,
    stack: str,
    instructions: str,
    mode_hybride: bool,
    avec_echantillons_bdd: bool,
    graph_data: dict | None,
) -> str:
    prompt_sys = _prompt_systeme_section(
        stack, instructions, mode_hybride, avec_echantillons_bdd, graph_data,
    ) + f"""

MISSION POUR CET APPEL : génère UNIQUEMENT les sections techniques suivantes :

## 4. CODE ET CONFIGURATION "READY-TO-VIBECODE"
- Code complet et commenté pour la stack : {stack}
- Tests de qualité de données adaptés (dbt schema.yml, LookML tests, DAX, SQL BQ…)

{CONSIGNE_ANTI_HALLUCINATION}
- Réutilise les noms exacts du dictionnaire validé (section 2).
"""
    prompt_user = (
        f"PROJET : {projet_titre}\nPÉRIMÈTRE : {perimetre_metier}\nSTACK : {stack}\n\n"
        f"SECTIONS DÉJÀ VALIDÉES :\n{_contexte_sections_precedentes(livrable)}\n\n"
        f"GRAPHE VALIDÉ :\n```json\n{_graphe_json(graph_data)}\n```\n\n"
        f"CATALOGUE SOURCES :\n{construire_catalogue_sources_graph(sources, max_apercu_chars=600)}"
    )
    return generer_section(
        client, prompt_sys, prompt_user,
        max_output_tokens=16384,
        label_debug="section_3_code",
    )


def generer_section_4_mapping_scoping(
    client: genai.Client,
    sources: list[SourceContexte],
    livrable: dict[str, str],
    *,
    projet_titre: str,
    perimetre_metier: str,
    stack: str,
    instructions: str,
    mode_hybride: bool,
    avec_echantillons_bdd: bool,
    graph_data: dict | None,
) -> str:
    prompt_sys = _prompt_systeme_section(
        stack, instructions, mode_hybride, avec_echantillons_bdd, graph_data,
    ) + f"""

MISSION POUR CET APPEL : génère UNIQUEMENT :

## 2.b ANALYSE DES RELATIONS ET JOINTURES (MERMAID.JS)
- Diagramme erDiagram Mermaid valide (bloc ```mermaid)

## 3. MATRICE DE MAPPING DE FLUX
- Tableau : Source | Champ source | Cible | Transformation | Règle métier
- Inclure les flux hybrides fichier ↔ BDD si applicable

## 5. ÉVALUATION DE LA COMPLEXITÉ ET SCOPING COMMERCIAL
- Score 1-5 et 3 risques techniques

{CONSIGNE_ANTI_HALLUCINATION}
"""
    prompt_user = (
        f"PROJET : {projet_titre}\nPÉRIMÈTRE : {perimetre_metier}\nSTACK : {stack}\n\n"
        f"DICTIONNAIRE VALIDÉ (extrait) :\n{(livrable.get('section_2') or '')[:20000]}\n\n"
        f"GRAPHE VALIDÉ :\n```json\n{_graphe_json(graph_data)}\n```\n\n"
        f"{compiler_contexte_sources(sources)}"
    )
    return generer_section(
        client, prompt_sys, prompt_user,
        max_output_tokens=12288,
        label_debug="section_4_mapping_scoping",
    )


def _extraire_lignes_tableau(texte: str) -> list[str]:
    """Extrait les lignes |...| d'une réponse Gemini."""
    lignes: list[str] = []
    for ligne in texte.splitlines():
        ligne_strip = ligne.strip()
        if not ligne_strip.startswith("|"):
            continue
        if ligne_strip.replace("|", "").replace("-", "").replace(" ", "") == "":
            if not lignes:
                lignes.append(ligne_strip)
            continue
        lignes.append(ligne_strip)
    if not lignes:
        return [texte.strip()] if texte.strip() else ["_Aucune ligne générée_"]
    if len(lignes) == 1:
        return lignes
    entete = lignes[0]
    separateur = lignes[1] if "---" in lignes[1] else "| --- | --- | --- | --- | --- | --- |"
    donnees = [l for l in lignes[2:] if l.startswith("|")]
    if not donnees:
        donnees = [l for l in lignes[1:] if l.startswith("|") and "---" not in l]
        return donnees or lignes
    return donnees
