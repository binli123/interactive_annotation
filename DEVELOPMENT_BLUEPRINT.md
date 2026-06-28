# Interactive Annotation — Development Blueprint

> **How to use this document**
> Review the 15 proposed features below. For each one, assign a priority: **high**, **mid**, or **low**.
> Once priorities are set, we will implement features top-down, highest priority first.
> Add any notes or modifications to features directly in this file.

---

## Current State (What Already Works)

| Area                  | Capability                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------ |
| Visualization         | UMAP scatter (color by cluster / annotation / gene), flip axes, zoom/pan, polygon drawing        |
| Annotation            | Polygon-based seed labeling, graph-diffusion + KNN-vote propagation, score/margin thresholds     |
| Clusters              | Visibility toggles, label editor (rename), move cluster between objects, undo                    |
| Genes                 | Gene catalog search, favorites, expression coloring, marker discovery, dotplot (preview + save)  |
| Reference propagation | Transfer labels from reference clusters to source clusters via KNN                               |
| Global view           | Pan-lineage UMAP, highlight cross-object cluster membership                                      |
| Persistence           | Save annotations to`.h5ad`; sidecar `.session.json`, `.polygons.geojson`, `.summary.csv` |
| Undo                  | Move-cluster undo; object-change undo                                                            |

---

## Feature Proposals

Each feature is self-contained. Priority field is blank — **fill in your priority (high / mid / low)**.

---

### F-01 · Propagation Confidence Overlay

**Priority:** `___________`

**What it is:**
After propagation runs, the per-cell confidence score (0–1) and decision margin are already computed on the backend but are discarded after the result is displayed. This feature would add a new UMAP color mode — "Color by confidence" — that shades each annotated cell from light (low score) to dark (high score), and a second mode for margin. A threshold brush on the canvas (e.g., click-drag a score cutoff) would let annotators quickly identify ambiguous cells and re-seed them.

**Why it matters:**
Low-confidence cells are where annotation errors concentrate. Without seeing them spatially, annotators have no feedback loop.

**Key files touched:**

- `backend/app/api/routes.py` — `propagate` response: include `scores` and `margins` arrays
- `backend/app/schemas/api.py` — `PropagateResponse`: add `scores: list[float]`, `margins: list[float]`
- `frontend/src/app/store.ts` — store scores alongside propagation result; add `colorMode: 'confidence' | 'margin'`
- `frontend/src/components/UmapCanvas.tsx` — new color branch in `getFillColor`
- `frontend/src/components/SessionSidebar.tsx` — color mode selector

**Effort estimate:** Small (2–3 days). The data is already computed; it's a display change.

---

### F-02 · Violin & Feature Plots

**Priority:** `___________`

**What it is:**
A panel (or tab within the Gene Panel) that renders violin plots of selected gene expression per cluster using the currently loaded object. Optionally extend to feature plots — a grid of small UMAPs, one per selected gene, colored by that gene's expression.

**Why it matters:**
Violin plots are the standard sanity check for cell type markers (e.g., "does CD3E go up in T cells?"). Currently the only multi-gene visualization is the dotplot, which requires saving to disk. Violins would be in-browser and immediate.

**Backend approach:**
Add `GET /objects/{object_id}/violin-data?cluster_key=...&genes=...` endpoint returning per-cluster expression distributions (e.g., percentiles or raw values for violin rendering). Use scanpy or numpy sampling so it is fast enough for interactive use.

**Key files touched:**

- `backend/app/services/adata_service.py` — new `get_violin_data()` method
- `backend/app/api/routes.py` — new route
- `frontend/src/components/GenePanel.tsx` — violin rendering (lightweight SVG or Recharts)
- `frontend/src/app/api.ts` / `store.ts` — new call + state

**Effort estimate:** Medium (1 week). Requires a charting approach; rendering raw data or percentile bands.

---

### F-03 · Persistent Session Recovery

**Priority:** `___________`

**What it is:**
Right now, all in-progress annotation state (seed labels, polygons, propagation snapshots) lives only in RAM and is lost if the server restarts. This feature serializes the `SessionStore` to disk (JSON sidecar files in the lineage directory) on every mutation and reloads them on startup. The frontend would show a "Restore previous session?" prompt when re-opening an object with a live sidecar.

