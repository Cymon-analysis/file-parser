#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Application Streamlit v5 — Cadrage Analytics Engineering (mode hybride + mindmap).

Sources cumulatives : fichiers locaux + DDL base de données.
"""

from __future__ import annotations

import hashlib
import json
import os

import streamlit as st

from cadrage.cache_semantique import calculer_hash_cache
from cadrage.client_db_auth import (
    charger_credentials_client,
    client_db_configure,
    enregistrer_service_account_client,
)
from cadrage.config import (
    DIALECTES_DB,
    DOSSIER_BRUTES,
    DOSSIER_EXTRACTION_TEMP,
    DOSSIER_NORMALISE,
    MODELE_GEMINI,
    SEUIL_ALERTE_COUT_USD,
    STACK_OPTIONS,
)
from cadrage.db_schema import ParametresConnexion, extraire_schemas_ddl
from cadrage.gcp_auth import enregistrer_service_account, restaurer_credentials_session
from cadrage.gemini_client import compter_tokens, estimer_cout_max_usd, obtenir_client
from cadrage.livrable_pipeline import (
    compiler_livrable_complet,
    generer_section_1_contexte,
    generer_section_2_dictionnaire,
    generer_section_3_code,
    generer_section_4_mapping_scoping,
    livrable_vide,
    statut_sections,
    toutes_sections_completes,
)
from cadrage.mermaid_utils import extraire_diagramme_mermaid
from cadrage.models import SourceContexte, sanitiser_metadonnees
from cadrage.notion_export import exporter_vers_notion
from cadrage.graph_gemini import generer_graph_data
from cadrage.graph_ui import ui_graphe_complet
from cadrage.prompts import (
    a_echantillons_bdd,
    compiler_contexte_sources,
    est_mode_hybride,
    prompt_utilisateur,
    valider_payload_sources,
)
from cadrage.sampling import formater_taille
from cadrage.sources_fichiers import ingerer_dossier_brut, scanner_dossier, sources_depuis_ddl
from cadrage.sources_registry import (
    compter_sources,
    integrer_ddl,
    integrer_fichiers,
    lister_sources,
    sources_dict_vide,
)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


def initialiser_session() -> None:
    defauts = {
        "sources": sources_dict_vide(),
        "sources_selectionnees": set(),
        "scan_fichiers_effectue": False,
        "extraction_ddl_effectuee": False,
        "busy_scan_fichiers": False,
        "busy_extraction_ddl": False,
        "projet_titre": "Mission de Cadrage Data - [Nom Client]",
        "perimetre_metier": "Finance, Ventes",
        "stack_technique": STACK_OPTIONS[0],
        "stack_autre": "",
        "instructions_consultant": "",
        "livrable_markdown": "",
        "livrable": livrable_vide(),
        "busy_livrable": False,
        "diagramme_mermaid": "",
        "erreur_generation": "",
        "erreur_notion": "",
        "cache_utilise": False,
        "url_notion": "",
        "db_dialecte": DIALECTES_DB[0],
        "db_schema": "public",
        "db_tables": "",
        "db_projet_bq": "",
        "db_dataset_bq": "",
        "db_connection_string": "",
        "graph_data": None,
        "graph_genere": False,
        "graph_positions": {},
        "current_node": None,
        "afficher_form_nouveau_noeud": False,
        "noeud_selectionne": None,
        "erreur_graph": "",
        "gcp_credentials_path": None,
        "gcp_credentials_dict": None,
        "gcp_project_id": "",
        "gcp_service_account_email": "",
        "gcp_auth_configured": False,
        "gcp_credentials_empreinte": "",
        "client_db_credentials_path": None,
        "client_db_credentials_dict": None,
        "client_db_project_id": "",
        "client_db_service_account_email": "",
        "client_db_auth_configured": False,
        "client_db_credentials_empreinte": "",
        "client_db_connection_ok": False,
        "arborescence_ingestion": "",
        "rapport_ingestion": "",
    }
    for cle, valeur in defauts.items():
        if cle not in st.session_state:
            st.session_state[cle] = valeur

    if st.session_state.get("gcp_auth_configured") and st.session_state.get("gcp_credentials_path"):
        restaurer_credentials_session(st.session_state.gcp_credentials_path)

    if st.session_state.get("client_db_auth_configured") and st.session_state.get("client_db_credentials_path"):
        creds = charger_credentials_client(st.session_state.client_db_credentials_path)
        if creds:
            st.session_state.client_db_credentials_dict = creds

    # Migration depuis l'ancien format (listes séparées → dict unique)
    if not st.session_state.sources and (
        "sources_fichiers" in st.session_state or "sources_ddl" in st.session_state
    ):
        for source in st.session_state.get("sources_fichiers", []):
            st.session_state.sources[source.identifiant] = source
        for source in st.session_state.get("sources_ddl", []):
            st.session_state.sources[source.identifiant] = source


def stack_effective() -> str:
    if st.session_state.stack_technique == "Autre (Saisir ci-dessous)":
        return st.session_state.stack_autre.strip() or "Non précisée"
    return st.session_state.stack_technique


def toutes_les_sources() -> list[SourceContexte]:
    return lister_sources(st.session_state.sources)


def sources_fichiers() -> list[SourceContexte]:
    return lister_sources(st.session_state.sources, "fichier")


def sources_ddl() -> list[SourceContexte]:
    return lister_sources(st.session_state.sources, "ddl")


def sources_actives() -> list[SourceContexte]:
    sel = st.session_state.sources_selectionnees
    return [s for s in toutes_les_sources() if s.identifiant in sel]


def au_moins_une_source() -> bool:
    return bool(st.session_state.sources)


def hash_contexte_actuel(sources: list[SourceContexte]) -> str:
    graph_json = ""
    if st.session_state.get("graph_data"):
        graph_json = json.dumps(st.session_state.graph_data, sort_keys=True, ensure_ascii=False)
    return calculer_hash_cache(
        sources=sources,
        projet_titre=st.session_state.projet_titre,
        perimetre_metier=st.session_state.perimetre_metier,
        stack=stack_effective(),
        instructions=st.session_state.instructions_consultant,
        graph_json=graph_json,
    )


def reinitialiser_selections() -> None:
    for cle in list(st.session_state.keys()):
        if str(cle).startswith("sel_"):
            del st.session_state[cle]


def invalider_livrable() -> None:
    st.session_state.livrable = livrable_vide()
    st.session_state.livrable_markdown = ""
    st.session_state.diagramme_mermaid = ""
    st.session_state.cache_utilise = False


def synchroniser_livrable_markdown() -> None:
    """Recompile le markdown complet depuis les sections du pipeline."""
    st.session_state.livrable_markdown = compiler_livrable_complet(st.session_state.livrable)
    st.session_state.diagramme_mermaid = (
        extraire_diagramme_mermaid(st.session_state.livrable_markdown) or ""
    )


def gemini_configure(cles: dict[str, str | None]) -> bool:
    return bool(cles.get("gcp_project") or cles.get("gemini"))


def obtenir_client_gemini(cles: dict[str, str | None]):
    if st.session_state.get("gcp_auth_configured") and st.session_state.get("gcp_credentials_path"):
        restaurer_credentials_session(st.session_state.gcp_credentials_path)
    return obtenir_client(cle_api=cles.get("gemini"), project_gcp=cles.get("gcp_project"))


# ---------------------------------------------------------------------------
# UI — Section A : fichiers locaux
# ---------------------------------------------------------------------------


def ui_section_fichiers_locaux() -> None:
    st.subheader("📁 Ingestion locale universelle")
    st.caption(
        f"Déposez vos fichiers (y compris archives `.zip`, `.7z`, `.rar` imbriquées) "
        f"dans `{DOSSIER_BRUTES}/`, puis lancez l'ingestion."
    )

    col_ingest, col_scan = st.columns(2)

    with col_ingest:
        if st.button(
            "Ingérer depuis sources_brutes (archives récursives)",
            type="primary",
            key="btn_ingest_brut",
        ):
            if st.session_state.busy_scan_fichiers:
                st.warning("Ingestion déjà en cours, veuillez patienter.")
                return
            if not DOSSIER_BRUTES.is_dir():
                st.error(
                    f"Le dossier `{DOSSIER_BRUTES}/` n'existe pas. "
                    "Créez-le et y déposez les fichiers client."
                )
                return
            st.session_state.busy_scan_fichiers = True
            try:
                with st.spinner(
                    "Désarchivage et analyse de la structure des fichiers en cours..."
                ):
                    nouvelles, notifs, resultat = ingerer_dossier_brut(
                        DOSSIER_BRUTES,
                        DOSSIER_EXTRACTION_TEMP,
                    )
                ajoutes, maj = integrer_fichiers(st.session_state.sources, nouvelles)
                st.session_state.scan_fichiers_effectue = True
                st.session_state.arborescence_ingestion = resultat.arborescence
                rapports = []
                if resultat.archives_traitees:
                    rapports.append(
                        f"{resultat.archives_traitees} archive(s) désarchivée(s)"
                    )
                rapports.append(f"{len(nouvelles)} fichier(s) identifié(s)")
                nb_supportes = sum(
                    1 for s in nouvelles if s.metadonnees.get("supporte", True)
                )
                nb_non_supportes = len(nouvelles) - nb_supportes
                if nb_non_supportes:
                    rapports.append(f"{nb_non_supportes} non supporté(s)")
                st.session_state.rapport_ingestion = " · ".join(rapports)

                ddl_sel = {
                    k for k in st.session_state.sources_selectionnees
                    if k.startswith("ddl:")
                }
                st.session_state.sources_selectionnees = ddl_sel | {
                    s.identifiant for s in nouvelles
                    if s.metadonnees.get("supporte", True)
                }
                invalider_livrable()
                st.session_state.graph_data = None
                st.session_state.graph_genere = False
                reinitialiser_selections()
                for msg in notifs:
                    st.info(msg)
                for avert in resultat.avertissements:
                    st.warning(avert)
                if nouvelles:
                    st.success(
                        f"Ingestion terminée : {ajoutes} ajouté(s), {maj} mis à jour."
                    )
                else:
                    st.warning(f"Aucun fichier exploitable dans `{DOSSIER_BRUTES}/`.")
                st.rerun()
            except Exception as exc:
                st.error(f"Erreur lors de l'ingestion : {exc}")
            finally:
                st.session_state.busy_scan_fichiers = False

    with col_scan:
        if st.button(
            "Scanner output_normalise (fichiers déjà normalisés)",
            key="btn_scan_fichiers",
        ):
            if st.session_state.busy_scan_fichiers:
                st.warning("Scan déjà en cours, veuillez patienter.")
                return
            st.session_state.busy_scan_fichiers = True
            try:
                nouvelles, _ = scanner_dossier(DOSSIER_NORMALISE)
                ajoutes, maj = integrer_fichiers(st.session_state.sources, nouvelles)
                st.session_state.scan_fichiers_effectue = True
                ddl_sel = {
                    k for k in st.session_state.sources_selectionnees
                    if k.startswith("ddl:")
                }
                st.session_state.sources_selectionnees = ddl_sel | {
                    s.identifiant for s in nouvelles
                }
                invalider_livrable()
                st.session_state.graph_data = None
                st.session_state.graph_genere = False
                reinitialiser_selections()
                if nouvelles:
                    st.success(
                        f"{len(nouvelles)} fichier(s) au scan "
                        f"({ajoutes} ajouté(s), {maj} mis à jour)."
                    )
                else:
                    st.warning(f"Aucun fichier dans `{DOSSIER_NORMALISE}/`.")
                st.rerun()
            finally:
                st.session_state.busy_scan_fichiers = False

    if st.session_state.rapport_ingestion:
        st.info(st.session_state.rapport_ingestion)

    if st.session_state.arborescence_ingestion:
        with st.expander("Arborescence des fichiers extraits", expanded=False):
            st.code(st.session_state.arborescence_ingestion, language=None)

    if st.session_state.scan_fichiers_effectue:
        n, _ = compter_sources(st.session_state.sources)
        st.caption(
            f"**{n}** fichier(s) local(aux) chargé(s)." if n
            else "Ingestion effectuée — aucun fichier chargé."
        )


# ---------------------------------------------------------------------------
# UI — Section B : base de données
# ---------------------------------------------------------------------------


def _indicateur_connexion(connecte: bool, label_ok: str, label_ko: str) -> None:
    if connecte:
        st.success(f"🟢 {label_ok}")
    else:
        st.warning(f"🔴 {label_ko}")


def _ui_auth_client_db(dialecte: str) -> dict | None:
    """Formulaire d'authentification client, isolé du LLM cabinet."""
    st.markdown("**Authentification client (isolée du LLM cabinet)**")

    if dialecte == "Google BigQuery":
        uploaded_client = st.file_uploader(
            "Fichier JSON Service Account — Base client",
            type=["json"],
            key="upload_client_db_service_account",
            help=(
                "Compte de service du client avec droits lecture BigQuery uniquement. "
                "Ce fichier est distinct des credentials Vertex AI du cabinet."
            ),
        )
        if uploaded_client is not None:
            empreinte = hashlib.sha256(uploaded_client.getvalue()).hexdigest()
            if empreinte != st.session_state.client_db_credentials_empreinte:
                try:
                    info = enregistrer_service_account_client(uploaded_client.getvalue())
                    st.session_state.client_db_credentials_path = info["chemin"]
                    st.session_state.client_db_credentials_dict = info["credentials_dict"]
                    st.session_state.client_db_project_id = info["project_id"]
                    st.session_state.client_db_service_account_email = info["client_email"]
                    st.session_state.client_db_auth_configured = True
                    st.session_state.client_db_credentials_empreinte = empreinte
                    st.session_state.client_db_connection_ok = True
                    if not st.session_state.db_projet_bq:
                        st.session_state.db_projet_bq = info["project_id"]
                    st.success(
                        f"Credentials client enregistrés : `{info['client_email']}`"
                    )
                except ValueError as exc:
                    st.error(str(exc))
            else:
                creds = charger_credentials_client(st.session_state.client_db_credentials_path)
                if creds:
                    st.session_state.client_db_credentials_dict = creds

        connecte = client_db_configure(
            dialecte,
            credentials_dict=st.session_state.get("client_db_credentials_dict"),
        )
        _indicateur_connexion(
            connecte,
            "Base de données connectée (Client)",
            "Base de données non configurée (Client)",
        )
        if connecte:
            st.caption(
                f"Compte client : `{st.session_state.client_db_service_account_email}`"
            )
        return st.session_state.get("client_db_credentials_dict")

    st.text_input(
        "Chaîne de connexion client (Connection String)",
        type="password",
        value=st.session_state.db_connection_string,
        key="input_connection_string",
        placeholder=(
            "postgresql+psycopg2://user:pass@host:5432/db  ou  "
            "snowflake://user:pass@account/db/schema?warehouse=WH"
        ),
        help="Credentials client uniquement — jamais utilisés pour le LLM cabinet.",
    )
    connecte = client_db_configure(
        dialecte,
        connection_string=st.session_state.get("input_connection_string", ""),
    )
    st.session_state.client_db_connection_ok = connecte
    _indicateur_connexion(
        connecte,
        "Base de données connectée (Client)",
        "Chaîne de connexion client requise",
    )
    return None


