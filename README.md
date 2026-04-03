# Interactive Annotation User Guide

This project is a local interactive tool for viewing lineage `.h5ad` objects, drawing polygon seeds on UMAP embeddings, propagating labels, editing cluster display names, exploring genes, and saving reannotation results back into the selected object.

This guide is based on the current frontend and backend code in this repository. The primary startup path below is local development without Docker, using the existing Conda environment `st_env`.

## What the app does

- scans a lineage folder for viewable `.h5ad` objects
- loads UMAP or other 2D embeddings from `obsm`
- colors cells by cluster, annotation, or single-gene expression
- lets you draw polygons to seed new labels
- propagates those labels with either kNN vote or graph diffusion
- edits human-readable cluster names and cluster visibility
- runs reference-based reassignment from selected reference clusters to selected source clusters
- discovers candidate marker genes and renders marker dotplots
- saves reannotation outputs and sidecar files beside the source object

## Requirements

- Conda with an existing environment named `st_env`
- Node.js and npm for the frontend
- one or more lineage `.h5ad` files

The backend dependencies required by this repo are already available in `st_env` on this machine. If you need to install or refresh them later, run:

```bash
conda run -n st_env pip install -r backend/requirements.txt
```

## Expected data layout

By default the app looks for lineage objects under `data/lineages_current`.

Supported layouts:

```text
data/lineages_current/
  lineage_a/
    object_a.h5ad
    recluster_manifest.json              # optional
  lineage_b/
    object_b.h5ad
  summary_resolution_trials.csv          # optional
```

or:

```text
data/lineages_current/
  object_a.h5ad
  object_b.h5ad
```

The scanner also accepts a wrapper `lineages/` directory, so this works too:

```text
data/lineages_current/
  lineages/
    lineage_a/
      object_a.h5ad
```

Notes:

- No sample `.h5ad` files are bundled in this repo.
- A viewable object must be a readable AnnData file with at least one embedding in `obsm`.
- Propagation and reference-based relabeling also need a PCA-like embedding in `obsm` because the backend uses PCA features for kNN operations.

## Start locally without Docker

Open two terminals from the repository root.

### 1. Start the backend

```bash
cd /path/to/interactive_annotation
REPO_ROOT="$(pwd)"

conda activate st_env
cd "$REPO_ROOT/backend"

export INTERACTIVE_ANNOTATION_PROJECT_ROOT="$REPO_ROOT"
export INTERACTIVE_ANNOTATION_DATA_ROOT="$REPO_ROOT/data"
export INTERACTIVE_ANNOTATION_LINEAGE_ROOT="$REPO_ROOT/data/lineages_current"
export INTERACTIVE_ANNOTATION_CORS_ORIGINS="http://127.0.0.1:5173,http://localhost:5173"

uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

If `conda activate` is not initialized in your shell, use `conda run -n st_env ...` instead.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok","default_lineage_root":"/path/to/interactive_annotation/data/lineages_current"}
```

### 2. Start the frontend

```bash
cd /path/to/interactive_annotation
REPO_ROOT="$(pwd)"

cd "$REPO_ROOT/frontend"
npm install

VITE_DEFAULT_FOLDER="$REPO_ROOT/data/lineages_current" \
npm run dev -- --host 127.0.0.1 --port 5173
```

Open:

```text
http://127.0.0.1:5173
```

Notes:

- In dev mode, Vite proxies `/api` to `http://127.0.0.1:8000`.
- `VITE_DEFAULT_FOLDER` pre-fills the folder shown in the UI. You can still scan a different folder from the app.
- Stop the app with `Ctrl+C` in each terminal.

## First-time local smoke test

1. Put one or more `.h5ad` files under `data/lineages_current`.
2. Start the backend and frontend using the commands above.
3. Open `http://127.0.0.1:5173`.
4. In `Objects`, confirm the folder path is correct and click `Scan`.
5. Load a valid object and confirm points appear in the UMAP panel.

## Main workflow

### 1. Load an object

Use the `Objects` panel on the left:

- `Lineage folder`: the folder to scan for `.h5ad` objects
- `Scan`: refresh the object list
- `Detected objects`: select the object to load

When an object loads, the app also loads:

- metadata
- the default embedding
- the default cluster key
- cluster label editor data
- full gene catalog

### 2. Inspect the embedding

Use the `View` and `Visualization` panels:

- change `Embedding`
- change `Cluster key`
- adjust `Max points` and `Min/cluster` for sampling
- click `Reload UMAP` after changing sampling settings
- color by cluster, annotation, or a selected gene
- tune dot size, transparency, polygon boundary width, palette, and axis flips

The app samples large objects for display. The full object is still used for backend operations.

### 3. Edit cluster names

Use `Cluster Names` below the UMAP:

- each row shows a cluster ID and its cell count
- `Show` toggles visibility for that cluster in the UMAP
- `Human-readable name` lets you assign a display name
- `Save names to object` writes the display-name column into the selected `.h5ad`

The saved display column is inferred from the active cluster key. Examples:

- `reannot_label` -> `reannot_display_label`
- `reannot_label_new` -> `reannot_display_label_new`
- `leiden_1_0` -> `leiden_1_0_display_name`

### 4. Draw polygons to create seed labels

Use the UMAP toolbar:

