"""Authentification base de données client — isolée du LLM cabinet."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cadrage.config import FICHIER_GCP_CREDENTIALS_CLIENT_DB
from cadrage.gcp_auth import valider_service_account


def sauvegarder_credentials_client(credentials_dict: dict[str, Any]) -> Path:
    """Sauvegarde le JSON client dans .secrets/ (hors variables d'environnement globales)."""
    FICHIER_GCP_CREDENTIALS_CLIENT_DB.parent.mkdir(parents=True, exist_ok=True)
    FICHIER_GCP_CREDENTIALS_CLIENT_DB.write_text(
        json.dumps(credentials_dict, indent=2),
        encoding="utf-8",
    )
    try:
        os.chmod(FICHIER_GCP_CREDENTIALS_CLIENT_DB, 0o600)
    except OSError:
        pass
    return FICHIER_GCP_CREDENTIALS_CLIENT_DB


def enregistrer_service_account_client(contenu_bytes: bytes) -> dict[str, Any]:
    """
    Valide et sauvegarde un compte de service client pour BigQuery.
    N'altère PAS GOOGLE_APPLICATION_CREDENTIALS (réservé au LLM cabinet).
    """
    try:
        data = json.loads(contenu_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Le fichier JSON client n'est pas valide.") from exc

    if not isinstance(data, dict):
        raise ValueError("Le fichier JSON client doit être un objet.")

    valider_service_account(data)
    chemin = sauvegarder_credentials_client(data)

    return {
        "credentials_dict": data,
        "chemin": str(chemin.resolve()),
        "project_id": str(data["project_id"]),
        "client_email": str(data["client_email"]),
    }


def charger_credentials_client(chemin: str | None) -> dict[str, Any] | None:
    """Charge les credentials client depuis le disque, sans les exposer dans l'environnement."""
    if not chemin:
        return None
    fichier = Path(chemin)
    if not fichier.is_file():
        return None
    try:
        data = json.loads(fichier.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def client_db_configure(
    dialecte: str,
    *,
    credentials_dict: dict[str, Any] | None = None,
    connection_string: str = "",
) -> bool:
    """Indique si la connexion client est prête pour l'extraction DDL."""
    if dialecte == "Google BigQuery":
        return bool(credentials_dict)
    return bool(connection_string.strip())
