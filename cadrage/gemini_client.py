"""Intégration API Gemini."""

from __future__ import annotations

from pathlib import Path

from google import genai
from google.genai import types

from cadrage.config import MODELE_GEMINI, PRIX_ENTREE_PAR_MILLION, PRIX_SORTIE_PAR_MILLION, TOKENS_SORTIE_MAX_ESTIMES, VERTEX_AI_LOCATION

FICHIER_DEBUG_PROMPT = Path("debug_prompt.txt")


def obtenir_client(
    cle_api: str | None = None,
    *,
    project_gcp: str | None = None,
    location: str = VERTEX_AI_LOCATION,
) -> genai.Client:
    """
    Client Gemini : Vertex AI si un projet GCP est configuré, sinon clé API.
    """
    if project_gcp:
        return genai.Client(vertexai=True, project=project_gcp, location=location)
    if cle_api:
        return genai.Client(api_key=cle_api)
    raise ValueError(
        "Authentification requise : téléversez un compte de service GCP "
        "dans la barre latérale ou saisissez une clé API Gemini."
    )


def compter_tokens(client: genai.Client, texte: str) -> int:
    reponse = client.models.count_tokens(model=MODELE_GEMINI, contents=texte)
    return reponse.total_tokens


def estimer_cout_max_usd(tokens_entree: int) -> float:
    cout_entree = (tokens_entree / 1_000_000) * PRIX_ENTREE_PAR_MILLION
    cout_sortie = (TOKENS_SORTIE_MAX_ESTIMES / 1_000_000) * PRIX_SORTIE_PAR_MILLION
    return cout_entree + cout_sortie


def generer_livrable(
    client: genai.Client,
    prompt_sys: str,
    prompt_user: str,
    *,
    payload_sources: str | None = None,
    max_output_tokens: int = 16384,
) -> str:
    """
    Génère le livrable via Gemini (appel monolithique — préférer livrable_pipeline).
    """
    return generer_section(
        client,
        prompt_sys,
        prompt_user,
        payload_sources=payload_sources,
        max_output_tokens=max_output_tokens,
        label_debug="livrable_monolithique",
    )


def generer_section(
    client: genai.Client,
    prompt_sys: str,
    prompt_user: str,
    *,
    payload_sources: str | None = None,
    max_output_tokens: int = 8192,
    label_debug: str = "section",
) -> str:
    """Appel Gemini ciblé pour une section du livrable."""
    if payload_sources is not None:
        print(f"[cadrage:{label_debug}] payload_sources ({len(payload_sources)} car.)")
        try:
            FICHIER_DEBUG_PROMPT.write_text(
                "\n".join([
                    f"=== {label_debug.upper()} ===",
                    "",
                    "=" * 72,
                    "PROMPT SYSTÈME",
                    "=" * 72,
                    prompt_sys,
                    "",
                    "=" * 72,
                    "PROMPT USER",
                    "=" * 72,
                    prompt_user,
                    "",
                    "=" * 72,
                    "PAYLOAD SOURCES",
                    "=" * 72,
                    payload_sources,
                ]),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[cadrage] Impossible d'écrire {FICHIER_DEBUG_PROMPT} : {exc}")

    config = types.GenerateContentConfig(
        system_instruction=prompt_sys,
        temperature=0.2,
        max_output_tokens=max_output_tokens,
    )
    reponse = client.models.generate_content(
        model=MODELE_GEMINI,
        contents=prompt_user,
        config=config,
    )
    if not reponse.text:
        raise RuntimeError(f"Gemini n'a renvoyé aucun contenu pour {label_debug}.")
    return reponse.text.strip()
