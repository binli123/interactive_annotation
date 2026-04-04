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

cd "${ROOT_DIR}/frontend"

if [ ! -d node_modules ]; then
  echo "Frontend packages are missing. Running npm install first."
  npm install
fi

npm run dev -- --host 127.0.0.1 --port 5173