**Why it matters:**
A real annotation project may take hours or days across multiple sessions. Loss of seed labels after a restart is a critical data-safety issue.

**Key files touched:**

- `backend/app/services/sessions.py` — add `persist()` / `load()` methods writing to `<lineage_dir>/<object_id>.live_session.json`
- `backend/app/api/routes.py` — call `persist()` on every seed-labels / propagate mutation
- New endpoint: `GET /objects/{object_id}/live-session` — check for existing sidecar
- `frontend/src/app/store.ts` — detect and offer to restore on `selectObject`

**Effort estimate:** Medium (1 week). The serialization format is close to the existing sidecar; the tricky part is restoring polygon drawings and the propagation snapshot.

---

### F-04 · Observation Metadata Coloring

**Priority:** `___________`

**What it is:**
Allow the UMAP to be colored by any `obs` column in the AnnData object — not just the cluster key, annotation label, or a single gene. Examples: batch, sample ID, donor, tissue, total UMI count, percent mitochondrial, doublet score. Categorical columns would get palette colors; continuous columns would get a gradient.

**Why it matters:**
Batch effect detection and QC are prerequisite steps to annotation. Annotators need to see whether clusters are driven by biology or technical confounds. This is table-stakes in Scanpy/Seurat workflows.

**Backend approach:**
Add `GET /objects/{object_id}/obs-columns` to return column names + dtype, and `POST /objects/{object_id}/obs-values` with `{column: string, indices: number[]}` to return values for displayed points.

**Key files touched:**

- `backend/app/services/adata_service.py` — `get_obs_columns()`, `get_obs_values()`
- `backend/app/api/routes.py` — two new routes
- `frontend/src/components/UmapCanvas.tsx` — new color mode branch
- `frontend/src/components/SessionSidebar.tsx` — obs column picker

**Effort estimate:** Medium (4–5 days).

---

### F-05 · Automated Cell Type Suggestion

**Priority:** `___________`

**What it is:**
A "Suggest Labels" panel that queries a bundled marker gene database (CellMarker 2.0 or PanglaoDB, stored as a static JSON in the backend) to score each current cluster against known cell type signatures. For each cluster it returns the top-5 candidate cell types with a match score. The annotator can click "Accept" to pre-fill the cluster label editor.

**Why it matters:**
Manual annotation from scratch requires deep domain knowledge. Automated suggestions dramatically speed up the first pass, especially for common immune and stromal cell types.

**Implementation notes:**

- Bundle a filtered, species-aware marker database as a static asset (`backend/data/marker_db.json`)
- Score clusters by overlap between top marker genes (from `discover_markers`) and database gene sets
- Scoring: Jaccard index or a weighted overlap using expression specificity

**Key files touched:**

- New file: `backend/app/services/marker_db.py`
- `backend/app/api/routes.py` — `POST /objects/{object_id}/suggest-labels`
- `frontend/src/components/ClusterLabelEditor.tsx` — "Suggest" button per row

**Effort estimate:** Medium–Large (1–2 weeks). Database curation and scoring logic are the bulk of work.

---

### F-06 · Spatial Transcriptomics Coordinate View

**Priority:** `___________`

**What it is:**
For AnnData objects that contain `obsm['spatial']` (Visium, Xenium, MERFISH, etc.), add a second scatter plot panel showing cells in physical tissue coordinates instead of UMAP coordinates. Both panels stay in sync: clicking a cluster in one highlights it in the other. Polygon drawing works in either panel.

**Why it matters:**
Spatial annotation is meaningless without seeing the tissue layout. UMAP alone cannot distinguish tumor core from margin, or cortex from medulla.

**Key files touched:**

- `backend/app/services/adata_service.py` — detect and return `spatial` coords alongside UMAP in `get_umap_points()`
- `backend/app/schemas/api.py` — `UmapPoint`: add optional `sx?: number`, `sy?: number`
- `frontend/src/components/UmapCanvas.tsx` — dual-canvas layout or mode toggle; share `displayPoints`
- `frontend/src/app/store.ts` — spatial view mode flag

