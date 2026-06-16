"""Pré-analyse graphe via Gemini (output JSON structuré)."""

from __future__ import annotations

import json

from google import genai
from google.genai import types

from cadrage.config import MODELE_GEMINI
from cadrage.graph_model import graphe_vide, normaliser_graph_data
from cadrage.models import SourceContexte
from cadrage.prompts import construire_catalogue_sources_graph


def _schema_reponse_graphe() -> types.Schema:
    """Schéma JSON imposé à Gemini pour le graphe."""
    noeud = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "id": types.Schema(type=types.Type.STRING),
            "label": types.Schema(type=types.Type.STRING),
            "group": types.Schema(type=types.Type.STRING),
            "level": types.Schema(type=types.Type.INTEGER),
            "details": types.Schema(type=types.Type.STRING),
            "kpi": types.Schema(type=types.Type.STRING),
        },
        required=["id", "label", "group"],
    )
    arete = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "from": types.Schema(type=types.Type.STRING),
            "to": types.Schema(type=types.Type.STRING),
            "label": types.Schema(type=types.Type.STRING),
            "type": types.Schema(type=types.Type.STRING),
        },
        required=["from", "to"],
    )
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "nodes": types.Schema(type=types.Type.ARRAY, items=noeud),
            "edges": types.Schema(type=types.Type.ARRAY, items=arete),
        },
        required=["nodes", "edges"],
    )


def _prompt_preanalyse(
    sources: list[SourceContexte],
    projet_titre: str,
    perimetre_metier: str,
    stack: str,
) -> str:
    return f"""Analyse les sources de données ci-dessous et produis un graphe de relations
Tech et Métier pour un projet de cadrage Analytics Engineering.

PROJET : {projet_titre}
PÉRIMÈTRE MÉTIER : {perimetre_metier}
STACK CIBLE : {stack}

Consignes pour le graphe JSON :
- "nodes" : entités (tables BQ, fichiers CSV, KPIs métier, modèles cibles).
  * group = "Technique" pour tables/fichiers/sources techniques.
  * group = "Métier" pour concepts métier, KPIs, dimensions analytiques.
  * level = 1 (sources brutes) à 3 (modèles finaux / couche sémantique).
  * id = EXACTEMENT l'identifiant fourni dans le catalogue pour chaque source technique.
  * details = MAX 80 caractères (rôle court, pas de paragraphe).
  * kpi = KPI métier associé si pertinent (sinon chaîne vide, max 40 car.).
- "edges" : relations entre nœuds (max 30 arêtes).
  * label = règle de jointure ou flux courte (ex: "id_client = client_id").
  * type = "jointure" | "transformation" | "agrégation" | "mapping".

Identifie les jointures hybrides fichier ↔ base de données si les deux types existent.
Ajoute des nœuds métier synthétiques seulement si pertinents (max 5).
Réponds UNIQUEMENT avec le JSON conforme au schéma (nodes + edges).

CATALOGUE DES SOURCES (métadonnées + aperçu court, pas le contenu complet) :
{construire_catalogue_sources_graph(sources)}"""


def generer_graph_data(
    client: genai.Client,
    sources: list[SourceContexte],
    projet_titre: str,
    perimetre_metier: str,
    stack: str,
) -> dict:
    """
    Appel léger à Gemini 2.5 Flash pour produire le graphe initial.
    """
    if not sources:
        return graphe_vide()

    max_tokens_sortie = 16384
    config = types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=max_tokens_sortie,
        response_mime_type="application/json",
        response_schema=_schema_reponse_graphe(),
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    reponse = client.models.generate_content(
        model=MODELE_GEMINI,
        contents=_prompt_preanalyse(sources, projet_titre, perimetre_metier, stack),
        config=config,
    )
    texte = (reponse.text or "").strip()
    finish_reason = str(
        getattr(reponse, "candidates", [{}])[0].finish_reason
        if getattr(reponse, "candidates", None)
        else "N/A"
    )

    if not texte:
        raise RuntimeError("Gemini n'a renvoyé aucun JSON de graphe.")

    # Si Gemini s'est arrêté sur la limite de tokens, la réponse est souvent tronquée
    if "MAX_TOKENS" in str(finish_reason):
        raise RuntimeError(
            "La pré-analyse du graphe a été interrompue avant la fin "
            "(limite de tokens Gemini atteinte). Réduisez le nombre de sources "
            "ou la taille des fichiers avant de relancer."
        )

    try:
        brut = json.loads(texte)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "La réponse de Gemini n'est pas un JSON complet de graphe. "
            "Il est probable que la limite de tokens ait été atteinte. "
            "Réduisez le nombre de sources ou la taille des fichiers, puis relancez."
        ) from exc

    normalise = normaliser_graph_data(brut)
    if not normalise["nodes"]:
        raise RuntimeError(
            "Le graphe généré ne contient aucun nœud. "
            "Vérifiez vos sources ou relancez l'analyse."
        )
    return normalise
