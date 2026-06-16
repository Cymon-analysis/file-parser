"""Moteur de désarchivage récursif et filtrage des fichiers d'ingestion."""

from __future__ import annotations

import gzip
import re
import shutil
import sys
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Extensions d'archives reconnues (ordre : composées avant simples)
SUFFIXES_ARCHIVE = (
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
    ".zip",
    ".tar",
    ".gz",
    ".rar",
    ".7z",
)

NOMS_FANTOMES_EXACTS = frozenset({
    ".ds_store",
    "desktop.ini",
    "thumbs.db",
    ".gitkeep",
    ".gitignore",
})

PREFIXES_FANTOMES = (
    "__macosx",
    "~$",
    "._",
)

DOSSIERS_FANTOMES = frozenset({
    "__macosx",
    ".git",
    "__pycache__",
    ".svn",
    "node_modules",
})


@dataclass
class FichierIngeste:
    """Fichier de données identifié après extraction et filtrage."""

    chemin: Path
    chemin_relatif: str
    extension: str
    supporte: bool
    statut: str
    message: str = ""
    profondeur: int = 0


@dataclass
class ResultatExtraction:
    """Résultat global du pipeline d'extraction locale."""

    fichiers: list[FichierIngeste] = field(default_factory=list)
    arborescence: str = ""
    archives_traitees: int = 0
    avertissements: list[str] = field(default_factory=list)


def suffixe_archive(chemin: Path) -> str | None:
    nom = chemin.name.lower()
    for suffixe in SUFFIXES_ARCHIVE:
        if nom.endswith(suffixe):
            return suffixe
    return None


def est_archive(chemin: Path) -> bool:
    return _est_fichier_accessible(chemin) and suffixe_archive(chemin) is not None


def est_fichier_fantome(chemin: Path) -> bool:
    nom = chemin.name
    nom_lower = nom.lower()

    if nom_lower in NOMS_FANTOMES_EXACTS:
        return True
    if nom.startswith("~$"):
        return True
    if nom.startswith("._"):
        return True
    if any(part.lower() in DOSSIERS_FANTOMES for part in chemin.parts):
        return True
    if "__macosx" in nom_lower:
        return True
    return False


def _chemin_windows(chemin: Path) -> Path:
    """Préfixe long-path Windows pour éviter les échecs silencieux > 260 caractères."""
    if sys.platform != "win32":
        return chemin
    texte = str(chemin.resolve())
    if texte.startswith("\\\\?\\"):
        return chemin
    return Path("\\\\?\\" + texte)


_chemin_extraction = _chemin_windows  # rétrocompatibilité interne


def _est_fichier_accessible(chemin: Path) -> bool:
    return _chemin_windows(chemin).is_file()


def _mkdir_parents(chemin: Path) -> None:
    _chemin_windows(chemin).mkdir(parents=True, exist_ok=True)


def _supprimer_arbre(chemin: Path) -> None:
    cible = _chemin_windows(chemin)
    if cible.exists():
        shutil.rmtree(cible)


def _extraire_zip(source: Path, destination: Path) -> list[str]:
    """
    Extraction ZIP tolérante : fichier par fichier, continue malgré les entrées
    problématiques (chemins longs, encodage, fichiers corrompus isolés).
    """
    avertissements: list[str] = []
    _mkdir_parents(destination)
    nb_ok = 0

    for encodage in ("utf-8", "cp437", None):
        try:
            kwargs = {"metadata_encoding": encodage} if encodage else {}
            archive = zipfile.ZipFile(source, **kwargs)
            break
        except TypeError:
            archive = zipfile.ZipFile(source)
            break
        except Exception as exc:
            if encodage is None:
                raise
            avertissements.append(f"Encodage {encodage} ignoré : {exc}")
    else:
        archive = zipfile.ZipFile(source)

    with archive:
        for membre in archive.infolist():
            try:
                nom = membre.filename.replace("\\", "/")
                if nom.endswith("/"):
                    _mkdir_parents(destination / nom)
                    nb_ok += 1
                    continue
                cible = destination / nom
                _mkdir_parents(cible.parent)
                cible_finale = _chemin_windows(cible)
                with archive.open(membre) as src, cible_finale.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                nb_ok += 1
            except Exception as exc:
                avertissements.append(f"{membre.filename} : {exc}")

    if nb_ok == 0:
        raise RuntimeError(
            f"Aucun fichier extrait de {source.name}"
            + (f" ({avertissements[0]})" if avertissements else "")
        )
    return avertissements