**Effort estimate:** Large (2 weeks). Coordinate system alignment, shared selection state, and layout are the hard parts.

---

### F-07 · Bulk Annotation Import from CSV

**Priority:** `___________`

**What it is:**
A file-upload flow in the UI that accepts a CSV with two columns (cell barcode + label) and seeds those cells as annotation labels without requiring polygon drawing. Useful for importing pre-computed annotations from Seurat, CellTypist, or a colleague's session.

**Why it matters:**
Users often have existing rough annotations from automated tools that they want to refine interactively. Forcing them to re-draw polygons defeats the purpose of the tool.

**Implementation notes:**

- CSV is parsed client-side (Papa Parse)
- Matched barcodes are sent to a new endpoint `POST /objects/{object_id}/import-labels` which resolves indices
- The result is merged into the existing session's seed labels in `SessionStore`

**Key files touched:**

- `backend/app/api/routes.py` — `POST /objects/{object_id}/import-labels`
- `backend/app/services/adata_service.py` — `resolve_barcode_indices()` to map barcodes → indices
- `frontend/src/components/SessionSidebar.tsx` — file input + import status

**Effort estimate:** Small–Medium (3–4 days).

---

### F-08 · Differential Expression Between Clusters

**Priority:** `___________`

**What it is:**
A panel (or extension of Marker Discovery) that runs a full pairwise or one-vs-rest DE analysis between clusters using Wilcoxon rank-sum test (already available through scanpy). Returns a ranked gene table with log fold-change, p-value, and adjusted p-value. Table is sortable and top genes can be sent directly to the Gene Panel's selected genes list.

**Why it matters:**
Marker discovery currently returns the top-N candidates with no statistical rigor. Full DE with corrected p-values is required for publication-grade annotation decisions.

**Key files touched:**

- `backend/app/services/adata_service.py` — `run_de_analysis()` using `scanpy.tl.rank_genes_groups`
- `backend/app/api/routes.py` — `POST /objects/{object_id}/differential-expression`
- New frontend component: `DEPanel.tsx`
- `frontend/src/App.tsx` — add panel to layout

**Effort estimate:** Medium (1 week). The backend call is straightforward; the table UI with sorting and gene transfer is the bulk of work.

---

### F-09 · Annotation Export to Multiple Formats

**Priority:** `___________`

**What it is:**
A dedicated export panel in the SessionSidebar that lets annotators download annotation results without requiring a full save to `.h5ad`. Export options:

1. **CSV**: barcode + annotation label + confidence score (for all annotated cells)
2. **AnnData obs patch**: a minimal JSON patch compatible with `anndata.obs.update()`
3. **Seurat-compatible TSV**: barcode + label, importable via `read.table()` in R

**Why it matters:**
Many bioinformaticians work in hybrid Python/R environments. The current "save" flow writes back to `.h5ad` in place, which is irreversible and requires server access. A lightweight export supports review workflows without committing.

**Key files touched:**

- `backend/app/api/routes.py` — `GET /objects/{object_id}/export-annotations?format=csv|tsv|json`
- `backend/app/services/sessions.py` — `export_annotations()` using stored session state + propagation snapshot
- `frontend/src/components/SessionSidebar.tsx` — export format selector + download trigger

**Effort estimate:** Small (2–3 days).

---

### F-10 · Project-Level Progress Dashboard

**Priority:** `___________`

**What it is:**
A top-level overview screen (separate from the per-object annotation view) that shows all scanned objects in a table with: object name, cell count, current annotation coverage (% cells annotated), number of clusters, whether a live session exists, last-modified date. Clicking a row opens the object. A summary bar chart shows annotation completeness across the full project.

**Why it matters:**
Large annotation projects span dozens of lineages. Without a dashboard, annotators have no way to track which objects are done, which are in progress, and which haven't been touched.

**Key files touched:**

- `backend/app/api/routes.py` — `GET /objects` extended to include annotation coverage stats
- `backend/app/services/adata_service.py` — `get_annotation_coverage()` per object
- New frontend component: `ProjectDashboard.tsx`
- `frontend/src/App.tsx` — routing between dashboard and annotation view (could be a modal or route)

