"""Smart Sampling FinOps — échantillonnage structuré préservant le contexte métier."""

from __future__ import annotations

import re

from cadrage.config import (
    LIGNES_DEBUT_TABULAIRE,
    LIGNES_DEBUT_TEXTE,
    LIGNES_FIN_TABULAIRE,
    LIGNES_FIN_TEXTE,
    LIGNES_ECHANTILLON_CSV,
    LIGNES_SMART_SAMPLE,
    SEUIL_SMART_SAMPLING,
)

EXTENSIONS_TABULAIRES = frozenset({
    ".csv", ".tsv",
    ".xlsx", ".xls", ".xlsm",
    ".sql",
})

MARQUEUR_FEUILLE = re.compile(r"^>>> FEUILLE : (.+)$", re.MULTILINE)
MARQUEUR_FICHIER_ZIP = re.compile(r"^>>> FICHIER : (.+)$", re.MULTILINE)


def formater_taille(octets: int) -> str:
    if octets < 1024:
        return f"{octets} o"
    if octets < 1024 * 1024:
        return f"{octets / 1024:.1f} Ko"
    return f"{octets / (1024 * 1024):.2f} Mo"


def _calculer_reduction(contenu_original: str, payload: str) -> float:
    taille_orig = len(contenu_original.encode("utf-8"))
    taille_payload = len(payload.encode("utf-8"))
    if not taille_orig:
        return 0.0
    return round(max(0.0, (1 - taille_payload / taille_orig) * 100), 1)


def _lignes_completes(contenu: str) -> list[str]:
    """Découpe en lignes entières sans couper au milieu d'une ligne."""
    return contenu.splitlines()


def _est_extension_tabulaire(extension: str) -> bool:
    return extension.lower() in EXTENSIONS_TABULAIRES


def _ressemble_a_entete_csv(ligne: str) -> bool:
    ligne = ligne.strip()
    if not ligne or ligne.startswith("#") or ligne.startswith("--"):
        return False
    if ligne.count(",") >= 1:
        return True
    if ligne.count(";") >= 1:
        return True
    if "\t" in ligne:
        return True
    if "|" in ligne and ligne.count("|") >= 2:
        return True
    return False


def _ressemble_a_donnees_tabulaires(lignes: list[str]) -> bool:
    """Heuristique : au moins 3 lignes de données avec structure régulière."""
    if len(lignes) < 4:
        return False
    entete = lignes[0].strip()
    if not _ressemble_a_entete_csv(entete):
        return False
    donnees = [l for l in lignes[1:] if l.strip() and not l.strip().startswith("--")]
    if len(donnees) < 2:
        return False
    sep = max([",", ";", "\t", "|"], key=lambda s: entete.count(s))
    if entete.count(sep) == 0:
        return False
    nb_col_entete = entete.count(sep) + 1
    lignes_ok = sum(
        1 for ligne in donnees[:20]
        if abs((ligne.count(sep) + 1) - nb_col_entete) <= 1
    )
    return lignes_ok >= min(2, len(donnees))


def _identifier_entete_et_donnees(lignes: list[str]) -> tuple[str, list[str]]:
    """
    Identifie la ligne d'en-tête et les lignes de données (lignes complètes).
    Ignore les lignes vides et commentaires SQL en tête du bloc.
    """
    lignes_utiles = [l for l in lignes if l.strip()]
    if not lignes_utiles:
        return "", []

    if _ressemble_a_donnees_tabulaires(lignes_utiles):
        return lignes_utiles[0], lignes_utiles[1:]

    # SQL / fichiers mixtes : chercher la première ligne type header CSV
    for index, ligne in enumerate(lignes_utiles):
        if _ressemble_a_entete_csv(ligne):
            suivantes = lignes_utiles[index + 1:]
            if suivantes and _ressemble_a_donnees_tabulaires([ligne, *suivantes[:5]]):
                return ligne, suivantes
    return lignes_utiles[0], lignes_utiles[1:]


