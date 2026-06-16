"""Anonymisation locale des échantillons de données (RGPD)."""

from __future__ import annotations

from typing import Any

MOTS_CLES_PII = (
    "mail", "nom", "firstname", "lastname", "phone", "tel",
    "adresse", "birth", "ssn",
)
MASQUE_VALEUR = "[DONNÉE_SENSIBLE_MASQUÉE]"


def colonne_sensible(nom_colonne: str) -> bool:
    """True si le nom de colonne contient un mot-clé PII."""
    nom = nom_colonne.lower()
    return any(mot in nom for mot in MOTS_CLES_PII)


def anonymiser_echantillon(
    colonnes: list[str],
    lignes: list[list[Any]],
) -> tuple[list[list[str]], list[str]]:
    """
    Masque localement les colonnes sensibles avant envoi à l'API.
    Retourne (lignes_anonymisées, noms_colonnes_masquées).
    """
    cols_masquees = [c for c in colonnes if colonne_sensible(c)]
    if not cols_masquees:
        return [[str(v) if v is not None else "" for v in row] for row in lignes], []

    set_masque = set(cols_masquees)
    resultat: list[list[str]] = []
    for row in lignes:
        ligne: list[str] = []
        for col, val in zip(colonnes, row):
            if col in set_masque:
                ligne.append(MASQUE_VALEUR)
            else:
                ligne.append(str(val) if val is not None else "")
        resultat.append(ligne)
    return resultat, cols_masquees
