"""Formatage des échantillons de données pour le contexte Gemini."""

from __future__ import annotations

import csv
import io
from typing import Any

from cadrage.anonymisation import anonymiser_echantillon
from cadrage.config import ECHANTILLON_BDD_LIGNES


def lignes_vers_csv(colonnes: list[str], lignes: list[list[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(colonnes)
    writer.writerows(lignes)
    return buffer.getvalue().strip()


def formater_echantillon_anonymise(
    colonnes: list[str],
    lignes_brutes: list[list[Any]],
) -> tuple[str, list[str]]:
    """Anonymise puis formate l'échantillon en CSV."""
    lignes_anon, cols_masquees = anonymiser_echantillon(colonnes, lignes_brutes)
    return lignes_vers_csv(colonnes, lignes_anon), cols_masquees


def assembler_contexte_table(
    ddl: str,
    echantillon_csv: str,
    colonnes_masquees: list[str],
    nb_lignes: int = ECHANTILLON_BDD_LIGNES,
) -> str:
    """Combine DDL et échantillon anonymisé en un seul bloc texte."""
    note_masque = (
        f"Colonnes masquées localement (RGPD) : {', '.join(colonnes_masquees)}"
        if colonnes_masquees
        else "Colonnes masquées localement (RGPD) : aucune"
    )
    echantillon_bloc = echantillon_csv if echantillon_csv else "(aucune ligne retournée)"
    return (
        f"## SCHÉMA DDL\n{ddl}\n\n"
        f"## ÉCHANTILLON DE DONNÉES ANONYMISÉ ({nb_lignes} premières lignes, LIMIT {nb_lignes})\n"
        f"{note_masque}\n"
        f"Format CSV :\n```csv\n{echantillon_bloc}\n```"
    )
