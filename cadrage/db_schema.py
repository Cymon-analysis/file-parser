"""Extraction DDL + échantillons de données anonymisés (reverse-engineering)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cadrage.config import ECHANTILLON_BDD_LIGNES
from cadrage.data_sampling import assembler_contexte_table, formater_echantillon_anonymise


@dataclass
class ParametresConnexion:
    dialecte: str
    schema: str = "public"
    tables_selectionnees: list[str] | None = None
    # BigQuery
    projet: str = ""
    dataset: str = ""
    credentials_dict: dict[str, Any] | None = None
    # SQLAlchemy (Snowflake, PostgreSQL, générique)
    connection_string: str = ""


@dataclass
class ContexteTable:
    """DDL + échantillon anonymisé pour une table."""

    nom: str
    ddl: str
    contenu_complet: str
    colonnes_masquees: list[str] = field(default_factory=list)
    nb_lignes_echantillon: int = 0


def _echantillon_sqlalchemy(
    engine,
    schema: str,
    table: str,
    prefixe: str,
) -> tuple[list[str], list[list[Any]]]:
    """Exécute SELECT * LIMIT 50 via SQLAlchemy."""
    from sqlalchemy import MetaData, Table, select

    metadata = MetaData()
    schema_eff = schema if schema else None
    try:
        tbl = Table(table, metadata, schema=schema_eff, autoload_with=engine)
    except Exception:
        tbl = Table(table, metadata, autoload_with=engine)

    colonnes = [c.name for c in tbl.columns]
    with engine.connect() as conn:
        result = conn.execute(select(tbl).limit(ECHANTILLON_BDD_LIGNES))
        lignes = [list(row) for row in result.fetchall()]
    return colonnes, lignes


def _contexte_sqlalchemy(params: ParametresConnexion) -> dict[str, ContexteTable]:
    from sqlalchemy import create_engine, inspect, text

    if not params.connection_string.strip():
        raise ValueError(
            "Chaîne de connexion manquante. "
            "Exemple PostgreSQL : postgresql+psycopg2://user:pass@host:5432/dbname"
        )

    engine = create_engine(params.connection_string)
    contextes: dict[str, ContexteTable] = {}
    schema = params.schema or "public"

    with engine.connect() as conn:
        try:
            conn.execute(text("SET TRANSACTION READ ONLY"))
        except Exception:
            pass
        insp = inspect(engine)
        noms_schemas = insp.get_schema_names()
        if schema in noms_schemas or params.dialecte != "PostgreSQL":
            tables = params.tables_selectionnees or insp.get_table_names(schema=schema)
        else:
            tables = params.tables_selectionnees or insp.get_table_names()

        for table in tables:
            schema_courant = schema
            try:
                colonnes_meta = insp.get_columns(table, schema=schema_courant)
                fks = insp.get_foreign_keys(table, schema=schema_courant)
            except Exception:
                colonnes_meta = insp.get_columns(table)
                fks = insp.get_foreign_keys(table)
                schema_courant = ""

            prefixe = f"{schema_courant}.{table}" if schema_courant else table
            lignes_ddl = [f"CREATE TABLE {prefixe} ("]
            defs = []
            for col in colonnes_meta:
                nullable = "" if col.get("nullable", True) else " NOT NULL"
                defs.append(f"  {col['name']} {col['type']}{nullable}")
            lignes_ddl.append(",\n".join(defs))
            lignes_ddl.append(");")
            if fks:
                lignes_ddl.append("-- Clés étrangères détectées :")
                for fk in fks:
                    lignes_ddl.append(
                        f"-- FK {fk.get('name')}: {fk.get('constrained_columns')} "
                        f"-> {fk.get('referred_schema')}.{fk.get('referred_table')}"
                        f"({fk.get('referred_columns')})"
                    )
            ddl = "\n".join(lignes_ddl)

            try:
                colonnes, lignes = _echantillon_sqlalchemy(
                    engine, schema_courant or schema, table, prefixe,
                )
            except Exception as exc:
                colonnes, lignes = [c["name"] for c in colonnes_meta], []
                ddl += f"\n-- Échantillon non disponible : {exc}"

            echantillon_csv, cols_masquees = formater_echantillon_anonymise(colonnes, lignes)
            contenu = assembler_contexte_table(ddl, echantillon_csv, cols_masquees)
            contextes[prefixe] = ContexteTable(
                nom=prefixe,
                ddl=ddl,
                contenu_complet=contenu,
                colonnes_masquees=cols_masquees,
                nb_lignes_echantillon=len(lignes),
            )

    engine.dispose()
    return contextes


def _contexte_bigquery(params: ParametresConnexion) -> dict[str, ContexteTable]:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    if not params.projet.strip():
        raise ValueError("ID du Projet GCP requis pour BigQuery.")
    if not params.dataset.strip():
        raise ValueError("ID du Dataset requis pour BigQuery.")

    if not params.credentials_dict:
        raise ValueError(
            "Credentials client BigQuery requis. Téléversez un JSON Service Account "
            "dans la section « Connexion Base de Données » (indépendant du LLM cabinet)."
        )
    credentials = service_account.Credentials.from_service_account_info(
        params.credentials_dict
    )
    client = bigquery.Client(project=params.projet, credentials=credentials)

    dataset_ref = f"{params.projet}.{params.dataset}"
    tables = params.tables_selectionnees
    if not tables:
        tables = [t.table_id for t in client.list_tables(dataset_ref)]

    contextes: dict[str, ContexteTable] = {}
    for table_id in tables:
        table_ref = f"{dataset_ref}.{table_id}"
        table = client.get_table(table_ref)
        defs = [f"  {field.name} {field.field_type}" for field in table.schema]
        ddl = f"CREATE TABLE `{table_ref}` (\n" + ",\n".join(defs) + "\n);"
        colonnes = [field.name for field in table.schema]

        try:
            query = f"SELECT * FROM `{table_ref}` LIMIT {ECHANTILLON_BDD_LIGNES}"
            rows = client.query(query).result()
            lignes = [[row[col] for col in colonnes] for row in rows]
        except Exception as exc:
            lignes = []
            ddl += f"\n-- Échantillon non disponible : {exc}"

        echantillon_csv, cols_masquees = formater_echantillon_anonymise(colonnes, lignes)
        contenu = assembler_contexte_table(ddl, echantillon_csv, cols_masquees)
        contextes[table_ref] = ContexteTable(
            nom=table_ref,
            ddl=ddl,
            contenu_complet=contenu,
            colonnes_masquees=cols_masquees,
            nb_lignes_echantillon=len(lignes),
        )
    return contextes


def extraire_contextes_bdd(params: ParametresConnexion) -> dict[str, ContexteTable]:
    """
    Extrait DDL + échantillon anonymisé (LIMIT 50) pour chaque table.
    """
    try:
        if params.dialecte == "Google BigQuery":
            return _contexte_bigquery(params)
        return _contexte_sqlalchemy(params)
    except ImportError as exc:
        raise ImportError(
            f"Dépendance manquante pour {params.dialecte}. "
            f"Installez les paquets requis : {exc}"
        ) from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ConnectionError(
            f"Échec de connexion {params.dialecte} : {exc}. "
            "Vérifiez les identifiants, le réseau et les droits en lecture."
        ) from exc


def extraire_schemas_ddl(params: ParametresConnexion) -> dict[str, str]:
    """Rétrocompatibilité : retourne le contenu complet (DDL + échantillon)."""
    return {k: v.contenu_complet for k, v in extraire_contextes_bdd(params).items()}