def _decouper_blocs_tabulaires(contenu: str) -> list[tuple[str, list[str]]]:
    """
    Découpe le contenu en blocs (feuilles Excel, fichiers ZIP consolidés, bloc unique).
    Retourne [(titre_bloc, lignes_complètes), ...].
    """
    if MARQUEUR_FEUILLE.search(contenu) or MARQUEUR_FICHIER_ZIP.search(contenu):
        blocs: list[tuple[str, list[str]]] = []
        morceaux = re.split(r"\n(?=>>> (?:FEUILLE|FICHIER) : )", contenu)
        for morceau in morceaux:
            morceau = morceau.strip()
            if not morceau:
                continue
            premiere = morceau.splitlines()[0] if morceau else ""
            match = re.match(r">>> (?:FEUILLE|FICHIER) : (.+)", premiere)
            titre = match.group(1).strip() if match else "Bloc"
            corps_lignes = morceau.splitlines()[1:] if match else morceau.splitlines()
            blocs.append((titre, corps_lignes))
        return blocs or [("", _lignes_completes(contenu))]

    return [("", _lignes_completes(contenu))]


def _construire_bloc_csv_echantillon(
    entete: str,
    lignes_donnees: list[str],
    nb_debut: int = LIGNES_DEBUT_TABULAIRE,
    nb_fin: int = LIGNES_FIN_TABULAIRE,
) -> str:
    """Reconstruit un bloc CSV avec header + début + marqueur + fin (lignes entières)."""
    lignes_donnees = [l for l in lignes_donnees if l.strip()]
    total = len(lignes_donnees)

    if total == 0:
        return entete

    if total <= nb_debut + nb_fin:
        return "\n".join([entete, *lignes_donnees])

    debut = lignes_donnees[:nb_debut]
    fin = lignes_donnees[-nb_fin:]
    omises = total - nb_debut - nb_fin
    return "\n".join([
        entete,
        *debut,
        f"... [LIGNES INTERMÉDIAIRES IDENTIQUES TRONQUÉES — {omises} ligne(s) omise(s)] ...",
        *fin,
    ])


def _encapsuler_echantillon_tabulaire(
    nom_fichier: str,
    corps_csv: str,
    sous_titre: str = "",
) -> str:
    titre = nom_fichier if not sous_titre else f"{nom_fichier} — {sous_titre}"
    return (
        "---\n"
        f"DEBUT DU FICHIER: {titre}\n"
        "TYPE: Structure Tabulaire\n"
        "NOTE: Ce fichier a été échantillonné pour optimiser le contexte. "
        "Seules les lignes initiales et finales sont présentées ci-dessous. "
        "La structure des colonnes est identique sur tout le fichier.\n\n"
        "```csv\n"
        f"{corps_csv.strip()}\n"
        "```\n"
        "---"
    )


def smart_sample_tabulaire(
    nom_fichier: str,
    contenu: str,
    extension: str,
) -> tuple[str, float]:
    """
    Échantillonnage structuré pour CSV, Excel (multi-feuilles) et SQL tabulaire.
    30 premières lignes de données + 10 dernières, header toujours préservé.
    """
    blocs = _decouper_blocs_tabulaires(contenu)
    sections_echantillon: list[str] = []

    for titre_bloc, lignes_bloc in blocs:
        entete, donnees = _identifier_entete_et_donnees(lignes_bloc)
        if not entete and not donnees:
            continue
        corps = _construire_bloc_csv_echantillon(entete, donnees)
        sections_echantillon.append(
            _encapsuler_echantillon_tabulaire(nom_fichier, corps, sous_titre=titre_bloc)
        )

    if not sections_echantillon:
        return smart_sample_texte(nom_fichier, contenu)

    payload = "\n\n".join(sections_echantillon)
    return payload, _calculer_reduction(contenu, payload)


