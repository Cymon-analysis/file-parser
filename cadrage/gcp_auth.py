"""Authentification GCP cabinet (Vertex AI / Gemini uniquement)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cadrage.config import FICHIER_GCP_CREDENTIALS_CABINET

FICHIER_GCP_CREDENTIALS = FICHIER_GCP_CREDENTIALS_CABINET

_CHAMPS_SERVICE_ACCOUNT = frozenset({"type", "project_id", "private_key", "client_email"})


def valider_service_account(data: dict[str, Any]) -> None:
    if data.get("type") != "service_account":
        raise ValueError(
            "Le fichier JSON doit être une clé de compte de service GCP "
            "(champ type = service_account)."
        )
    manquants = _CHAMPS_SERVICE_ACCOUNT - data.keys()
    if manquants:
        raise ValueError(
            f"Clé JSON invalide : champs manquants ({', '.join(sorted(manquants))})."
        )


def sauvegarder_credentials(credentials_dict: dict[str, Any]) -> Path:
    """Sauvegarde le JSON cabinet dans .secrets/gcp_credentials_cabinet.json."""
    FICHIER_GCP_CREDENTIALS_CABINET.parent.mkdir(parents=True, exist_ok=True)
    FICHIER_GCP_CREDENTIALS_CABINET.write_text(
        json.dumps(credentials_dict, indent=2),
        encoding="utf-8",
    )
    try:
        os.chmod(FICHIER_GCP_CREDENTIALS_CABINET, 0o600)
    except OSError:
        pass
    return FICHIER_GCP_CREDENTIALS_CABINET


def appliquer_credentials_env(chemin: Path | str) -> None:
    """Configure GOOGLE_APPLICATION_CREDENTIALS pour les SDK Google."""
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(Path(chemin).resolve())


def enregistrer_service_account(contenu_bytes: bytes) -> dict[str, Any]:
    """
    Valide, sauvegarde et active un compte de service GCP cabinet (Vertex AI).
    Retourne les métadonnées utiles pour session_state.
    """
    try:
        data = json.loads(contenu_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Le fichier JSON n'est pas valide.") from exc

    if not isinstance(data, dict):
        raise ValueError("Le fichier JSON doit être un objet.")

    valider_service_account(data)
    chemin = sauvegarder_credentials(data)
    appliquer_credentials_env(chemin)

    return {
        "credentials_dict": data,
        "chemin": str(chemin.resolve()),
        "project_id": str(data["project_id"]),
        "client_email": str(data["client_email"]),
    }


def restaurer_credentials_session(chemin: str | None) -> bool:
    """Réapplique GOOGLE_APPLICATION_CREDENTIALS si le fichier existe encore."""
    if not chemin:
        return False
    fichier = Path(chemin)
    if not fichier.is_file():
        return False
    appliquer_credentials_env(fichier)
    return True
