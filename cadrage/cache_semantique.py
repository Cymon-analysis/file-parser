"""Cache sémantique local basé sur hash MD5."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from cadrage.config import FICHIER_CACHE
from cadrage.models import SourceContexte
from cadrage.prompts import extraire_contenu_echantillon


def _hash_contenu(texte: str) -> str:
    return hashlib.md5(texte.encode("utf-8")).hexdigest()


def calculer_hash_cache(
    sources: list[SourceContexte],
    projet_titre: str,
    perimetre_metier: str,
    stack: str,
    instructions: str,
    graph_json: str = "",
) -> str:
    """Hash MD5 des entrées déterminant le livrable."""
    parties = [
        projet_titre.strip(),
        perimetre_metier.strip(),
        stack.strip(),
        instructions.strip(),
        graph_json.strip(),
    ]
    for source in sorted(sources, key=lambda s: s.identifiant):
        parties.extend([
            source.identifiant,
            source.type_source,
            _hash_contenu(extraire_contenu_echantillon(source) or source.contenu_payload),
        ])
    payload = "||".join(parties)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def charger_cache(chemin: Path = FICHIER_CACHE) -> dict | None:
    if not chemin.is_file():
        return None
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def sauvegarder_cache(
    hash_cles: str,
    livrable: str,
    projet_titre: str,
    chemin: Path = FICHIER_CACHE,
) -> None:
    donnees = {
        "hash": hash_cles,
        "livrable": livrable,
        "projet_titre": projet_titre,
        "generated_at": datetime.now().isoformat(),
    }
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")


def lire_livrable_cache(hash_attendu: str, chemin: Path = FICHIER_CACHE) -> str | None:
    cache = charger_cache(chemin)
    if cache and cache.get("hash") == hash_attendu:
        return cache.get("livrable")
    return None
