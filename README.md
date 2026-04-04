# Interactive Annotation App

This app helps you view lineage `.h5ad` files, inspect UMAPs, draw polygons, propagate annotations, rename clusters, examine genes, and move clusters between lineage objects.

This guide is written for someone with beginner coding skills. You do not need Docker for local development, but a Docker option is included later in this guide if you want a more portable setup.

## What You Need

Before you start, make sure you have:

- this repository on your computer
- Miniforge installed
- a terminal
- a web browser

You do not need to install Python or Node.js separately if you use the Conda environment in this guide, because the new `environment.yml` includes both.

## Folder Layout

Important folders:

- `backend/`: Python backend
- `frontend/`: React frontend
- `data/lineages_current/`: lineage-specific `.h5ad` objects
- `data/adata_global.h5ad`: global object for comparative viewing
- `scripts/`: helper scripts for setup and running the app

## Quick Start

If you want the shortest version:

1. install Miniforge
2. open a terminal in this repository
3. run:

```bash
bash scripts/setup_local.sh
```

4. open a second terminal and run:

```bash
bash scripts/run_backend.sh
```

5. open a third terminal and run:

```bash
bash scripts/run_frontend.sh
```

6. open your browser at:

```text
http://127.0.0.1:5173
```

## Step 1: Install Miniforge

If you do not already have Conda, install Miniforge first:

- https://github.com/conda-forge/miniforge

After installation, open a new terminal.

Check that Conda works:

```bash
conda --version
```

If that does not work, restart your terminal and try again.

## Step 2: Set Up The Environment

From the project root, run:

```bash
bash scripts/setup_local.sh
```

What this does:

- creates or updates the Conda environment `st_env`
- installs Python packages from `environment.yml`
- installs frontend packages in `frontend/`

The environment file is:

- [environment.yml](/Users/binli/Projects/interactive_annotation/environment.yml)

It includes:

- Python `3.10`
- Node.js
- backend packages
- Scanpy, Matplotlib, and HDF5 support needed by the app

### Manual Setup If You Prefer

If you want to do the same work by hand:

```bash
conda env create -f environment.yml
conda activate st_env
cd frontend
npm install
```

If `st_env` already exists, use:

```bash
conda env update -n st_env -f environment.yml --prune
conda activate st_env
cd frontend
npm install
```

## Step 3: Start The Backend

In a new terminal, from the project root, run:

```bash
bash scripts/run_backend.sh
```

What this script does:

- activates `st_env`
- sets the required local environment variables
- starts the backend on `127.0.0.1:8000`

The script is:

- [scripts/run_backend.sh](/Users/binli/Projects/interactive_annotation/scripts/run_backend.sh)

If the backend is healthy, this command should work in another terminal:

```bash
curl http://127.0.0.1:8000/health
```

You should see a JSON response with `"status":"ok"`.

## Step 4: Start The Frontend

In another new terminal, from the project root, run:

```bash
bash scripts/run_frontend.sh
```

What this script does:

- activates `st_env`
- checks that frontend packages are installed
- starts the Vite frontend on `127.0.0.1:5173`

The script is:

- [scripts/run_frontend.sh](/Users/binli/Projects/interactive_annotation/scripts/run_frontend.sh)

## Step 5: Open The App In Your Browser

Open:

- `http://127.0.0.1:5173`

You can also usually use:

- `http://localhost:5173`

## Optional: Run The App With Docker

If you prefer Docker, the repository also includes a working Docker setup for the frontend and backend together.

### Requirements

- Docker Desktop
- the `data/` folder present in this repository

### Start The Docker App

From the project root, run:

```bash
docker compose up --build
```

If you want it in the background:

```bash
docker compose up -d --build
```

Then open:

- `http://127.0.0.1:5173`

The Docker app uses:

- frontend on port `5173`
- backend inside Docker on port `8000`
- the local `data/` folder mounted into the containers

Important:

- moving clusters and recomputing PCA/UMAP can take several minutes on large objects
- changes are written to the mounted `.h5ad` files in `data/`
- the Docker app reads the global object from `data/adata_global.h5ad`

To stop it:

```bash
docker compose down
```

## What To Do When The App Opens

1. wait for the page to load
2. look at the left side of the app
3. click `Scan`
4. choose one of the lineage objects
5. wait for the UMAP to load

Large objects can take time to load. That is normal.

## Main Parts Of The App

The app has three main working areas:

- left panel: object loading, view controls, propagation, and saving
- center: the UMAP view
- right panel: gene tools
- bottom center: cluster names

## Main Functionality

## 1. Basic Loading, Waiting, And Viewing

Use this workflow to open an object and explore it.

### Load An Object

1. click `Scan`
2. choose an object such as `adata_Myeloid_current`
3. wait for the UMAP to appear

### Change What You See

In the left `View` panel you can change:

- `Embedding`
- `Cluster key`
- `Max points`
- `Min/cluster`

Then click:

- `Reload UMAP`

### What These Controls Mean

- `Embedding`: which coordinate system to plot
- `Cluster key`: which labels are used to color points
- `Max points`: total number of cells drawn on screen
- `Min/cluster`: minimum number of cells to keep per cluster in the sampled display

### Lineage And Global Views

In the `View` panel there are two tabs:

- `Lineage`
- `Global`

Use them to switch between:

- the current lineage-specific object
- the global object

The center plot also switches between these views.

### Tips For Beginners

- if the plot feels slow, reduce `Max points`
- if the plot looks too sparse, increase `Max points`
- if you get lost after zooming, click `Reset view`