def _extraire_tar(source: Path, destination: Path) -> None:
    _mkdir_parents(destination)
    with tarfile.open(source, "r:*") as archive:
        for membre in archive.getmembers():
            if not membre.isfile() and not membre.isdir():
                continue
            cible = destination / membre.name.replace("\\", "/")
            if membre.isdir():
                _mkdir_parents(cible)
                continue
            _mkdir_parents(cible.parent)
            with archive.extractfile(membre) as src:
                if src is None:
                    continue
                with _chemin_windows(cible).open("wb") as dst:
                    shutil.copyfileobj(src, dst)


def _extraire_gzip(source: Path, destination: Path) -> None:
    """Décompresse un .gz simple (non tar)."""
    nom_sortie = source.name
    if nom_sortie.lower().endswith(".gz"):
        nom_sortie = nom_sortie[:-3] or f"{source.stem}_decompresse"
    cible = destination / nom_sortie
    _mkdir_parents(cible.parent)
    with gzip.open(source, "rb") as gz_in, _chemin_windows(cible).open("wb") as sortie:
        shutil.copyfileobj(gz_in, sortie)


def _extraire_7z(source: Path, destination: Path) -> None:
    try:
        import py7zr
    except ImportError as exc:
        raise ImportError(
            "Format .7z détecté : installez py7zr (`pip install py7zr`)."
        ) from exc
    with py7zr.SevenZipFile(source, "r") as archive:
        archive.extractall(destination)


def _extraire_rar(source: Path, destination: Path) -> None:
    try:
        import rarfile
    except ImportError as exc:
        raise ImportError(
            "Format .rar détecté : installez rarfile (`pip install rarfile`) "
            "et assurez-vous que UnRAR est disponible sur le système."
        ) from exc
    with rarfile.RarFile(source) as archive:
        archive.extractall(destination)


def extraire_archive_unique(source: Path, destination: Path) -> list[str]:
    """Extrait une archive vers un dossier (sans récursion). Retourne les avertissements."""
    _mkdir_parents(destination)
    suffixe = suffixe_archive(source)
    if suffixe is None:
        raise ValueError(f"Fichier non reconnu comme archive : {source.name}")

    if suffixe == ".zip":
        return _extraire_zip(source, destination)
    elif suffixe in {".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"}:
        _extraire_tar(source, destination)
    elif suffixe == ".gz":
        _extraire_gzip(source, destination)
    elif suffixe == ".7z":
        _extraire_7z(source, destination)
    elif suffixe == ".rar":
        _extraire_rar(source, destination)
    else:
        raise ValueError(f"Extension d'archive non gérée : {suffixe}")
    return []


def _dossier_extrait_pour(archive: Path) -> Path:
    return archive.parent / f"{archive.stem}_extrait"


def _archive_deja_extraite(archive: Path) -> bool:
    dossier = _dossier_extrait_pour(archive)
    if not dossier.is_dir():
        return False
    return any(
        _est_fichier_accessible(p) and not est_fichier_fantome(p)
        for p in dossier.rglob("*")
    )


def _copier_fichier(source: Path, destination: Path) -> None:
    _mkdir_parents(destination.parent)
    shutil.copy2(_chemin_windows(source), _chemin_windows(destination))


