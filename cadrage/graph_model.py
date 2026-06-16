"""Modèle et opérations CRUD sur le graphe de relations."""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from typing import Any

from cadrage.models import SourceContexte

# Couleurs par origine de nœud (canvas)
COULEURS_ORIGINE: dict[str, dict[str, Any]] = {
    "bigquery": {
        "background": "#2E86AB",
        "border": "#1B4F72",
        "highlight": {"background": "#5DADE2", "border": "#2E86AB"},
        "font": {"color": "#ffffff"},
    },
    "fichier": {
        "background": "#28A745",
        "border": "#1E5631",
        "highlight": {"background": "#58D68D", "border": "#28A745"},
        "font": {"color": "#ffffff"},
    },
    "metier": {
        "background": "#E67E22",
        "border": "#CA6F1E",
        "highlight": {"background": "#F5B041", "border": "#E67E22"},
        "font": {"color": "#ffffff"},
    },
    "custom": {
        "background": "#E67E22",
        "border": "#CA6F1E",
        "highlight": {"background": "#F5B041", "border": "#E67E22"},
        "font": {"color": "#ffffff"},
    },
}
COULEUR_DEFAUT = COULEURS_ORIGINE["metier"]

TYPES_COLONNE = [
    "String",
    "Integer",
    "Float",
    "Boolean",
    "Timestamp",
    "Date",
    "Numeric",
    "JSON",
    "Autre",
]

OPTIONS_CLE = ["Aucune", "Primaire", "Étrangère"]


def graphe_vide() -> dict[str, list]:
    return {"nodes": [], "edges": []}


def _slug(texte: str) -> str:
    normalise = unicodedata.normalize("NFKD", texte)
    ascii_only = normalise.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "_", ascii_only).strip("_").lower() or "noeud"


def detecter_source_type(noeud: dict[str, Any]) -> str:
    if noeud.get("source_type"):
        return str(noeud["source_type"])
    node_id = str(noeud.get("id", ""))
    group = str(noeud.get("group", ""))
    if group in ("Métier", "Metier"):
        return "metier"
    if node_id.startswith("ddl:") or node_id.startswith("custom_"):
        if node_id.startswith("custom_"):
            return "custom"
        return "bigquery"
    if "." in node_id and not node_id.endswith((".txt", ".csv", ".sql")):
        return "bigquery"
    return "fichier"


def libelle_type_source(source_type: str) -> str:
    return {
        "bigquery": "BigQuery",
        "fichier": "Fichier local",
        "metier": "Nœud métier",
        "custom": "Table personnalisée",
    }.get(source_type, source_type)


