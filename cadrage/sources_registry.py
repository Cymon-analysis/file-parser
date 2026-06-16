"""Registre idempotent des sources (fichiers + DDL) dans session_state."""

from __future__ import annotations

from cadrage.models import SourceContexte


def sources_dict_vide() -> dict[str, SourceContexte]:
    return {}


def cle_fichier(chemin_relatif: str) -> str:
    """Clé unique pour un fichier local normalisé."""
    return chemin_relatif


def cle_ddl(nom_table: str) -> str:
    """Clé unique pour une table extraite de la BDD."""
    return f"ddl:{nom_table}"


def integrer_fichiers(
    registre: dict[str, SourceContexte],
    nouvelles: list[SourceContexte],
    remplacer_scan: bool = True,
) -> tuple[int, int]:
    """
    Ajoute ou met à jour les fichiers locaux (sans doublon).
    Retourne (ajoutés, mis_à_jour).
    """
    ajoutes = mis_a_jour = 0
    nouvelles_cles = {s.identifiant for s in nouvelles}

    if remplacer_scan:
        for cle in list(registre.keys()):
            if registre[cle].type_source == "fichier" and cle not in nouvelles_cles:
                del registre[cle]

    for source in nouvelles:
        cle = source.identifiant
        if cle in registre:
            registre[cle] = source
            mis_a_jour += 1
        else:
            registre[cle] = source
            ajoutes += 1
    return ajoutes, mis_a_jour


def integrer_ddl(
    registre: dict[str, SourceContexte],
    nouvelles: list[SourceContexte],
    remplacer_lot: bool = True,
) -> tuple[int, int]:
    """
    Ajoute ou met à jour les tables DDL (sans doublon).
    Retourne (ajoutés, mis_à_jour).
    """
    ajoutes = mis_a_jour = 0
    nouvelles_cles = {s.identifiant for s in nouvelles}

    if remplacer_lot:
        for cle in list(registre.keys()):
            if registre[cle].type_source == "ddl" and cle not in nouvelles_cles:
                del registre[cle]

    for source in nouvelles:
        cle = source.identifiant
        if cle in registre:
            registre[cle] = source
            mis_a_jour += 1
        else:
            registre[cle] = source
            ajoutes += 1
    return ajoutes, mis_a_jour


def lister_sources(
    registre: dict[str, SourceContexte],
    type_source: str | None = None,
) -> list[SourceContexte]:
    sources = list(registre.values())
    if type_source:
        sources = [s for s in sources if s.type_source == type_source]
    return sorted(sources, key=lambda s: (s.type_source, s.nom))


def compter_sources(registre: dict[str, SourceContexte]) -> tuple[int, int]:
    fichiers = sum(1 for s in registre.values() if s.type_source == "fichier")
    ddl = sum(1 for s in registre.values() if s.type_source == "ddl")
    return fichiers, ddl
