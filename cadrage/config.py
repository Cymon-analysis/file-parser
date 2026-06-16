"""Constantes globales de l'application."""

from pathlib import Path

DOSSIER_NORMALISE = Path("output_normalise")
DOSSIER_BRUTES = Path("sources_brutes")
DOSSIER_EXTRACTION_TEMP = Path(".ingestion_temp")
FICHIER_CACHE = Path(".cadrage_cache.json")
DOSSIER_SECRETS = Path(".secrets")
FICHIER_GCP_CREDENTIALS_CABINET = DOSSIER_SECRETS / "gcp_credentials_cabinet.json"
FICHIER_GCP_CREDENTIALS_CLIENT_DB = DOSSIER_SECRETS / "gcp_credentials_client_db.json"
# Rétrocompatibilité
FICHIER_GCP_CREDENTIALS = FICHIER_GCP_CREDENTIALS_CABINET
VERTEX_AI_LOCATION = "europe-west1"

# Clés interdites dans les métadonnées exposées (sécurité payload LLM)
CLES_METADONNEES_INTERDITES = frozenset({
    "credentials", "credentials_dict", "private_key", "connection_string",
    "token", "password", "secret", "api_key", "client_email",
})

SEUIL_SMART_SAMPLING = 200 * 1024  # 200 Ko
LIGNES_SMART_SAMPLE = 30  # rétrocompatibilité texte
LIGNES_DEBUT_TABULAIRE = 30
LIGNES_FIN_TABULAIRE = 10
LIGNES_DEBUT_TEXTE = 40
LIGNES_FIN_TEXTE = 15
LIGNES_ECHANTILLON_CSV = 10
CARACTERES_ECHANTILLON_TEXTE = 1500

MODELE_GEMINI = "gemini-2.5-flash"
PRIX_ENTREE_PAR_MILLION = 0.15
PRIX_SORTIE_PAR_MILLION = 0.60
TOKENS_SORTIE_MAX_ESTIMES = 32_768
SEUIL_ALERTE_COUT_USD = 2.00
ECHANTILLON_BDD_LIGNES = 50

STACK_OPTIONS = [
    "Looker (LookML) + BigQuery",
    "dbt + Snowflake",
    "Power BI (DAX / Datamart)",
    "SQL BigQuery Pure (DDL/DML)",
    "Autre (Saisir ci-dessous)",
]

DIALECTES_DB = [
    "Google BigQuery",
    "Snowflake",
    "PostgreSQL",
    "SQLAlchemy (Connection String)",
]