def _normaliser_colonnes(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    colonnes: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        est_cle = item.get("est_cle", "Aucune")
        if isinstance(est_cle, bool):
            est_cle = "Primaire" if est_cle else "Aucune"
        colonnes.append({
            "nom": str(item.get("nom", "")),
            "type": str(item.get("type", "String")),
            "definition": str(item.get("definition", "")),
            "est_cle": est_cle if est_cle in OPTIONS_CLE else "Aucune",
        })
    return colonnes


def _mapper_type_sql(type_sql: str) -> str:
    t = type_sql.upper()
    if "INT" in t:
        return "Integer"
    if "FLOAT" in t or "DOUBLE" in t or "NUMERIC" in t or "DECIMAL" in t:
        return "Float"
    if "BOOL" in t:
        return "Boolean"
    if "TIMESTAMP" in t or "DATETIME" in t:
        return "Timestamp"
    if t == "DATE":
        return "Date"
    if "JSON" in t:
        return "JSON"
    return "String"


def parser_colonnes_ddl(contenu: str) -> list[dict[str, Any]]:
    colonnes: list[dict[str, Any]] = []
    in_create = False
    for line in contenu.splitlines():
        ligne = line.strip()
        if ligne.upper().startswith("CREATE TABLE"):
            in_create = True
            continue
        if not in_create:
            continue
        if ligne.startswith(");") or ligne == ");":
            break
        if ligne.startswith("--") or not ligne:
            continue
        match = re.match(r"[`\"]?(\w+)[`\"]?\s+(\w+)", ligne.rstrip(","))
        if not match:
            continue
        nom = match.group(1)
        colonnes.append({
            "nom": nom,
            "type": _mapper_type_sql(match.group(2)),
            "definition": "",
            "est_cle": "Primaire" if nom.lower() in ("id", "pk") or nom.lower().endswith("_id") else "Aucune",
        })
    return colonnes


def parser_colonnes_fichier(contenu: str) -> list[dict[str, Any]]:
    for line in contenu.splitlines():
        ligne = line.strip()
        if not ligne or ligne.startswith(">>>") or ligne.startswith("#"):
            continue
        sep = ";" if ";" in ligne else ","
        entetes = [c.strip().strip('"').strip("'") for c in ligne.split(sep)]
        return [
            {
                "nom": h,
                "type": "String",
                "definition": "",
                "est_cle": "Primaire" if h.lower() == "id" or h.lower().endswith("_id") else "Aucune",
            }
            for h in entetes if h
        ]
    return []


def inferer_colonnes_noeud(
    node_id: str,
    sources: dict[str, SourceContexte],
) -> list[dict[str, Any]]:
    source = sources.get(node_id)
    if not source:
        return []
    contenu = source.contenu_payload or source.contenu_original or ""
    if source.type_source == "ddl":
        return parser_colonnes_ddl(contenu)
    return parser_colonnes_fichier(contenu)


def normaliser_graph_data(data: dict[str, Any]) -> dict[str, list]:
    """Valide et normalise la structure du graphe."""
    nodes_raw = data.get("nodes") or []
    edges_raw = data.get("edges") or []

    nodes: list[dict[str, Any]] = []
    for i, n in enumerate(nodes_raw):
        if not isinstance(n, dict):
            continue
        node_id = str(n.get("id", i + 1))
        source_type = detecter_source_type({**n, "id": node_id})
        nodes.append({
            "id": node_id,
            "label": str(n.get("label", f"Nœud {node_id}")),
            "group": str(n.get("group", "Technique")),
            "source_type": source_type,
            "level": int(n.get("level", 1)),
            "details": str(n.get("details", "")),
            "kpi": str(n.get("kpi", "")),
            "colonnes": _normaliser_colonnes(n.get("colonnes")),
        })

    ids_valides = {n["id"] for n in nodes}
    edges: list[dict[str, Any]] = []
    for i, e in enumerate(edges_raw):
        if not isinstance(e, dict):
            continue
        from_id = str(e.get("from", ""))
        to_id = str(e.get("to", ""))
        if from_id not in ids_valides or to_id not in ids_valides:
            continue
        edges.append({
            "id": str(e.get("id", f"edge_{from_id}_{to_id}_{i}")),
            "from": from_id,
            "to": to_id,
            "label": str(e.get("label", "")),
            "type": str(e.get("type", "jointure")),
        })
    return {"nodes": nodes, "edges": edges}


def noeud_par_id(graph_data: dict, node_id: str) -> dict[str, Any] | None:
    for n in graph_data.get("nodes", []):
        if n["id"] == node_id:
            return n
    return None


def ajouter_relation(
    graph_data: dict,
    from_id: str,
    to_id: str,
    label: str,
    type_relation: str = "jointure",
) -> dict:
    g = copy.deepcopy(graph_data)
    if not noeud_par_id(g, from_id) or not noeud_par_id(g, to_id):
        raise ValueError("Les deux nœuds doivent exister dans le graphe.")
    edge_id = f"edge_{from_id}_{to_id}_{len(g['edges'])}"
    g["edges"].append({
        "id": edge_id,
        "from": from_id,
        "to": to_id,
        "label": label,
        "type": type_relation,
    })
    return g


def supprimer_relation(graph_data: dict, edge_id: str) -> dict:
    g = copy.deepcopy(graph_data)
    g["edges"] = [e for e in g["edges"] if e.get("id") != edge_id]
    return g


def modifier_noeud(
    graph_data: dict,
    node_id: str,
    label: str | None = None,
    group: str | None = None,
    details: str | None = None,
    kpi: str | None = None,
    level: int | None = None,
    source_type: str | None = None,
    colonnes: list[dict[str, Any]] | None = None,
) -> dict:
    g = copy.deepcopy(graph_data)
    for n in g["nodes"]:
        if n["id"] == node_id:
            if label is not None:
                n["label"] = label
            if group is not None:
                n["group"] = group
            if details is not None:
                n["details"] = details
            if kpi is not None:
                n["kpi"] = kpi
            if level is not None:
                n["level"] = level
            if source_type is not None:
                n["source_type"] = source_type
            if colonnes is not None:
                n["colonnes"] = _normaliser_colonnes(colonnes)
            break
    return g


def ajouter_noeud_personnalise(
    graph_data: dict,
    label: str,
    *,
    details: str = "",
    kpi: str = "",
    group: str = "Métier",
) -> dict:
    g = copy.deepcopy(graph_data)
    base_id = f"custom_{_slug(label)}"
    node_id = base_id
    compteur = 1
    ids_existants = {n["id"] for n in g["nodes"]}
    while node_id in ids_existants:
        compteur += 1
        node_id = f"{base_id}_{compteur}"
    g["nodes"].append({
        "id": node_id,
        "label": label.strip() or "Nouveau nœud",
        "group": group,
        "source_type": "custom",
        "level": 2,
        "details": details,
        "kpi": kpi,
        "colonnes": [],
    })
    return g


def supprimer_noeud(graph_data: dict, node_id: str) -> dict:
    g = copy.deepcopy(graph_data)
    g["nodes"] = [n for n in g["nodes"] if n["id"] != node_id]
    g["edges"] = [
        e for e in g["edges"]
        if e.get("from") != node_id and e.get("to") != node_id
    ]
    return g


def preparer_noeuds_vis(
    graph_data: dict,
    positions: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """Convertit les nœuds pour streamlit-vis-network / vis.js."""
    positions = positions or {}
    noeuds = []
    for n in graph_data.get("nodes", []):
        source_type = detecter_source_type(n)
        couleur = COULEURS_ORIGINE.get(source_type, COULEUR_DEFAUT)
        node_id = str(n["id"])
        titre = n.get("details", "") or ""
        if n.get("kpi"):
            titre += f"\nKPI : {n['kpi']}" if titre else f"KPI : {n['kpi']}"

        vis_node: dict[str, Any] = {
            "id": node_id,
            "label": n.get("label", node_id),
            "group": source_type,
            "title": titre or n.get("label", node_id),
            "color": couleur,
            "shape": "box",
            "margin": 12,
            "font": {
                "size": 15,
                "bold": True,
                "face": "arial",
                "color": couleur.get("font", {}).get("color", "#ffffff"),
            },
            "borderWidth": 2,
            "widthConstraint": {"minimum": 110, "maximum": 240},
            "heightConstraint": {"minimum": 36},
        }
        pos = positions.get(node_id)
        if pos and "x" in pos and "y" in pos:
            vis_node["x"] = float(pos["x"])
            vis_node["y"] = float(pos["y"])
            vis_node["fixed"] = {"x": False, "y": False}
        noeuds.append(vis_node)
    return noeuds


def preparer_aretes_vis(graph_data: dict) -> list[dict[str, Any]]:
    aretes = []
    for e in graph_data.get("edges", []):
        type_rel = e.get("type", "jointure")
        couleur = "#E67E22" if type_rel == "jointure" else "#8E44AD"
        aretes.append({
            "id": e.get("id", f"{e['from']}_{e['to']}"),
            "from": e["from"],
            "to": e["to"],
            "label": e.get("label", ""),
            "arrows": "to",
            "color": {"color": couleur, "highlight": "#F39C12"},
            "font": {"size": 11, "align": "middle"},
            "smooth": {"type": "dynamic"},
        })
    return aretes


def options_vis_network(positions_fixes: bool = False) -> dict[str, Any]:
    """Options vis.js : nœuds lisibles, espacement, édition manuelle des arêtes."""
    options: dict[str, Any] = {
        "nodes": {
            "shape": "box",
            "font": {"size": 15, "bold": True},
            "margin": 12,
        },
        "edges": {
            "width": 2,
            "selectionWidth": 3,
            "smooth": {"type": "dynamic"},
        },
        "interaction": {
            "dragNodes": True,
            "dragView": True,
            "zoomView": True,
            "hover": True,
            "multiselect": False,
        },
        "manipulation": {
            "enabled": True,
            "addNode": False,
            "addEdge": True,
            "editEdge": True,
            "deleteNode": False,
            "deleteEdge": True,
        },
        "layout": {
            "improvedLayout": True,
            "hierarchical": {"enabled": False},
        },
    }
    if positions_fixes:
        options["physics"] = {"enabled": False}
    else:
        options["physics"] = {
            "enabled": True,
            "barnesHut": {
                "gravitationalConstant": -12000,
                "centralGravity": 0.15,
                "springLength": 220,
                "springConstant": 0.05,
                "damping": 0.12,
                "avoidOverlap": 0.8,
            },
            "stabilization": {
                "enabled": True,
                "iterations": 200,
                "fit": True,
            },
        }
    return options


def graph_data_en_json(graph_data: dict) -> str:
    return json.dumps(graph_data, ensure_ascii=False, indent=2)
