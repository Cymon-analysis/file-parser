"""Modèles de données partagés."""

from __future__ import annotations

from dataclasses import dataclass, field

from cadrage.config import CLES_METADONNEES_INTERDITES


def sanitiser_metadonnees(metadonnees: dict) -> dict:
    """Retire toute clé sensible avant affichage ou envoi au LLM."""
    return {
        cle: valeur
        for cle, valeur in metadonnees.items()
        if cle.lower() not in CLES_METADONNEES_INTERDITES
        and not any(interdit in cle.lower() for interdit in ("password", "secret", "token", "credential"))
    }


@dataclass
class SourceContexte:
    """Source de contexte (fichier local ou schéma DDL extrait)."""

    identifiant: str
    nom: str
    type_source: str  # "fichier" | "ddl"
    extension: str
    taille_octets: int
    contenu_original: str
    contenu_payload: str
    echantillon_apercu: str
    smart_sample_applique: bool = False
    reduction_pct: float = 0.0
    metadonnees: dict = field(default_factory=dict)

    @property
    def contenu(self) -> str:
        """Alias rétrocompatible."""
        return self.contenu_payload
