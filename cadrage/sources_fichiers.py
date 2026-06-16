"""Scan des fichiers normalisés locaux et ingestion depuis sources brutes."""

from __future__ import annotations

from pathlib import Path

from cadrage.ingestion_archives import ResultatExtraction
from cadrage.ingestion_fichiers import scanner_dossier_avec_ingestion
from cadrage.models import SourceContexte, sanitiser_metadonnees
from cadrage.sampling import preparer_contenu_source


def scanner_dossier(dossier: Path) -> tuple[list[SourceContexte], list[str]]:
    """
    Parcourt le dossier normalisé et retourne (sources, notifications_sampling).
    """
    if not dossier.is_dir():
        return [], []

    sources: list[SourceContexte] = []
    notifications: list[str] = []

    for chemin in sorted(dossier.rglob("*")):
        if not chemin.is_file() or chemin.name == "_MANIFEST.csv":
            continue
        try:
            contenu = chemin.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        extension = chemin.suffix.lower()
        relatif = str(chemin.relative_to(dossier)).replace("\\", "/")
        payload, apercu, applique, reduction, notif = preparer_contenu_source(
            chemin.name, contenu, extension,
        )
        if notif:
            notifications.append(notif)

        sources.append(SourceContexte(
            identifiant=relatif,
            nom=chemin.name,
            type_source="fichier",
            extension=extension,
            taille_octets=chemin.stat().st_size,
            contenu_original=contenu,
            contenu_payload=payload,
            echantillon_apercu=apercu,
            smart_sample_applique=applique,
            reduction_pct=reduction,
            metadonnees={"supporte": True, "statut_ingestion": "normalise"},
        ))
    return sources, notifications


def ingerer_dossier_brut(
    dossier_brut: Path,
    dossier_extraction: Path,
) -> tuple[list[SourceContexte], list[str], ResultatExtraction]:
    """Ingestion universelle : archives imbriquées + smart sampling."""
    return scanner_dossier_avec_ingestion(dossier_brut, dossier_extraction)


def sources_depuis_ddl(
    schemas: dict[str, str],
) -> tuple[list[SourceContexte], list[str]]:
    """Transforme les contextes DDL+échantillon en sources de contexte."""
    sources: list[SourceContexte] = []
    notifications: list[str] = []

    for nom_table, contenu in sorted(schemas.items()):
        payload, apercu, applique, reduction, notif = preparer_contenu_source(
            nom_table, contenu, ".sql",
        )
        if notif:
            notifications.append(notif)

        sources.append(SourceContexte(
            identifiant=f"ddl:{nom_table}",
            nom=nom_table,
            type_source="ddl",
            extension=".sql",
            taille_octets=len(contenu.encode("utf-8")),
            contenu_original=contenu,
            contenu_payload=payload,
            echantillon_apercu=apercu,
            smart_sample_applique=applique,
            reduction_pct=reduction,
            metadonnees=sanitiser_metadonnees({
                "table": nom_table,
                "avec_echantillon_bdd": True,
                "origine": "extraction_ddl_client",
            }),
        ))
    return sources, notifications
