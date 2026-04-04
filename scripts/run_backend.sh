#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${CONDA_ENV_NAME:-st_env}"

if ! command -v conda >/dev/null 2>&1; then
  echo "Conda was not found."
  echo "Install Miniforge and create the environment first."
  exit 1
fi

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "${ENV_NAME}"

export INTERACTIVE_ANNOTATION_PROJECT_ROOT="${ROOT_DIR}"
export INTERACTIVE_ANNOTATION_DATA_ROOT="${ROOT_DIR}/data"
export INTERACTIVE_ANNOTATION_LINEAGE_ROOT="${ROOT_DIR}/data/lineages_current"
export INTERACTIVE_ANNOTATION_GLOBAL_OBJECT_PATH="${ROOT_DIR}/data/adata_global.h5ad"
export INTERACTIVE_ANNOTATION_CORS_ORIGINS="http://127.0.0.1:5173,http://localhost:5173"

cd "${ROOT_DIR}/backend"
uvicorn app.main:app --host 127.0.0.1 --port 8000
