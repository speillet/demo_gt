import os
from dotenv import load_dotenv

# Charge les variables d'environnement depuis le fichier .env (s'il existe)
load_dotenv()

# ==============================================================================
# Dossiers / Chemins
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONVERSATIONS_DIR = os.path.join(DATA_DIR, "conversations")

# ==============================================================================
# Modèles (LLM)
# ==============================================================================
# La sélection et la configuration du fournisseur de modèle sont gérées dans
# ``llm.py`` (registre de fournisseurs, lecture paresseuse des variables d'env).

# ==============================================================================
# Serveurs MCP
# ==============================================================================
QGIS_MCP_REF = os.environ.get("QGIS_MCP_REF", "599de023a60f6ff0d477d8b75806259a29d7e88c")
GEOPORTAIL_URL = os.environ.get("GEOPORTAIL_URL", "https://geollm.beta.ign.fr/geocontext/mcp")
