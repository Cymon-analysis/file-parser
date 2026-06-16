"""Routage des fichiers extraits vers le Smart Sampling et la lecture métier."""

from __future__ import annotations

import tempfile
from pathlib import Path

from cadrage.ingestion_archives import (
    ResultatExtraction,
    _chemin_windows,
    _est_fichier_accessible,
    extraire_archives_recursivement,
)
from cadrage.models import SourceContexte
from cadrage.sampling import preparer_contenu_source

# Formats supportés pour le cadrage sémantique (aligné sur normaliser.py)
EXTENSIONS_SUPPORTEES = frozenset({
    ".xlsx", ".xlsm", ".xls",
    ".csv", ".tsv",
    ".pdf",
    ".docx",
    ".pptx",
    ".html", ".htm",
    ".txt", ".md", ".sql", ".json", ".xml", ".yaml", ".yml", ".ini", ".cfg",
    ".log", ".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".sh", ".ps1",
    ".bat", ".r", ".rb", ".php", ".go", ".rs", ".toml", ".env", ".qvs",
})

EXTENSIONS_NON_SUPPORTEES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico",
    ".exe", ".dll", ".msi", ".bin",
    ".mp4", ".mp3", ".avi", ".mov", ".wav", ".mkv",
    ".zip", ".tar", ".gz", ".rar", ".7z", ".tgz",
})

EXTENSIONS_MEDIA = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico",
    ".mp4", ".mp3", ".avi", ".mov", ".wav", ".mkv",
})

SEUIL_DETECTION_TEXTE = 0.85


def _est_probablement_texte(chemin: Path, echantillon_octets: int = 4096) -> bool:
    try:
        donnees = _chemin_windows(chemin).read_bytes()[:echantillon_octets]
    except OSError:
        return False
    if not donnees:
        return True
    try:
        donnees.decode("utf-8")
        return True
    except UnicodeDecodeError:
        pass
    caracteres_imprimables = sum(
        1 for octet in donnees if octet in (9, 10, 13) or 32 <= octet <= 126 or octet >= 128
    )
    return (caracteres_imprimables / len(donnees)) >= SEUIL_DETECTION_TEXTE


def detecter_extension_effective(chemin: Path) -> str:
    extension = chemin.suffix.lower()
    if extension:
        return extension
    if _est_probablement_texte(chemin):
        return ".txt"
    return ""


def classifier_fichier(chemin: Path) -> tuple[bool, str, str]:
    """
    Retourne (supporté, extension_effective, statut).
  statut : extrait | non_supporte | erreur_lecture
    """
    extension = detecter_extension_effective(chemin)

    if extension in EXTENSIONS_NON_SUPPORTEES:
        statut = "media_ignore" if extension in EXTENSIONS_MEDIA else "non_supporte"
        return False, extension, statut

    if extension in EXTENSIONS_SUPPORTEES:
        return True, extension, "extrait"

    if not extension and not _est_probablement_texte(chemin):
        return False, extension or "(sans extension)", "non_supporte"

    if extension == ".txt" or (not extension and _est_probablement_texte(chemin)):
        return True, ".txt", "extrait"

    # Extension inconnue mais textuelle
    if _est_probablement_texte(chemin):
        return True, ".txt", "extrait"

    return False, extension or "(inconnu)", "non_supporte"


def _lire_via_normaliseur(chemin: Path, extension: str) -> str:
    """Délègue la lecture aux convertisseurs de normaliser.py."""
    from normaliser import choisir_convertisseur, lire_texte_brut

    convertisseur, _ = choisir_convertisseur(extension)
    if convertisseur is None:
        return lire_texte_brut(chemin)

    with tempfile.TemporaryDirectory(prefix="cadrage_ingest_") as tmp:
        sorties = convertisseur(chemin, Path(tmp))
        if not sorties:
            return ""
        morceaux = []
        for sortie in sorties:
            if _chemin_windows(sortie).is_file():
                morceaux.append(
                    _chemin_windows(sortie).read_text(encoding="utf-8", errors="replace")
                )
        return "\n\n".join(morceaux)


def lire_contenu_fichier(chemin: Path, extension: str) -> str:
    try:
        return _lire_via_normaliseur(chemin, extension)
    except Exception as exc:
        raise RuntimeError(f"Lecture impossible : {exc}") from exc


