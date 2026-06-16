"""Extraction du diagramme Mermaid depuis le livrable Markdown."""

from __future__ import annotations

import re


def extraire_diagramme_mermaid(markdown: str) -> str | None:
    """Extrait le premier bloc ```mermaid du document."""
    pattern = r"```mermaid\s*\n(.*?)```"
    match = re.search(pattern, markdown, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None