**Effort estimate:** Medium (1 week).

---

### F-11 · Keyboard Shortcuts & Annotation Productivity

**Priority:** `___________`

**What it is:**
A configurable set of keyboard shortcuts to speed up the annotation workflow:

- `D` — start drawing polygon
- `Escape` — cancel polygon
- `Enter` / `Space` — confirm polygon (open label dialog)
- `1`–`9` — assign recently used labels
- `Z` — undo last polygon
- `Ctrl+S` — save session
- `Ctrl+P` — run propagation with last-used settings
- Click-drag to pan without entering draw mode

Display a keyboard shortcut reference overlay (toggled by `?`).

**Why it matters:**
Drawing 50 polygons per session with mouse-only is fatiguing. Hotkeys reduce clicks by 60–80% for experienced annotators.

**Key files touched:**

- `frontend/src/components/UmapCanvas.tsx` — `useEffect` keyboard listener
- `frontend/src/app/store.ts` — no backend changes needed
- New component: `KeyboardHelp.tsx`

**Effort estimate:** Small (2–3 days).

---

### F-12 · Cell Type Ontology (CL) Integration

**Priority:** `___________`

**What it is:**
Bundle a trimmed version of the Cell Ontology (CL, from OBO Foundry) and add an ontology browser to the cluster label editor. When naming a cluster, the annotator can search the ontology tree to find the canonical CL term (e.g., `CL:0000084` → "T cell"), see its definition and parent terms, and assign it. The CL ID is stored alongside the display name.

**Why it matters:**
Standardized ontology terms are required for data submissions to CellxGene, HCA, and GEO. Without them, annotations are not interoperable across labs.

**Key files touched:**

- New file: `backend/data/cl_ontology_slim.json` (pre-built from OWL; ~10k terms for immune + stromal)
- New backend service: `backend/app/services/ontology.py`
- `backend/app/api/routes.py` — `GET /ontology/search?q=...`
- `frontend/src/components/ClusterLabelEditor.tsx` — ontology search widget
- `backend/app/schemas/api.py` — `ClusterLabelRow`: add `cl_id?: string`

**Effort estimate:** Medium–Large (2 weeks). Ontology parsing and the search UX are the complex parts.

---

### F-13 · QC Metrics Overlay & Cell Filtering

**Priority:** `___________`

**What it is:**
Read standard QC columns from `obs` (`n_genes_by_counts`, `total_counts`, `pct_counts_mt`, doublet scores) and display them in two ways:

1. **UMAP overlay**: color mode "Color by QC metric" with a dropdown (extends F-04)
2. **Filter brush**: a histogram + slider for each metric that hides cells below/above threshold from the UMAP and excludes them from polygon selection

This allows annotators to see which clusters are enriched for low-quality or doublet cells before assigning labels.

**Why it matters:**
Annotating a cluster as "B cell" when it is actually a B+T doublet artifact wastes time and introduces errors. QC overlay is the first thing experienced scRNA-seq analysts check.

**Key files touched:**

- `backend/app/services/adata_service.py` — detect standard QC columns; return in metadata
- `backend/app/schemas/api.py` — `MetadataResponse`: add `qc_columns: list[str]`
- `frontend/src/components/SessionSidebar.tsx` — QC filter sliders
- `frontend/src/app/store.ts` — `qcFilters: Record<string, [number, number]>`; pass to `polygon_select` and UMAP color

**Effort estimate:** Medium (1 week). QC column detection is easy; the filter-brush histogram UI is the harder part.

---

### F-14 · Test Suite (Backend + Frontend)

**Priority:** `___________`

**What it is:**
A foundational test layer covering the highest-risk code paths. No tests exist anywhere in the project today — every blast-radius symbol is unprotected.

**Backend (pytest):**

- Unit tests for `propagation.py` (`run_graph_diffusion`, `run_knn_vote`, `assign_from_scores`) using synthetic AnnData fixtures
- Integration tests for key routes (`/umap`, `/propagate`, `/save`) using a small real `.h5ad` fixture in `backend/tests/fixtures/`
- Tests for `AnnDataService` cache eviction logic