def enrichir_resultat_extraction(resultat: ResultatExtraction) -> ResultatExtraction:
    """Affine le statut supporté / non supporté de chaque fichier extrait."""
    for fichier in resultat.fichiers:
        if fichier.statut == "archive_non_extraite":
            fichier.supporte = False
            fichier.message = fichier.message or "Archive non extraite."
            continue
        supporte, extension, statut = classifier_fichier(fichier.chemin)
        fichier.extension = extension
        fichier.supporte = supporte
        fichier.statut = statut
        if statut == "media_ignore":
            fichier.message = "Média ignoré (hors périmètre cadrage sémantique)"
        elif not supporte:
            fichier.message = "Non supporté pour le cadrage sémantique"

    medias = [f for f in resultat.fichiers if f.statut == "media_ignore"]
    resultat.fichiers = [f for f in resultat.fichiers if f.statut != "media_ignore"]
    if medias:
        noms = ", ".join(sorted({f.chemin.name for f in medias})[:5])
        suffixe = f" (+{len(medias) - 5} autres)" if len(medias) > 5 else ""
        resultat.avertissements.append(
            f"{len(medias)} fichier(s) média ignoré(s) : {noms}{suffixe}"
        )

    resultat.arborescence = _arborescence_avec_statuts(resultat.fichiers)
    return resultat


def _arborescence_avec_statuts(fichiers: list) -> str:
    from cadrage.ingestion_archives import construire_arborescence_texte

    return construire_arborescence_texte(fichiers)


def pipeline_ingestion_locale(
    dossier_source: Path,
    dossier_extraction: Path,
) -> ResultatExtraction:
    """Extraction récursive + classification des fichiers de données."""
    resultat = extraire_archives_recursivement(dossier_source, dossier_extraction)
    return enrichir_resultat_extraction(resultat)


def fichiers_vers_sources(
    resultat: ResultatExtraction,
    prefixe_identifiant: str = "ingest",
) -> tuple[list[SourceContexte], list[str]]:
    """Transforme les fichiers ingérés en SourceContexte pour l'application."""
    sources: list[SourceContexte] = []
    notifications: list[str] = []

    for fichier in resultat.fichiers:
        identifiant = f"{prefixe_identifiant}:{fichier.chemin_relatif}"
        supporte = fichier.supporte and fichier.statut != "archive_non_extraite"

        contenu_original = ""
        payload = ""
        apercu = ""
        applique = False
        reduction = 0.0
        notif = None

        if supporte:
            try:
                contenu_original = lire_contenu_fichier(fichier.chemin, fichier.extension)
                payload, apercu, applique, reduction, notif = preparer_contenu_source(
                    fichier.chemin.name,
                    contenu_original,
                    fichier.extension,
                )
                if notif:
                    notifications.append(notif)
            except Exception as exc:
                supporte = False
                fichier.supporte = False
                fichier.statut = "erreur_lecture"
                fichier.message = str(exc)
                apercu = f"Erreur de lecture : {exc}"
        else:
            apercu = fichier.message or "Non supporté pour le cadrage sémantique"

        sources.append(SourceContexte(
            identifiant=identifiant,
            nom=fichier.chemin.name,
            type_source="fichier",
            extension=fichier.extension,
            taille_octets=_chemin_windows(fichier.chemin).stat().st_size
                if _est_fichier_accessible(fichier.chemin) else 0,

            contenu_original=contenu_original,
            contenu_payload=payload if supporte else "",
            echantillon_apercu=apercu,
            smart_sample_applique=applique,
            reduction_pct=reduction,
            metadonnees={
                "supporte": supporte,
                "statut_ingestion": fichier.statut,
                "chemin_relatif": fichier.chemin_relatif,
                "profondeur": fichier.profondeur,
                "message": fichier.message,
            },
        ))

    return sources, notifications


def scanner_dossier_avec_ingestion(
    dossier_brut: Path,
    dossier_extraction: Path,
) -> tuple[list[SourceContexte], list[str], ResultatExtraction]:
    """Pipeline complet : archives imbriquées → sources Streamlit."""
    resultat = pipeline_ingestion_locale(dossier_brut, dossier_extraction)
    sources, notifications = fichiers_vers_sources(resultat)
    return sources, notifications, resultat
