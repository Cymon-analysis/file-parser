"""Interface Streamlit d'édition du graphe de relations (layout 2 colonnes)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cadrage.graph_model import (
    TYPES_COLONNE,
    ajouter_noeud_personnalise,
    ajouter_relation,
    detecter_source_type,
    inferer_colonnes_noeud,
    libelle_type_source,
    modifier_noeud,
    noeud_par_id,
    supprimer_noeud,
)
from cadrage.graph_viz import afficher_graphe_interactif, afficher_legende_couleurs


def _synchroniser_selection_canvas(
    selection: tuple[list, list, dict] | None,
) -> None:
    """Met à jour current_node et les positions sans réinitialiser le graphe."""
    if not selection:
        return

    selected_nodes, _selected_edges, positions = selection

    if positions:
        st.session_state.graph_positions = {
            str(node_id): {"x": float(coords["x"]), "y": float(coords["y"])}
            for node_id, coords in positions.items()
            if isinstance(coords, dict) and "x" in coords and "y" in coords
        }

    if selected_nodes:
        node_id = str(selected_nodes[0])
        if st.session_state.get("current_node") != node_id:
            st.session_state.current_node = node_id
            st.session_state.noeud_selectionne = node_id


def _colonnes_en_dataframe(colonnes: list[dict]) -> pd.DataFrame:
    if not colonnes:
        return pd.DataFrame(columns=["nom", "type", "definition", "est_cle"])
    return pd.DataFrame(colonnes)


def _dataframe_en_colonnes(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    lignes = df.fillna("").to_dict(orient="records")
    return [
        {
            "nom": str(row.get("nom", "")).strip(),
            "type": str(row.get("type", "String")).strip() or "String",
            "definition": str(row.get("definition", "")).strip(),
            "est_cle": str(row.get("est_cle", "Aucune")).strip() or "Aucune",
        }
        for row in lignes
        if str(row.get("nom", "")).strip()
    ]


def ui_inspecteur_noeud(graph_data: dict) -> None:
    """Colonne droite : édition complète du nœud sélectionné."""
    node_id = st.session_state.get("current_node")
    if not node_id:
        st.markdown("### Inspecteur")
        st.info("Cliquez sur un nœud du graphe pour l'éditer ici.")
        st.caption(
            "Vous pouvez modifier les métadonnées métier, les colonnes, "
            "et enregistrer sans perdre la disposition du canvas."
        )
        return

    noeud = noeud_par_id(graph_data, node_id)
    if not noeud:
        st.warning("Nœud introuvable — sélectionnez un autre nœud.")
        return

    source_type = detecter_source_type(noeud)
    st.markdown("### Inspecteur de table")
    st.markdown(f"**{noeud.get('label', node_id)}**")
    st.caption(f"`{node_id}` · {libelle_type_source(source_type)}")

    if not noeud.get("colonnes"):
        colonnes_init = inferer_colonnes_noeud(
            node_id,
            st.session_state.get("sources", {}),
        )
        if colonnes_init:
            noeud = {**noeud, "colonnes": colonnes_init}

    with st.form(key=f"form_inspecteur_{node_id}", clear_on_submit=False):
        st.markdown("#### Métadonnées métier")
        label = st.text_input("Nom affiché", value=noeud.get("label", ""))
        details = st.text_area(
            "Description métier",
            value=noeud.get("details", ""),
            height=100,
        )
        kpi = st.text_input("KPIs associés", value=noeud.get("kpi", ""))

        st.markdown("#### Colonnes")
        df_colonnes = _colonnes_en_dataframe(noeud.get("colonnes", []))
        df_edite = st.data_editor(
            df_colonnes,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "nom": st.column_config.TextColumn("Nom", required=True),
                "type": st.column_config.SelectboxColumn(
                    "Type",
                    options=TYPES_COLONNE,
                    required=True,
                ),
                "definition": st.column_config.TextColumn("Définition sémantique"),
                "est_cle": st.column_config.SelectboxColumn(
                    "Est une clé",
                    options=["Aucune", "Primaire", "Étrangère"],
                    required=True,
                ),
            },
            hide_index=True,
            key=f"editor_colonnes_{node_id}",
        )

        save = st.form_submit_button(
            "Enregistrer les modifications du nœud",
            type="primary",
            use_container_width=True,
        )

    if save:
        colonnes = _dataframe_en_colonnes(df_edite)
        st.session_state.graph_data = modifier_noeud(
            st.session_state.graph_data,
            node_id,
            label=label.strip() or noeud.get("label", node_id),
            details=details,
            kpi=kpi,
            colonnes=colonnes,
        )
        st.success("Nœud mis à jour.")
        st.rerun()

    if st.button(
        "Supprimer ce nœud du modèle",
        key=f"btn_delete_node_{node_id}",
        type="secondary",
        use_container_width=True,
    ):
        st.session_state.graph_data = supprimer_noeud(st.session_state.graph_data, node_id)
        st.session_state.current_node = None
        st.session_state.noeud_selectionne = None
        if st.session_state.graph_positions:
            st.session_state.graph_positions.pop(node_id, None)
        st.warning("Nœud supprimé.")
        st.rerun()


def ui_ajout_noeud_personnalise() -> None:
    """Formulaire compact pour créer une table intermédiaire."""
    if not st.session_state.get("afficher_form_nouveau_noeud"):
        return

    with st.expander("Nouveau nœud personnalisé", expanded=True):
        label = st.text_input(
            "Nom de la table / modèle",
            placeholder="ex: fct_ventes_dbt",
            key="input_nouveau_noeud_label",
        )
        details = st.text_area(
            "Description (optionnel)",
            key="input_nouveau_noeud_details",
            height=80,
        )
        c1, c2 = st.columns(2)
        if c1.button("Créer le nœud", type="primary", key="btn_creer_noeud"):
            if not label.strip():
                st.error("Indiquez un nom pour le nœud.")
            else:
                st.session_state.graph_data = ajouter_noeud_personnalise(
                    st.session_state.graph_data,
                    label.strip(),
                    details=details,
                )
                nouveau = st.session_state.graph_data["nodes"][-1]["id"]
                st.session_state.current_node = nouveau
                st.session_state.noeud_selectionne = nouveau
                st.session_state.afficher_form_nouveau_noeud = False
                st.success(f"Nœud « {label.strip()} » ajouté.")
                st.rerun()
        if c2.button("Annuler", key="btn_annuler_noeud"):
            st.session_state.afficher_form_nouveau_noeud = False
            st.rerun()


def ui_graphe_complet() -> None:
    """Mindmap : canvas (3/4) + inspecteur dynamique (1/4)."""
    _rendu_mindmap()


@st.fragment
def _rendu_mindmap() -> None:
    graph_data = st.session_state.get("graph_data")
    if not graph_data or not graph_data.get("nodes"):
        return

    if "graph_positions" not in st.session_state:
        st.session_state.graph_positions = {}
    if "current_node" not in st.session_state:
        st.session_state.current_node = st.session_state.get("noeud_selectionne")

    afficher_legende_couleurs()

    col_canvas, col_inspecteur = st.columns([3, 1], gap="large")

    with col_canvas:
        if st.button("＋ Ajouter un nœud personnalisé", key="btn_toggle_nouveau_noeud"):
            st.session_state.afficher_form_nouveau_noeud = True
        ui_ajout_noeud_personnalise()

        selection = afficher_graphe_interactif(
            graph_data,
            positions_sauvegardees=st.session_state.graph_positions,
        )
        _synchroniser_selection_canvas(selection)

        with st.expander("Ajouter une relation manuellement (formulaire)"):
            ids = [n["id"] for n in graph_data.get("nodes", [])]
            labels = {n["id"]: n.get("label", n["id"]) for n in graph_data.get("nodes", [])}
            if len(ids) >= 2:
                c1, c2, c3 = st.columns(3)
                from_id = c1.selectbox(
                    "Source",
                    ids,
                    format_func=lambda i: labels[i],
                    key="add_edge_from",
                )
                to_id = c2.selectbox(
                    "Cible",
                    ids,
                    format_func=lambda i: labels[i],
                    key="add_edge_to",
                )
                regle = c3.text_input(
                    "Règle de jointure",
                    placeholder="id_client = client_id",
                    key="add_edge_label",
                )
                if st.button("Ajouter la relation", key="btn_add_edge_form"):
                    if from_id == to_id:
                        st.error("Choisissez deux nœuds distincts.")
                    elif not regle.strip():
                        st.error("Indiquez la règle de jointure.")
                    else:
                        st.session_state.graph_data = ajouter_relation(
                            st.session_state.graph_data,
                            from_id,
                            to_id,
                            regle.strip(),
                        )
                        st.success("Relation ajoutée.")
                        st.rerun()
            else:
                st.caption("Au moins 2 nœuds requis.")

    with col_inspecteur:
        st.markdown(
            """
            <style>
            div[data-testid="stVerticalBlock"] button[kind="secondary"] {
                border-color: #dc3545 !important;
                color: #dc3545 !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        ui_inspecteur_noeud(st.session_state.graph_data)