- `Draw polygon` starts drawing mode
- click on the plot to add vertices
- `Close polygon` completes the polygon
- `Undo point` removes the most recent draft vertex
- `Clear draft` clears the in-progress polygon
- `Clear all` removes all saved polygons from the current session

After closing a polygon, use the `Polygons` panel:

- `Cluster ID`: the label that propagation will assign
- `Cluster name`: optional human-readable label
- `Include in propagate`: include or exclude that polygon from the next run
- `Cells inside` and `Leiden mix` summarize what the polygon captured

### 5. Propagate labels

Use the `Propagate` panel:

- `Method`
  - `kNN vote`
  - `Graph diffusion`
- `Scope`
  - `Polygon only`
  - `Selected clusters only`
  - `Same connected neighborhood`
  - `Whole lineage`
- `Annotate all`
  - when enabled, score and margin thresholds are ignored
- `Min score` and `Min margin`
  - used only when `Annotate all` is off
- `Graph smoothing`
  - used only for graph diffusion

Click `Propagate selected polygons` to run the current session.

What happens next:

- the app seeds cells from the included polygons
- propagation results are shown on the UMAP using annotation colors
- the `Session` panel reports seed counts and assigned counts
- nothing is persisted to disk yet

Use `Reset propagation` to discard the current propagated result but keep polygons, or `Reset session` to clear polygons as well.

### 6. Run reference-based relabeling

Use `Propagate (Reference-Based)`:

- choose the current `Cluster key` first
- mark one or more `Reference` clusters
- mark one or more disjoint `Source` clusters
- set `Output name`
- choose `kNN neighbors`
- click `Apply kNN vote to source clusters`

This creates new columns inside the selected object immediately:

- `reannot_label_<output_name>`
- `reannot_display_label_<output_name>`

Example:

- output name `new` creates `reannot_label_new` and `reannot_display_label_new`

After it runs, the app reloads the object and switches the active cluster key to the new column.

### 7. Promote `reannot_label_new` to canonical labels

If the current object contains `reannot_label_new`, the `View` panel exposes:

- `Use reannot_label_new as canonical`

This copies:

- `reannot_label_new` -> `reannot_label`
- `reannot_display_label_new` -> `reannot_display_label`

The object is written back immediately.

### 8. Explore genes and dotplots

Use the right-side `Gene Examination` panel:

- search genes by symbol
- tick genes to select them
- use the heart button to favorite genes locally in browser storage
- drag selected genes to reorder them for dotplots

Actions:

- `Color UMAP by gene`
  - requires exactly one selected gene
- `Preview dotplot`
  - renders a dotplot in the app only
- `Save dotplot beside object`
  - writes a PNG next to the selected `.h5ad`

### 9. Discover candidate marker genes

Use `Marker Discovery` at the bottom of the gene panel:

- only clusters currently checked in `Cluster Names` are used as the analysis universe
- select one or more target clusters
- choose `Candidate genes (N)`
- click `Discover marker genes`

The returned candidate genes are added to the selected-gene list so you can immediately preview or save a dotplot.

### 10. Save the reannotated session

Use `Session -> Save reannotated object` after a polygon propagation run.

This writes the propagated result into the selected `.h5ad` and also writes sidecar files beside it:

- `<object>.session.json`
- `<object>.polygons.geojson`
- `<object>.summary.csv`

The saved `.h5ad` receives reannotation fields including:

- `reannot_label`
- `reannot_display_label`
- `reannot_label_source`
- `reannot_confidence`
- `reannot_margin`
- `reannot_seed`
- `reannot_polygon_ids`
- `reannot_scope`
- `reannot_cluster_key`
- `reannot_session_id`
- `reannot_timestamp`

## Important persistence behavior

Several actions write directly back into the selected `.h5ad` in place. The backend writes to a temporary file in the same directory and then replaces the original file.

Actions that persist immediately:

- `Save names to object`
- `Apply kNN vote to source clusters`
- `Use reannot_label_new as canonical`
- `Save reannotated object`

Also:

- `Save dotplot beside object` writes a PNG beside the object
- `Preview dotplot` does not write a file
- polygon drawing and normal propagation stay in memory until `Save reannotated object`

If you need to preserve an untouched source object, make a copy before using the save actions above.

## Troubleshooting

### The object list is empty

- confirm the folder exists
- confirm the frontend default folder points to the correct absolute path
- confirm your `.h5ad` files are under the scanned folder

### An object is marked invalid

Common reasons:

- the file is not a readable AnnData object
- `obsm` is missing
- `obsm` exists but contains no embeddings
- required groups such as `var` are missing

### UMAP loads but propagation fails

Propagation requires PCA-like features in `obsm`. The backend looks for:

- `X_pca_lineage`, or
- another embedding key containing `pca`

### Frontend cannot reach the backend

- confirm the backend is running on `127.0.0.1:8000`
- confirm the frontend is running on `127.0.0.1:5173`
- confirm `INTERACTIVE_ANNOTATION_CORS_ORIGINS` includes the frontend URL

## Docker note

Docker support still exists in this repo through `docker-compose.yml` and the `Makefile`, but this document is intentionally local-first. If you do want the container path later, the existing shortcuts are:

```bash
make up
make down
make logs
```