def ui_section_base_de_donnees() -> None:
    st.subheader("🗄️ Connexion Base de Données (Reverse-Engineering)")
    st.caption(
        "Extraction DDL en lecture seule — credentials client isolés du LLM cabinet. "
        "Aucune donnée d'authentification n'est stockée dans les sources."
    )

    dialecte = st.selectbox(
        "Type de base de données",
        DIALECTES_DB,
        index=DIALECTES_DB.index(st.session_state.db_dialecte),
        key="select_dialecte",
    )
    st.session_state.db_dialecte = dialecte

    credentials_dict = _ui_auth_client_db(dialecte)

    schema = st.text_input(
        "Schéma (PostgreSQL / Snowflake / SQLAlchemy)",
        value=st.session_state.db_schema,
        help="Ignoré pour Google BigQuery.",
    )
    tables = st.text_input(
        "Tables (optionnel, séparées par des virgules — vide = toutes)",
        value=st.session_state.db_tables,
        placeholder="clients, commandes, produits",
    )
    tables_liste = [t.strip() for t in tables.split(",") if t.strip()] or None

    params: ParametresConnexion | None = None

    if dialecte == "Google BigQuery":
        projet_defaut = st.session_state.db_projet_bq or st.session_state.client_db_project_id
        c1, c2 = st.columns(2)
        projet = c1.text_input("ID du Projet client", value=projet_defaut)
        dataset = c2.text_input("ID du Dataset", value=st.session_state.db_dataset_bq)

        params = ParametresConnexion(
            dialecte=dialecte,
            schema=schema,
            tables_selectionnees=tables_liste,
            projet=projet,
            dataset=dataset,
            credentials_dict=credentials_dict,
        )
    else:
        params = ParametresConnexion(
            dialecte=dialecte,
            schema=schema,
            tables_selectionnees=tables_liste,
            connection_string=st.session_state.get("input_connection_string", ""),
        )

    if st.button("Lancer l'extraction du schéma", type="primary", key="btn_extract_ddl"):
        if st.session_state.busy_extraction_ddl:
            st.warning("Extraction déjà en cours, veuillez patienter.")
            return
        st.session_state.busy_extraction_ddl = True
        st.session_state.db_schema = schema
        st.session_state.db_tables = tables

        if dialecte == "Google BigQuery":
            st.session_state.db_projet_bq = projet
            st.session_state.db_dataset_bq = dataset
            if not client_db_configure(dialecte, credentials_dict=credentials_dict):
                st.warning(
                    "Téléversez un JSON Service Account client dans la section ci-dessus "
                    "avant d'extraire le schéma BigQuery."
                )
                st.session_state.busy_extraction_ddl = False
                return
        else:
            st.session_state.db_connection_string = st.session_state.get(
                "input_connection_string", ""
            )
            if not client_db_configure(
                dialecte,
                connection_string=st.session_state.db_connection_string,
            ):
                st.warning("Saisissez la chaîne de connexion client.")
                st.session_state.busy_extraction_ddl = False
                return

        if params is None:
            st.session_state.busy_extraction_ddl = False
            return

        try:
            with st.spinner(f"Extraction DDL {dialecte} en cours..."):
                schemas = extraire_schemas_ddl(params)
            if not schemas:
                st.error("Aucune table trouvée. Vérifiez le dataset/schéma et les droits de lecture.")
                return

            nouvelles, _ = sources_depuis_ddl(schemas)
            ajoutes, maj = integrer_ddl(st.session_state.sources, nouvelles)
            st.session_state.extraction_ddl_effectuee = True
            fichiers_sel = {
                k for k in st.session_state.sources_selectionnees
                if not k.startswith("ddl:")
            }
            st.session_state.sources_selectionnees = fichiers_sel | {
                s.identifiant for s in nouvelles
            }
            invalider_livrable()
            st.session_state.graph_data = None
            st.session_state.graph_genere = False
            reinitialiser_selections()
            st.success(
                f"{len(nouvelles)} structure(s) DDL traitée(s) "
                f"({ajoutes} ajoutée(s), {maj} mise(s) à jour, sans doublon)."
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
        except ImportError as exc:
            st.error(str(exc))
        except ConnectionError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Erreur inattendue lors de l'extraction : {exc}")
        finally:
            st.session_state.busy_extraction_ddl = False

    if st.session_state.extraction_ddl_effectuee:
        _, n = compter_sources(st.session_state.sources)
        st.info(f"**{n}** structure(s) DDL chargée(s) depuis la base de données." if n else "Extraction effectuée — aucune table.")


# ---------------------------------------------------------------------------
# UI — liste des sources & configuration mission
# ---------------------------------------------------------------------------


def _afficher_source_dans_expander(source: SourceContexte) -> bool:
    """Affiche une source dans un expander compact. Retourne True si incluse."""
    supporte = source.metadonnees.get("supporte", True)
    defaut = supporte and source.identifiant in st.session_state.sources_selectionnees
    badge = "📁" if source.type_source == "fichier" else "🗄️"
    statut = ""
    if not supporte:
        statut = " ⛔"
    elif source.smart_sample_applique:
        statut = f" ⚡ −{source.reduction_pct:.0f}%"

    coche = False
    with st.expander(f"{badge} {source.nom}{statut}", expanded=False):
        onglets = st.tabs([
            "Configuration & Inclusion",
            "Aperçu de l'échantillon propre",
            "Métadonnées détectées",
        ])
        with onglets[0]:
            coche = st.checkbox(
                "Inclure cette source dans l'analyse",
                value=defaut,
                key=f"sel_{source.identifiant}",
                disabled=not supporte,
            )
            if not supporte:
                st.error(
                    source.metadonnees.get(
                        "message",
                        "Non supporté pour le cadrage sémantique",
                    )
                )
            elif source.smart_sample_applique:
                st.info(
                    f"Smart Sampling actif : données réduites de {source.reduction_pct:.0f}% "
                    f"pour l'API, structure préservée."
                )
            chemin_rel = source.metadonnees.get("chemin_relatif", source.identifiant)
            st.caption(f"Identifiant : `{source.identifiant}`")
            st.caption(f"Chemin : `{chemin_rel}` · {formater_taille(source.taille_octets)}")

        with onglets[1]:
            if source.echantillon_apercu:
                st.code(source.echantillon_apercu, language=None)
            else:
                st.caption("Aucun aperçu disponible.")

        with onglets[2]:
            meta = sanitiser_metadonnees(source.metadonnees)
            if meta:
                st.json(meta)
            else:
                st.caption("Aucune métadonnée détectée.")
            st.caption(
                "Les credentials et secrets ne sont jamais stockés dans les sources "
                "(payload sécurisé pour le LLM cabinet)."
            )

    return coche


def ui_liste_sources() -> None:
    fichiers = sources_fichiers()
    ddl = sources_ddl()

    if not fichiers and not ddl:
        st.warning(
            "Aucune source chargée. Utilisez la section fichiers et/ou la section base de données "
            "(les deux peuvent coexister)."
        )
        return

    nb_f, nb_d = len(fichiers), len(ddl)
    if nb_f and nb_d:
        st.success(f"Mode hybride actif : **{nb_f}** fichier(s) + **{nb_d}** table(s) DDL.")
    else:
        st.caption(f"**{nb_f + nb_d}** source(s) chargée(s) — cliquez pour inspecter.")

    nouvelle_selection: set[str] = set()

    if fichiers:
        st.markdown(f"#### 📁 Fichiers locaux ({nb_f})")
        for source in fichiers:
            if _afficher_source_dans_expander(source):
                nouvelle_selection.add(source.identifiant)

    if ddl:
        st.markdown(f"#### 🗄️ Tables base de données ({nb_d})")
        for source in ddl:
            if _afficher_source_dans_expander(source):
                nouvelle_selection.add(source.identifiant)

    st.session_state.sources_selectionnees = nouvelle_selection
    st.caption(
        f"**{len(nouvelle_selection)}** source(s) sélectionnée(s) pour l'analyse."
    )


def afficher_sidebar() -> dict[str, str | None]:
    st.sidebar.header("Authentification LLM (Cabinet)")
    st.sidebar.caption(
        "Credentials Vertex AI / Gemini du cabinet uniquement. "
        "Les accès base client sont configurés à l'étape 1."
    )

    uploaded_gcp = st.sidebar.file_uploader(
        "Fichier JSON Service Account — Cabinet (Vertex AI)",
        type=["json"],
        key="upload_gcp_service_account",
        help="Authentifie Gemini via Vertex AI. N'est pas utilisé pour la base client.",
    )

    if uploaded_gcp is not None:
        empreinte = hashlib.sha256(uploaded_gcp.getvalue()).hexdigest()
        if empreinte != st.session_state.gcp_credentials_empreinte:
            try:
                info = enregistrer_service_account(uploaded_gcp.getvalue())
                st.session_state.gcp_credentials_path = info["chemin"]
                st.session_state.gcp_credentials_dict = info["credentials_dict"]
                st.session_state.gcp_project_id = info["project_id"]
                st.session_state.gcp_service_account_email = info["client_email"]
                st.session_state.gcp_auth_configured = True
                st.session_state.gcp_credentials_empreinte = empreinte
                st.sidebar.success(
                    f"Credentials cabinet enregistrés : `{info['client_email']}`"
                )
            except ValueError as exc:
                st.sidebar.error(str(exc))
        else:
            restaurer_credentials_session(st.session_state.gcp_credentials_path)
    elif st.session_state.gcp_auth_configured:
        restaurer_credentials_session(st.session_state.gcp_credentials_path)

    if st.session_state.gcp_auth_configured:
        st.sidebar.success("🟢 LLM Vertex AI connecté (Cabinet)")
        st.sidebar.caption(
            f"Compte : `{st.session_state.gcp_service_account_email}` · "
            f"Projet : `{st.session_state.gcp_project_id}`"
        )
    elif os.environ.get("GEMINI_API_KEY"):
        st.sidebar.success("🟢 LLM Gemini connecté (Clé API)")
    else:
        st.sidebar.warning("🔴 LLM non configuré (Cabinet)")

    st.sidebar.divider()
    st.sidebar.header("Clés API & intégrations")
    cle_gemini = st.sidebar.text_input(
        "Clé API Gemini (optionnel si Vertex AI cabinet configuré)",
        value=os.environ.get("GEMINI_API_KEY", ""),
        type="password",
        help="Alternative à Vertex AI pour le LLM cabinet uniquement.",
    )
    st.sidebar.divider()
    st.sidebar.subheader("Export Notion")
    notion_token = st.sidebar.text_input("NOTION_TOKEN", value=os.environ.get("NOTION_TOKEN", ""), type="password")
    notion_page = st.sidebar.text_input("NOTION_PAGE_ID", value=os.environ.get("NOTION_PAGE_ID", ""))
    st.sidebar.divider()
    st.sidebar.markdown(
        f"**Modèle :** `{MODELE_GEMINI}`\n\n"
        "**Workflow :**\n"
        "1. Sources hybrides (fichiers + BDD)\n"
        "2. Estimation tokens\n"
        "3. Mindmap interactive\n"
        "4. Livrable final + Notion"
    )
    return {
        "gemini": cle_gemini.strip() or None,
        "gcp_project": st.session_state.gcp_project_id if st.session_state.gcp_auth_configured else None,
        "notion_token": notion_token.strip() or None,
        "notion_page": notion_page.strip() or None,
    }


def etape_1_capture_et_configuration() -> None:
    st.header("Étape 1 — Capture de l'existant & configuration")

    ui_section_fichiers_locaux()
    st.divider()
    ui_section_base_de_donnees()

    if not au_moins_une_source():
        st.caption("Chargez au moins une source (fichiers, base de données, ou les deux).")
        return

    st.divider()
    st.subheader("Contexte de la mission")
    with st.form("form_configuration_mission"):
        projet_titre = st.text_input("Titre du Projet", value=st.session_state.projet_titre)
        perimetre_metier = st.text_input("Périmètre Métier", value=st.session_state.perimetre_metier)
        stack_technique = st.selectbox(
            "Stack Technique Cible", STACK_OPTIONS,
            index=STACK_OPTIONS.index(st.session_state.stack_technique),
        )
        stack_autre = ""
        if stack_technique == "Autre (Saisir ci-dessous)":
            stack_autre = st.text_input("Précisez la stack technique", value=st.session_state.stack_autre)
        instructions = st.text_area(
            "Instructions spécifiques du consultant",
            value=st.session_state.instructions_consultant,
            height=120,
        )
        if st.form_submit_button("Enregistrer la configuration"):
            st.session_state.projet_titre = projet_titre
            st.session_state.perimetre_metier = perimetre_metier
            st.session_state.stack_technique = stack_technique
            st.session_state.stack_autre = stack_autre
            st.session_state.instructions_consultant = instructions
            st.success("Configuration enregistrée.")

    st.subheader("Sources cumulées (fichiers + DDL)")
    ui_liste_sources()


def etape_2_tokens_et_cout(cles: dict[str, str | None]) -> None:
    st.header("Étape 2 — Calculateur de tokens & coût Gemini")

    actifs = sources_actives()
    if not au_moins_une_source():
        st.caption("Chargez des sources à l'étape 1.")
        return
    if not actifs:
        st.warning("Sélectionnez au moins une source.")
        return
    if not gemini_configure(cles):
        st.error(
            "Authentification Gemini requise : téléversez un compte de service GCP "
            "ou saisissez une clé API Gemini."
        )
        return

    prompt_user = prompt_utilisateur(
        actifs, st.session_state.projet_titre,
        st.session_state.perimetre_metier, stack_effective(),
    )
    try:
        client = obtenir_client_gemini(cles)
        with st.spinner("Calcul des tokens via l'API Gemini..."):
            total_tokens = compter_tokens(client, prompt_user)
    except Exception as exc:
        st.error(f"Erreur lors du comptage des tokens : {exc}")
        return

    cout_max = estimer_cout_max_usd(total_tokens)
    c1, c2, c3 = st.columns(3)
    c1.metric("Sources sélectionnées", len(actifs))
    c2.metric("Volume total", f"{total_tokens:,} tokens".replace(",", " "))
    c3.metric("Coût max estimé", f"${cout_max:.4f}")

    st.info(
        f"Volume total : **{total_tokens:,} tokens** | "
        f"Coût maximum estimé : **${cout_max:.2f}** (sur une base {MODELE_GEMINI})".replace(",", " ")
    )
    if cout_max > SEUIL_ALERTE_COUT_USD:
        st.error(
            "⚠️ Attention, le volume est important. Le Smart Sampling réduit déjà "
            "les fichiers > 200 Ko ; désélectionnez les sources non essentielles si besoin."
        )


def etape_3_mindmap_interactive(cles: dict[str, str | None]) -> None:
    st.header("Étape 3 — Mindmap interactive (relations Tech & Métier)")

    actifs = sources_actives()
    if not actifs:
        if au_moins_une_source():
            st.caption("Sélectionnez au moins une source à l'étape 1.")
        else:
            st.caption("Chargez des sources à l'étape 1.")
        return
    if not gemini_configure(cles):
        st.error(
            "Authentification Gemini requise : téléversez un compte de service GCP "
            "ou saisissez une clé API Gemini."
        )
        return

    st.info(
        "Validez vos sources puis lancez la pré-analyse. "
        "Ajustez la mindmap (drag-and-drop, ajout/suppression de relations) "
        "avant de générer le livrable final."
    )

    if st.button("Analyser les relations et générer la mindmap", type="primary"):
        st.session_state.erreur_graph = ""
        try:
            client = obtenir_client_gemini(cles)
            with st.spinner(f"Pré-analyse graphe via {MODELE_GEMINI}..."):
                st.session_state.graph_data = generer_graph_data(
                    client,
                    actifs,
                    st.session_state.projet_titre,
                    st.session_state.perimetre_metier,
                    stack_effective(),
                )
            st.session_state.graph_genere = True
            st.session_state.noeud_selectionne = None
            st.session_state.current_node = None
            st.session_state.graph_positions = {}
            st.session_state.afficher_form_nouveau_noeud = False
            invalider_livrable()
            st.success(
                f"Mindmap générée : {len(st.session_state.graph_data['nodes'])} nœuds, "
                f"{len(st.session_state.graph_data['edges'])} relations."
            )
            st.rerun()
        except Exception as exc:
            st.session_state.graph_data = None
            st.session_state.graph_genere = False
            st.session_state.erreur_graph = str(exc)

    if st.session_state.erreur_graph:
        st.error(f"Échec de la pré-analyse : {st.session_state.erreur_graph}")

    if st.session_state.graph_genere and st.session_state.graph_data:
        ui_graphe_complet()
    elif not st.session_state.graph_genere:
        st.caption("Cliquez sur le bouton ci-dessus pour générer le graphe initial.")


def _parametres_generation(actifs: list[SourceContexte]) -> dict:
    return {
        "mode_hybride": est_mode_hybride(actifs),
        "avec_echantillons_bdd": a_echantillons_bdd(actifs),
        "graph_data": st.session_state.get("graph_data"),
        "projet_titre": st.session_state.projet_titre,
        "perimetre_metier": st.session_state.perimetre_metier,
        "stack": stack_effective(),
        "instructions": st.session_state.instructions_consultant,
    }


def _parametres_section_2(params: dict) -> dict:
    """Sous-ensemble des paramètres acceptés par generer_section_2_dictionnaire."""
    cles = ("stack", "instructions", "mode_hybride", "avec_echantillons_bdd", "graph_data")
    return {cle: params[cle] for cle in cles}


def _afficher_statut_sections() -> None:
    libelles = {
        "section_1": "1. Introduction & Stratégie",
        "section_2": "2. Dictionnaire de données",
        "section_3": "3. Couche sémantique (LookML/dbt)",
        "section_4": "4. Matrice, Mermaid & Scoping",
    }
    cols = st.columns(4)
    for col, (cle, libelle) in zip(cols, libelles.items()):
        ok = statut_sections(st.session_state.livrable).get(cle, False)
        with col:
            if ok:
                st.success(f"🟢 {libelle}")
            else:
                st.warning(f"⚪ {libelle}")


def etape_4_generation_et_export(
    cles: dict[str, str | None],
    notion_token: str | None,
    notion_page: str | None,
) -> None:
    st.header("Étape 4 — Génération itérative du livrable")

    actifs = sources_actives()
    if not actifs:
        if au_moins_une_source():
            st.caption("Sélectionnez au moins une source à l'étape 1.")
        return
    if not gemini_configure(cles):
        st.error(
            "Authentification Gemini requise : téléversez un compte de service GCP "
            "ou saisissez une clé API Gemini."
        )
        return
    if not st.session_state.get("graph_data") or not st.session_state.graph_genere:
        st.warning(
            "Générez et validez d'abord la mindmap à l'étape 3 "
            "avant de produire le livrable."
        )
        return

    st.info(
        "Génération modulaire : chaque section est produite séparément pour éviter "
        "la troncature par limite de tokens de sortie. Le dictionnaire (section 2) "
        f"effectue **{len(actifs)} appel(s) API** (un par source)."
    )
    _afficher_statut_sections()

    params = _parametres_generation(actifs)
    livrable = st.session_state.livrable

    def _verifier_payload() -> bool:
        payload = compiler_contexte_sources(actifs)
        problemes = valider_payload_sources(payload, len(actifs))
        for msg in problemes:
            st.error(msg)
        return not problemes

    col1, col2 = st.columns(2)

    with col1:
        if st.button(
            "1. Générer l'Introduction & Stratégie",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.busy_livrable,
            key="btn_livrable_s1",
        ):
            if not _verifier_payload():
                return
            st.session_state.busy_livrable = True
            st.session_state.erreur_generation = ""
            try:
                client = obtenir_client_gemini(cles)
                with st.spinner("Génération section 1 — Contexte & Stratégie..."):
                    livrable["section_1"] = generer_section_1_contexte(
                        client, actifs, livrable, **params,
                    )
                synchroniser_livrable_markdown()
                st.success("Section 1 enregistrée.")
                st.rerun()
            except Exception as exc:
                st.session_state.erreur_generation = str(exc)
            finally:
                st.session_state.busy_livrable = False

        if st.button(
            "3. Générer la Couche Sémantique (LookML/dbt)",
            use_container_width=True,
            disabled=st.session_state.busy_livrable,
            key="btn_livrable_s3",
        ):
            if not livrable.get("section_2", "").strip():
                st.warning("Générez d'abord la section 2 (dictionnaire).")
                return
            st.session_state.busy_livrable = True
            st.session_state.erreur_generation = ""
            try:
                client = obtenir_client_gemini(cles)
                with st.spinner("Génération section 3 — Code technique..."):
                    livrable["section_3"] = generer_section_3_code(
                        client, actifs, livrable, **params,
                    )
                synchroniser_livrable_markdown()
                st.success("Section 3 enregistrée.")
                st.rerun()
            except Exception as exc:
                st.session_state.erreur_generation = str(exc)
            finally:
                st.session_state.busy_livrable = False

    with col2:
        if st.button(
            "2. Générer le Dictionnaire de Données",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.busy_livrable,
            key="btn_livrable_s2",
        ):
            if not _verifier_payload():
                return
            st.session_state.busy_livrable = True
            st.session_state.erreur_generation = ""
            try:
                client = obtenir_client_gemini(cles)
                barre = st.progress(0.0, text="Dictionnaire : initialisation...")
                statut = st.empty()

                def _progress(courant: int, total: int, nom: str) -> None:
                    barre.progress(courant / total, text=f"Dictionnaire : {nom} ({courant}/{total})")
                    statut.caption(f"Appel API pour **{nom}**...")

                params_s2 = _parametres_section_2(params)
                livrable["section_2"] = generer_section_2_dictionnaire(
                    client, actifs, livrable,
                    on_progress=_progress,
                    **params_s2,
                )
                barre.progress(1.0, text="Dictionnaire : terminé")
                synchroniser_livrable_markdown()
                st.success(
                    f"Section 2 enregistrée ({len(actifs)} source(s) traitée(s))."
                )
                st.rerun()
            except Exception as exc:
                st.session_state.erreur_generation = str(exc)
            finally:
                st.session_state.busy_livrable = False

        if st.button(
            "4. Générer Matrice de Mapping & Scoping",
            use_container_width=True,
            disabled=st.session_state.busy_livrable,
            key="btn_livrable_s4",
        ):
            if not livrable.get("section_2", "").strip():
                st.warning("Générez d'abord la section 2 (dictionnaire).")
                return
            st.session_state.busy_livrable = True
            st.session_state.erreur_generation = ""
            try:
                client = obtenir_client_gemini(cles)
                with st.spinner("Génération section 4 — Mapping, Mermaid & Scoping..."):
                    livrable["section_4"] = generer_section_4_mapping_scoping(
                        client, actifs, livrable, **params,
                    )
                synchroniser_livrable_markdown()
                st.success("Section 4 enregistrée.")
                st.rerun()
            except Exception as exc:
                st.session_state.erreur_generation = str(exc)
            finally:
                st.session_state.busy_livrable = False

    if st.session_state.erreur_generation:
        st.error(f"Échec de la génération : {st.session_state.erreur_generation}")

    if toutes_sections_completes(livrable):
        st.success("Toutes les sections sont complètes. Le livrable est prêt à l'export.")
        synchroniser_livrable_markdown()
        st.download_button(
            label="Télécharger le Livrable Complet (.md)",
            data=st.session_state.livrable_markdown,
            file_name="livrable_cadrage.md",
            mime="text/markdown",
            type="primary",
            use_container_width=True,
        )
    else:
        manquantes = [
            k for k, ok in statut_sections(livrable).items() if not ok
        ]
        st.caption(
            f"Sections restantes : {', '.join(manquantes)}"
        )

    if not st.session_state.livrable_markdown:
        return

    with st.expander("Aperçu du livrable compilé", expanded=False):
        if st.session_state.diagramme_mermaid:
            st.subheader("Diagramme de relations (Mermaid)")
            try:
                st.mermaid(st.session_state.diagramme_mermaid)
            except Exception:
                st.code(st.session_state.diagramme_mermaid, language="mermaid")
        st.markdown(st.session_state.livrable_markdown)

    st.divider()
    st.subheader("Export Notion")
    if st.button("Exporter le projet vers Notion", use_container_width=True):
        st.session_state.erreur_notion = ""
        st.session_state.url_notion = ""
        try:
            with st.spinner("Création de la page Notion..."):
                url = exporter_vers_notion(
                    st.session_state.livrable_markdown,
                    st.session_state.projet_titre,
                    token=notion_token,
                    page_parent_id=notion_page,
                )
            st.session_state.url_notion = url
            st.success(f"Projet exporté vers Notion : {url}")
        except (ValueError, ImportError, RuntimeError) as exc:
            st.session_state.erreur_notion = str(exc)

    if st.session_state.erreur_notion:
        st.error(st.session_state.erreur_notion)
    if st.session_state.url_notion:
        st.markdown(f"[Ouvrir la page Notion]({st.session_state.url_notion})")


def main() -> None:
    st.set_page_config(
        page_title="Cadrage Analytics Engineering",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    initialiser_session()

    st.title("Cadrage Analytics Engineering")
    st.caption(
        "v5 — Mode hybride · Mindmap interactive · Smart Sampling · "
        "Cache sémantique · Export Notion"
    )

    cles = afficher_sidebar()
    etape_1_capture_et_configuration()
    st.divider()
    etape_2_tokens_et_cout(cles)
    st.divider()
    etape_3_mindmap_interactive(cles)
    st.divider()
    etape_4_generation_et_export(cles, cles["notion_token"], cles["notion_page"])


if __name__ == "__main__":
    main()