## 2. Draw A Polygon, Name It, Propagate It, And Save

This is the main manual annotation workflow.

### Step A: Prepare The View

1. load an object
2. make sure you are in the lineage view
3. click `Reset view` if the plot is zoomed in a strange way

### Step B: Draw A Polygon

Use the buttons above the UMAP:

- `Draw polygon`
- `Close polygon`
- `Undo point`
- `Clear draft`

Suggested workflow:

1. click `Draw polygon`
2. click around the cell cloud you want
3. if you make a mistake, click `Undo point`
4. if you want to restart, click `Clear draft`
5. when the shape is finished, click `Close polygon`

### Step C: Give The Polygon A New Cluster

After the polygon is closed, go to the polygon section in the left panel.

For the polygon, enter:

- a numerical cluster ID
- a human-readable name

Example:

- cluster ID: `8`
- human-readable name: `Macrophage candidate`

### Step D: Propagate

When your polygon is ready:

1. make sure the polygon is enabled
2. click `Propagate selected polygons`
3. wait for the propagation to finish

This can take time on large objects.

### Step E: Save The Result

When you are happy with the new annotation:

1. click `Save reannotated object`

This writes the reannotation back into the current `.h5ad` file on disk.

Important:

- this is an in-place save
- the file really changes on disk

## 3. Color UMAP By Gene And Use Dotplot

Use the right-side `Gene Examination` panel.

### Color UMAP By One Gene

1. search for a gene
2. select exactly one gene
3. click `Color UMAP by gene`

The plot will switch from cluster colors to expression colors.

If you want to return to cluster colors, click:

- `Restore cluster colors`

### Preview A Dotplot

1. select one or more genes
2. click `Preview dotplot`

This shows a dotplot in the app.

### Save A Dotplot

1. select one or more genes
2. click `Save dotplot beside object`

This saves a PNG file next to the current object.

## 4. Use The Cluster Names Panel

The `Cluster Names` panel is at the bottom center.

You can use it to:

- show or hide clusters
- rename clusters
- highlight a lineage cluster in the global view
- move a cluster into another object
- undo the latest move

### Rename A Cluster

1. find the cluster row
2. edit the text in the human-readable name box
3. click `Save names to object`

This writes the display names back into the current object.

### Highlight A Cluster In The Global View

1. find the cluster row
2. click `Highlight`

The app switches to the global view and highlights matching cells.

If you want normal colors back, click:

- `Restore cluster colors`

### Undo The Latest Move

If you just moved a cluster and want to reverse that most recent move:

1. click `Undo Moving cluster`

Important:

- this is a one-step undo for the latest move only

## 5. Example: Move One Cluster From Myeloid To Stromal

Here is a real example using the current project objects.

### Example Cluster

- source object: `adata_Myeloid_current`
- cluster key: `reannot_label`
- cluster ID: `3`
- cluster name: `CD163 macrophage`
- destination object: `adata_Stromal_current`

### Step-By-Step

1. click `Scan`
2. load `adata_Myeloid_current`
3. make sure `Cluster key` is `reannot_label`
4. go to the `Cluster Names` panel
5. find cluster `3`
6. click `Move to`
7. choose `adata_Stromal_current`
8. read the preview

The preview tells you:

- how many cells will be moved
- how many destination `cell_id` values will be overwritten
- the destination cluster ID that will be assigned
- the destination display name

If it looks correct:

1. click `OK`
2. wait

Important:

- this operation changes both objects
- after the move, the app recomputes PCA and UMAP embeddings
- this can take a while on large objects
- in Docker, a large move can take a few minutes
- do not close the backend while it is working

After the move:

- the source object loses that cluster
- the destination object gains the moved cluster
- the moved human-readable name stays readable instead of growing longer and longer with repeated suffixes

If you want to reverse that latest move:

1. click `Undo Moving cluster`

## 6. Advanced Features Not Covered Here

This beginner guide does not explain these advanced sections:

- `Propagate (Reference-Based)`
- `Marker Discovery`

## Files Added For Easier Setup

This repository now includes beginner-friendly setup files:

- [environment.yml](/Users/binli/Projects/interactive_annotation/environment.yml)
- [scripts/setup_local.sh](/Users/binli/Projects/interactive_annotation/scripts/setup_local.sh)
- [scripts/run_backend.sh](/Users/binli/Projects/interactive_annotation/scripts/run_backend.sh)
- [scripts/run_frontend.sh](/Users/binli/Projects/interactive_annotation/scripts/run_frontend.sh)

## Common Problems

### `conda` Is Not Found

Install Miniforge, then open a new terminal and try again.

### `conda activate st_env` Does Not Work

Try:

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate st_env
```

### The App Opens But You Do Not See Data

Check:

- the backend is running on `127.0.0.1:8000`
- the frontend is running on `127.0.0.1:5173`
- you clicked `Scan`
- you selected a valid object

### `Scan` Fails

The intended lineage folder for this project is:

```text
/Users/binli/Projects/interactive_annotation/data/lineages_current
```

### I Want To Stop The App

In the backend terminal and frontend terminal, press:

```bash
Ctrl+C
```

## Summary

For most users, the full local workflow is just:

```bash
bash scripts/setup_local.sh
```

Then in two separate terminals:

```bash
bash scripts/run_backend.sh
```

```bash
bash scripts/run_frontend.sh
```

Then open:

```text
http://127.0.0.1:5173
```