def smart_sample_texte(nom_fichier: str, contenu: str) -> tuple[str, float]:
    """
    Échantillonnage texte : lignes complètes du début et de la fin uniquement
    (pas de coupe au milieu d'une ligne, pas d'échantillon du milieu ambigu).
    """
    lignes = _lignes_completes(contenu)
    total = len(lignes)
    if total == 0:
        return contenu, 0.0

    if total <= LIGNES_DEBUT_TEXTE + LIGNES_FIN_TEXTE:
        return contenu, 0.0

    debut = lignes[:LIGNES_DEBUT_TEXTE]
    fin = lignes[-LIGNES_FIN_TEXTE:]
    omises = total - LIGNES_DEBUT_TEXTE - LIGNES_FIN_TEXTE
    morceaux = [
        "---",
        f"DEBUT DU FICHIER: {nom_fichier}",
        "TYPE: Texte / Code",
        "NOTE: Fichier échantillonné — lignes initiales et finales uniquement. "
        "Le contenu omis au milieu suit la même structure.",
        "",
        *debut,
        "",
        f"... [CONTENU INTERMÉDIAIRE TRONQUÉ — {omises} ligne(s) omise(s)] ...",
        "",
        *fin,
        "---",
    ]
    payload = "\n".join(morceaux)
    return payload, _calculer_reduction(contenu, payload)


def smart_sample_lignes(contenu: str, n: int = LIGNES_SMART_SAMPLE) -> tuple[str, float]:
    """Alias rétrocompatible — délègue au sampling texte structuré."""
    return smart_sample_texte("document", contenu)


def _choisir_strategie_sampling(
    nom: str,
    contenu: str,
    extension: str,
) -> tuple[str, float]:
    ext = extension.lower()
    if _est_extension_tabulaire(ext):
        if ext in {".csv", ".tsv"}:
            return smart_sample_tabulaire(nom, contenu, ext)
        if ext in {".xlsx", ".xls", ".xlsm"}:
            return smart_sample_tabulaire(nom, contenu, ext)
        if ext == ".sql":
            lignes = _lignes_completes(contenu)
            if _ressemble_a_donnees_tabulaires(lignes):
                return smart_sample_tabulaire(nom, contenu, ext)
    # Contenu multi-feuilles normalisé (.txt) avec blocs CSV
    if ">>> FEUILLE :" in contenu or ">>> FICHIER :" in contenu:
        return smart_sample_tabulaire(nom, contenu, extension)
    if _ressemble_a_donnees_tabulaires(_lignes_completes(contenu)):
        return smart_sample_tabulaire(nom, contenu, extension)
    return smart_sample_texte(nom, contenu)


def appliquer_smart_sampling(
    nom: str,
    contenu: str,
    extension: str,
    taille_octets: int,
) -> tuple[str, bool, float, str | None]:
    """
    Applique le smart sampling si taille > seuil.
    Retourne (payload, appliqué, reduction_pct, message_notification).
    """
    if taille_octets <= SEUIL_SMART_SAMPLING:
        return contenu, False, 0.0, None

    payload, reduction = _choisir_strategie_sampling(nom, contenu, extension)
    if payload == contenu:
        return contenu, False, 0.0, None

    type_echantillon = (
        "structure tabulaire préservée (header + 30 premières / 10 dernières lignes)"
        if "Structure Tabulaire" in payload
        else "lignes complètes début/fin"
    )
    message = (
        f"⚡ Smart Sampling appliqué sur {nom} "
        f"({type_echantillon}, −{reduction:.0f}% tokens)"
    )
    return payload, True, reduction, message


def extraire_echantillon_apercu(contenu: str, extension: str) -> str:
    from cadrage.config import CARACTERES_ECHANTILLON_TEXTE

    if extension == ".csv" or "Structure Tabulaire" in contenu:
        lignes = contenu.splitlines()
        return "\n".join(lignes[: max(LIGNES_ECHANTILLON_CSV, 15)])
    return contenu[:CARACTERES_ECHANTILLON_TEXTE]


def preparer_contenu_source(
    nom: str,
    contenu: str,
    extension: str,
) -> tuple[str, str, bool, float, str | None]:
    """Prépare contenu payload + aperçu + métadonnées sampling."""
    taille = len(contenu.encode("utf-8"))
    payload, applique, reduction, notif = appliquer_smart_sampling(
        nom, contenu, extension, taille,
    )
    apercu = extraire_echantillon_apercu(payload, extension)
    return payload, apercu, applique, reduction, notif
