#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${CONDA_ENV_NAME:-st_env}"

if ! command -v conda >/dev/null 2>&1; then
  echo "Conda was not found."
  echo "Install Miniforge first, then open a new terminal and run this script again."
  exit 1
fi

source "$(conda info --base)/etc/profile.d/conda.sh"

if conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "Updating existing Conda environment: ${ENV_NAME}"
  conda env update -n "${ENV_NAME}" -f "${ROOT_DIR}/environment.yml" --prune
else
  echo "Creating Conda environment: ${ENV_NAME}"
  conda env create -f "${ROOT_DIR}/environment.yml"
fi

conda activate "${ENV_NAME}"

echo "Installing frontend packages"
cd "${ROOT_DIR}/frontend"
npm install

echo
echo "Setup complete."
echo "Next:"
echo "  bash scripts/run_backend.sh"
echo "  bash scripts/run_frontend.sh"
