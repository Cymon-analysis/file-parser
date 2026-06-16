"""Export du livrable Markdown vers Notion."""

from __future__ import annotations

import os
import re
from typing import Any


def _texte_riche(contenu: str) -> list[dict]:
    return [{"type": "text", "text": {"content": contenu[:2000]}}]


def _bloc_paragraphe(texte: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _texte_riche(texte)},
    }


def _bloc_titre(texte: str, niveau: int) -> dict:
    type_titre = {1: "heading_1", 2: "heading_2", 3: "heading_3"}.get(niveau, "heading_3")
    return {
        "object": "block",
        "type": type_titre,
        type_titre: {"rich_text": _texte_riche(texte)},
    }


def _bloc_code(code: str, langue: str = "plain text") -> dict:
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": _texte_riche(code[:2000]),
            "language": langue or "plain text",
        },
    }


def markdown_vers_blocs_notion(markdown: str) -> list[dict[str, Any]]:
    """Convertit un Markdown simplifié en blocs Notion."""
    blocs: list[dict[str, Any]] = []
    dans_code = False
    langue_code = ""
    buffer_code: list[str] = []
    buffer_table: list[str] = []

    def flush_table() -> None:
        nonlocal buffer_table
        if not buffer_table:
            return
        for ligne in buffer_table:
            if re.match(r"^\s*\|?[\s\-:|]+\|?\s*$", ligne):
                continue
            cellules = [c.strip() for c in ligne.strip("|").split("|")]
            blocs.append(_bloc_paragraphe(" | ".join(cellules)))
        buffer_table = []

    for ligne in markdown.splitlines():
        if ligne.strip().startswith("```"):
            if not dans_code:
                flush_table()
                dans_code = True
                langue_code = ligne.strip("`").strip() or "plain text"
                if langue_code.lower() == "mermaid":
                    langue_code = "plain text"
                buffer_code = []
            else:
                blocs.append(_bloc_code("\n".join(buffer_code), langue_code))
                dans_code = False
                buffer_code = []
            continue

        if dans_code:
            buffer_code.append(ligne)
            continue

        if ligne.strip().startswith("|"):
            buffer_table.append(ligne)
            continue
        flush_table()

        if not ligne.strip():
            continue
        if ligne.startswith("# "):
            blocs.append(_bloc_titre(ligne[2:].strip(), 1))
        elif ligne.startswith("## "):
            blocs.append(_bloc_titre(ligne[3:].strip(), 2))
        elif ligne.startswith("### "):
            blocs.append(_bloc_titre(ligne[4:].strip(), 3))
        else:
            blocs.append(_bloc_paragraphe(ligne.strip()))

    flush_table()
    if dans_code and buffer_code:
        blocs.append(_bloc_code("\n".join(buffer_code), langue_code))
    return blocs


def exporter_vers_notion(
    markdown: str,
    titre_projet: str,
    token: str | None = None,
    page_parent_id: str | None = None,
) -> str:
    """
    Crée une page Notion et y injecte le livrable.
    Retourne l'URL de la page créée.
    """
    token = token or os.environ.get("NOTION_TOKEN", "")
    page_parent_id = page_parent_id or os.environ.get("NOTION_PAGE_ID", "")

    if not token:
        raise ValueError(
            "Token Notion manquant. Définissez NOTION_TOKEN ou saisissez-le dans la barre latérale."
        )
    if not page_parent_id:
        raise ValueError(
            "ID de page parent Notion manquant. Définissez NOTION_PAGE_ID "
            "(ID de la page ou base où créer le projet)."
        )

    try:
        from notion_client import Client
    except ImportError as exc:
        raise ImportError(
            "Le paquet 'notion-client' est requis. Lancez : pip install notion-client"
        ) from exc

    notion = Client(auth=token)
    blocs = markdown_vers_blocs_notion(markdown)

    # Notion limite à 100 blocs par requête children
    premiers_blocs = blocs[:100]
    reste_blocs = blocs[100:]

    try:
        page = notion.pages.create(
            parent={"page_id": page_parent_id.strip()},
            properties={
                "title": {
                    "title": [{"text": {"content": titre_projet[:2000]}}],
                }
            },
            children=premiers_blocs,
        )
        page_id = page["id"]

        for i in range(0, len(reste_blocs), 100):
            notion.blocks.children.append(
                block_id=page_id,
                children=reste_blocs[i:i + 100],
            )

        url = page.get("url", "")
        if not url:
            url = f"https://www.notion.so/{page_id.replace('-', '')}"
        return url

    except Exception as exc:
        raise RuntimeError(
            f"Échec de l'export Notion : {exc}. "
            "Vérifiez que le token a accès à la page parent et que NOTION_PAGE_ID est valide."
        ) from exc