**Frontend (Vitest + Testing Library):**

- Unit tests for store actions that don't require network (`setClusterVisibility`, `updateClusterLabelName`, `reorderSelectedGenes`)
- Mock-fetch integration tests for `api.ts` call shapes

**CI:**

- Add a `pytest` step and `vitest run` step to a GitHub Actions workflow

**Key files touched:**

- New: `backend/tests/` directory structure
- New: `frontend/src/__tests__/` directory
- New: `.github/workflows/ci.yml`

**Effort estimate:** Large (2 weeks to reach meaningful coverage). High long-term ROI for all subsequent features.

---

### F-15 · Annotation Comparison / Diff View

**Priority:** `___________`

**What it is:**
A side-by-side or overlay view that compares two annotation runs (two `cluster_key` columns in the same object, or the same key before and after a propagation step). Shows:

- A confusion-matrix-style table of label changes (how many cells moved from label A to label B)
- A UMAP where cells are colored by agreement (same label = grey, changed = red)
- An export of the diff as CSV

**Why it matters:**
Iterative re-annotation is common: an annotator runs propagation, makes adjustments, runs again. Without a diff view they cannot tell what changed between passes, making it hard to audit or justify annotation decisions.

**Key files touched:**

- `backend/app/api/routes.py` — `POST /objects/{object_id}/annotation-diff` comparing two cluster keys
- `backend/app/services/adata_service.py` — `compare_cluster_columns()`
- New frontend component: `AnnotationDiff.tsx`
- `frontend/src/app/store.ts` — `diffResult` state

**Effort estimate:** Medium (1 week).

---

## Priority Summary Table

Fill in your priorities and we will sequence implementation accordingly.

| #    | Feature                          | Priority | Notes                     |
| ---- | -------------------------------- | -------- | ------------------------- |
| F-01 | Propagation Confidence Overlay   | low      | do not need at this stage |
| F-02 | Violin & Feature Plots           | mid      |                           |
| F-03 | Persistent Session Recovery      | high     |                           |
| F-04 | Observation Metadata Coloring    | high     |                           |
| F-05 | Automated Cell Type Suggestion   | low      | do not need at this stage |
| F-06 | Spatial Transcriptomics View     | high     | very useful               |
| F-07 | Bulk Annotation Import (CSV)     | mid      |                           |
| F-08 | Differential Expression          | high     |                           |
| F-09 | Annotation Export (multi-format) | high     |                           |
| F-10 | Project-Level Dashboard          | high     |                           |
| F-11 | Keyboard Shortcuts               | mid      |                           |
| F-12 | Cell Type Ontology (CL)          | low      | do not need at this stage |
| F-13 | QC Metrics Overlay & Filter      | high     | use standard method first |
| F-14 | Test Suite                       | high     |                           |
| F-15 | Annotation Comparison / Diff     | high     |                           |

---

## Architecture Notes for Implementors

### Backend patterns to follow

- All new routes go in `backend/app/api/routes.py` using the existing `router = APIRouter()` pattern
- New service methods go in `backend/app/services/adata_service.py` on the `AnnDataService` class; use `get_adata(record)` which handles caching
- New Pydantic schemas go in `backend/app/schemas/api.py`
- Settings/config via env vars following the `Settings` dataclass in `backend/app/core/config.py`

### Frontend patterns to follow

- New API calls: add to the `api` object in `frontend/src/app/api.ts`
- New state: add fields + actions to `StoreState` in `frontend/src/app/store.ts`
- New types: add to `frontend/src/app/types.ts`
- New panels: standalone components in `frontend/src/components/`, wired into `App.tsx`
- Style: use existing CSS classes in `frontend/src/styles.css`; panels use `.panel` class, rails use `.right-rail` / `.sidebar-stack`

### Risk areas

- `AnnDataService` is a ~1745-line monolith. New service methods are fine; avoid refactoring it wholesale.
- All session state is in-memory. Until F-03 ships, assume sessions do not survive restarts.
- No tests exist. Until F-14 ships, manually verify every backend change against a real `.h5ad` file.
- Write operations (`save`) overwrite the `.h5ad` in place. Always test save/undo paths carefully.
