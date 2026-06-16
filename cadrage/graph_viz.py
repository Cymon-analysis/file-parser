"""Rendu interactif du graphe avec streamlit-vis-network."""

from __future__ import annotations

from typing import Any

import streamlit as st

from cadrage.graph_model import (
    options_vis_network,
    preparer_aretes_vis,
    preparer_noeuds_vis,
)


def afficher_graphe_interactif(
    graph_data: dict,
    positions_sauvegardees: dict[str, dict[str, float]] | None = None,
    hauteur: int = 680,
) -> tuple[list, list, dict] | None:
    """
    Affiche le graphe vis.js interactif (zoom, drag, manipulation d'arêtes).
    Retourne (selected_nodes, selected_edges, positions) ou None.
    """
    try:
        from streamlit_vis_network import streamlit_vis_network
    except ImportError as exc:
        st.error(
            "Le composant `streamlit-vis-network` est requis. "
            "Installez-le : `pip install streamlit-vis-network`"
        )
        st.code("pip install streamlit-vis-network", language="powershell")
        raise ImportError(str(exc)) from exc

    positions = positions_sauvegardees or {}
    positions_fixes = bool(positions)
    noeuds = preparer_noeuds_vis(graph_data, positions)
    aretes = preparer_aretes_vis(graph_data)
    options = options_vis_network(positions_fixes=positions_fixes)

    if not noeuds:
        st.warning("Aucun nœud à afficher.")
        return None

    selection = streamlit_vis_network(
        noeuds,
        aretes,
        options=options,
        height=hauteur,
        key="cadrage_vis_network",
    )
    if not selection:
        return None

    selected_nodes, selected_edges, new_positions = selection
    return selected_nodes, selected_edges, new_positions or {}


def afficher_legende_couleurs() -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown("🔵 **BigQuery** — tables cloud")
    c2.markdown("🟢 **Fichiers** — sources locales")
    c3.markdown("🟠 **Métier** — concepts & cibles")
    c4.markdown("✏️ **Canvas** — tracez des jointures à la souris")