def extraire_archives_recursivement(
    dossier_source: Path,
    dossier_destination: Path,
) -> ResultatExtraction:
    """
    Désarchive récursivement toutes les archives et collecte les fichiers de données.

    Si data.zip contient sales.7z contenant export.csv, le moteur creuse jusqu'aux
    fichiers finaux non-archives.
    """
    resultat = ResultatExtraction()
    if not dossier_source.is_dir():
        resultat.avertissements.append(f"Dossier source introuvable : {dossier_source}")
        return resultat

    _mkdir_parents(dossier_destination)
    zone_travail = dossier_destination / "_workspace"
    if zone_travail.exists():
        _supprimer_arbre(zone_travail)
    _mkdir_parents(zone_travail)

    # Copie initiale de la structure source (hors archives directes)
    for chemin in sorted(dossier_source.rglob("*")):
        if not _est_fichier_accessible(chemin) or est_fichier_fantome(chemin):
            continue
        relatif = chemin.relative_to(dossier_source)
        if est_archive(chemin):
            cible = zone_travail / relatif
            _copier_fichier(chemin, cible)
        else:
            _copier_fichier(chemin, zone_travail / relatif)

    archives_traitees = 0
    boucle = True
    while boucle:
        boucle = False
        for archive in sorted(zone_travail.rglob("*")):
            if not _est_fichier_accessible(archive) or est_fichier_fantome(archive):
                continue
            if not est_archive(archive):
                continue
            dossier_extrait = _dossier_extrait_pour(archive)
            if dossier_extrait.exists():
                _supprimer_arbre(dossier_extrait)
            try:
                avertissements = extraire_archive_unique(archive, dossier_extrait)
                archives_traitees += 1
                for msg in avertissements[:10]:
                    resultat.avertissements.append(
                        f"{archive.name} : {msg}"
                    )
                if len(avertissements) > 10:
                    resultat.avertissements.append(
                        f"{archive.name} : {len(avertissements) - 10} autre(s) avertissement(s)"
                    )
                archive.unlink(missing_ok=True)
                boucle = True
            except ImportError as exc:
                resultat.avertissements.append(str(exc))
            except Exception as exc:
                deja_ok = _archive_deja_extraite(archive)
                resultat.avertissements.append(
                    f"Échec extraction {archive.relative_to(zone_travail)} : {exc}"
                )
                if deja_ok:
                    try:
                        archive.unlink(missing_ok=True)
                        archives_traitees += 1
                        boucle = True
                    except OSError:
                        pass

    fichiers_finaux: list[FichierIngeste] = []
    for chemin in sorted(zone_travail.rglob("*")):
        if not _est_fichier_accessible(chemin) or est_fichier_fantome(chemin):
            continue
        if est_archive(chemin):
            if _archive_deja_extraite(chemin):
                continue
            rel = chemin.relative_to(zone_travail)
            fichiers_finaux.append(FichierIngeste(
                chemin=chemin,
                chemin_relatif=str(rel).replace("\\", "/"),
                extension=suffixe_archive(chemin) or chemin.suffix.lower(),
                supporte=False,
                statut="archive_non_extraite",
                message="Archive non extraite (dépendance manquante ou fichier corrompu).",
                profondeur=len(rel.parts) - 1,
            ))
            continue

        rel = chemin.relative_to(zone_travail)
        rel_str = str(rel).replace("\\", "/")
        dest_finale = dossier_destination / rel
        _copier_fichier(chemin, dest_finale)
        fichiers_finaux.append(FichierIngeste(
            chemin=dest_finale,
            chemin_relatif=rel_str,
            extension=chemin.suffix.lower(),
            supporte=True,  # sera affiné par ingestion_fichiers
            statut="extrait",
            profondeur=len(rel.parts) - 1,
        ))

    try:
        _supprimer_arbre(zone_travail)
    except OSError:
        shutil.rmtree(zone_travail, ignore_errors=True)

    resultat.fichiers = fichiers_finaux
    resultat.archives_traitees = archives_traitees
    resultat.arborescence = construire_arborescence_texte(fichiers_finaux)
    return resultat


def construire_arborescence_texte(fichiers: list[FichierIngeste], max_lignes: int = 120) -> str:
    """Construit une arborescence lisible pour le consultant."""
    if not fichiers:
        return "(aucun fichier trouvé)"

    lignes = ["Arborescence des fichiers extraits :"]
    tries: dict[str, list[FichierIngeste]] = {}
    for fichier in fichiers:
        racine = fichier.chemin_relatif.split("/")[0]
        tries.setdefault(racine, []).append(fichier)

    for racine in sorted(tries):
        groupe = tries[racine]
        nb_supportes = sum(1 for f in groupe if f.supporte)
        lignes.append(f"📁 {racine}/ ({nb_supportes} fichier(s) de données)")
        for fichier in sorted(groupe, key=lambda f: f.chemin_relatif)[:max_lignes]:
            parties = fichier.chemin_relatif.split("/")
            indent = "    " * len(parties)
            nom = parties[-1]
            badge = "📄" if fichier.supporte else "⛔"
            detail = f" — {fichier.message}" if fichier.message else ""
            lignes.append(f"{indent}└── {badge} {nom}{detail}")
        reste = len(groupe) - min(len(groupe), max_lignes)
        if reste > 0:
            lignes.append(f"    … et {reste} autre(s) fichier(s) dans {racine}/")
    return "\n".join(lignes)
