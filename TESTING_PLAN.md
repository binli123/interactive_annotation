# Interactive Annotation - Manual Testing Plan

This is a walkthrough for a human tester to exercise the app end-to-end. Each section is a self-contained scenario: what to do, what you should see, and what would count as a failure. Work through sections in order the first time - later sections (propagation, save) assume you've already loaded an object from earlier sections.

## 0. Setup

1. Make sure the app is running: `docker compose up -d --build` from the repo root (rebuild is required after any code change - the app does not run off a live dev server).
2. Open the app in a browser: `http://localhost:5173` (or whatever port `INTERACTIVE_ANNOTATION_PORT` is set to).
3. You'll need at least one lineage `.h5ad` object folder, and optionally a global `adata_global.h5ad`, accessible to the backend container (mounted under `./data`). **Use copies of your data, not originals** - several tests in this plan write to disk.
4. The app does **not** auto-load a folder on startup. You must enter a folder path and click Scan every time you open the app fresh.

Record your environment before you start:
- Browser + version:
- Approx. number of cells in the lineage object you're testing:
- Whether a global object is configured:

---

## 1. Load objects (Object Browser)

| Step | Action | Expected result |
|---|---|---|
| 1.1 | Paste the lineage folder path into the "Lineage folder" field, click **Scan**. | The "Detected objects" dropdown populates with one entry per lineage object found, showing lineage name, filename, and cell count. |
| 1.2 | Select an object from the dropdown. | The status pill briefly shows "Working...", then the UMAP, cluster names, and gene panel all populate. The header shows lineage name, cell count, gene count. |
| 1.3 | Select an object marked `[invalid]` (if any exist). | A validation error message is shown instead of loading; app doesn't crash. |
| 1.4 | Re-scan the same folder a second time. | No duplicate entries, no errors. |

**Fail if:** the dropdown stays empty after a successful scan, the app hangs on "Working..." indefinitely, or selecting an object throws a visible error with no explanation.

---

## 2. UMAP visualization - Lineage View

| Step | Action | Expected result |
|---|---|---|
| 2.1 | With an object loaded, confirm you're on the **Lineage View** tab. | Scatter plot renders with points colored by cluster; a legend-free but distinct color per cluster. |
| 2.2 | Change **Embedding** dropdown (if more than one embedding key exists). | UMAP reloads with a progress indication if it takes more than about 1s; layout changes to match new embedding. |
| 2.3 | Change **Cluster key** dropdown. | Points recolor according to the new clustering; Cluster Names table below updates to match. |
| 2.4 | Adjust **Overall max points**, **Min/cluster**, **Cluster-wise cap**, then click **Reload UMAP**. | Point count in the "Displayed points" counter (top of canvas) changes accordingly. A progress bar should appear if the object is large. |
| 2.5 | Drag **Dot size** and **Transparency** sliders. | Points resize/fade live, no reload needed. |
| 2.6 | Toggle **Flip horizontally** / **Flip vertically**. | Plot mirrors accordingly; polygons (if any) mirror too, consistently. |
| 2.7 | Click **Reset view**. | Viewport re-centers/re-zooms to fit all currently displayed points. |
| 2.8 | Hover over a point. | Tooltip shows `cell_id`, `cluster`, `annotation`, and (if colored by gene) the expression value. |
| 2.9 | In the **Cluster Names** table, uncheck a cluster's **Show** checkbox. | That cluster's points disappear from the UMAP; displayed point count drops. |

**Fail if:** the canvas is blank with a valid object loaded, the browser tab becomes unresponsive during reload, or point count/color doesn't match the selected cluster key.

---

## 3. UMAP visualization - Global View

*Only testable if a global object is configured (the "Global View" tab is hidden otherwise).*

| Step | Action | Expected result |
|---|---|---|
| 3.1 | Click the **Global View** tab (top of canvas) or the **Global** tab in the sidebar. | Canvas switches to a combined scatter of subsampled points from *all* lineage objects, not just the currently selected one. |
| 3.2 | Change **Embedding**/**Cluster key**/sampling controls, click **Reload Global UMAP**. | Plot reloads; "Displayed global points" counter updates. |
| 3.3 | Go back to Lineage View, open the Cluster Names table, click **Highlight** next to a cluster row. | Switching to Global View shows that cluster's cells highlighted in color against all other cells dimmed gray; a status line reports "Highlighting `<name>` with N visible matches." |
| 3.4 | With a highlight active, click **Restore cluster colors** (sidebar or Cluster Names header). | Global view returns to standard per-cluster coloring; highlight status message disappears. |

**Fail if:** Global View shows only the currently-selected lineage's cells instead of a combined subset from every lineage, or highlighting doesn't visibly distinguish the source cluster.

---

## 4. Gene selection and highlighting

| Step | Action | Expected result |
|---|---|---|
| 4.1 | In the Gene Examination panel (right rail), type a partial gene symbol into **Search genes**. | Gene list filters live, case-insensitively. |
| 4.2 | Check 2-3 genes from the list. | Chips appear under "Selected Genes"; count updates. |
| 4.3 | Click the heart icon next to a gene (unfilled heart). | Turns into a filled heart; that gene sorts to the top of the list even after clearing the search box. |
| 4.4 | Paste a list of gene symbols (comma/space/newline separated, mix in 1-2 fake names) into **Paste gene list**, click **Check pasted genes**. | Feedback message reports how many matched vs. not found; matched genes get checked automatically. |
| 4.5 | With exactly one gene checked, click **Color UMAP by gene**. | UMAP recolors on a continuous scale by that gene's expression; hover tooltip shows the expression value. A progress bar should appear while this loads on a large object. |
| 4.6 | With 2+ genes checked, click the small highlight-toggle circle on one chip to pick which one drives coloring, then **Color UMAP by gene** again. | Only the chosen gene drives coloring (confirm via tooltip values). |
| 4.7 | Click **Restore cluster colors**. | UMAP reverts to categorical cluster coloring. |
| 4.8 | Drag a selected-gene chip to reorder it in the list. | Order changes and persists (affects dotplot gene order later). |
| 4.9 | Click **Preview dotplot**, then **Save dotplot beside object**. | An image renders in a new "Marker Dotplot" panel below the UMAP; save reports a file path written next to the object. |
| 4.10 | Switch to Global View, select a gene, click **Color UMAP by gene**. | Global canvas colors by gene expression across the combined subset; switching back to Lineage View preserves its own independent gene-coloring choice. |

**Fail if:** coloring never changes after clicking "Color UMAP by gene", the app freezes with no progress indicator on a large object, or gene coloring on one view (lineage/global) leaks into the other.

---

## 5. Marker discovery (Lineage View only)

| Step | Action | Expected result |
|---|---|---|
| 5.1 | In the Gene panel, under **Marker Discovery**, set candidate gene count (N). | Field accepts 1-200. |
| 5.2 | Check 1+ clusters as discovery targets. | Checkbox list mirrors currently-visible clusters (respects Cluster Names "Show" toggles). |
| 5.3 | Click **Discover marker genes**. | A result message lists candidate genes added; those genes should now appear checked in the Selected Genes list. |
| 5.4 | Switch to Global View. | Marker Discovery section shows "available only in Lineage View" instead of controls. |

---

## 6. Draw polygon + propagate labels

| Step | Action | Expected result |
|---|---|---|
| 6.1 | On Lineage View, click **Draw polygon**. | Button label changes to "Stop drawing"; clicking on the canvas starts placing vertices (crosshair-style overlay becomes interactive). |
| 6.2 | Click 4-5 points on the canvas to outline a region, then double-click the last point (or click **Close polygon**). | A closed polygon boundary renders; a new entry appears in the sidebar **Polygons** section with a cell count and a "Leiden mix" summary. |
| 6.3 | In the new polygon's card, set a **Cluster ID** and **Cluster name**. | Fields accept free text; polygon boundary color updates to match its assigned identity. |
| 6.4 | Click **Undo point** while mid-draw on a second polygon. | Removes only the last placed vertex. |
| 6.5 | Click **Edit vertices** on an existing polygon, drag a vertex, then **Stop editing**. | Polygon shape updates; cell count recalculates. |
| 6.6 | Draw a second polygon with a different Cluster ID, leave "Include in propagate" checked on both. | Sidebar shows both polygons. |
| 6.7 | Uncheck **Include in propagate** on one polygon. | That polygon is excluded from the next propagation run (verify via results afterward). |
| 6.8 | In the **Propagate** section, choose Method = Graph diffusion, Scope = Whole lineage, leave default thresholds, click **Propagate selected polygons**. | A progress bar appears (for anything but a tiny object) with a label like "Propagating labels"; on completion, a "Propagation finished" modal shows assigned/eligible cell counts. |
| 6.9 | Click **Not now** on the modal. | Modal dismisses; the **Session** panel in the sidebar still shows the propagation summary (Assigned/Eligible/Labels breakdown). |
| 6.10 | Change UMAP color mode to **Color by annotation**. | Points inside/near propagated regions show the new label colors; unassigned cells show "Unassigned". |
| 6.11 | Click **Reset propagation**. | Clears the propagation result and annotation coloring reverts to showing no propagated labels. |
| 6.12 | Repeat propagation with Method = kNN vote and a smaller Scope (e.g. "Polygon only"). | Different (typically more conservative) assignment - fewer or equal assigned cells vs. whole-lineage graph diffusion. |
| 6.13 | Try **Annotate all** checked vs. unchecked with the same polygons. | With it checked, min score/margin fields are disabled and every eligible cell gets a label regardless of confidence; unchecked respects the thresholds (fewer assigned cells expected). |

**Fail if:** propagation never completes / hangs with no progress feedback, the polygon's included/excluded flag doesn't affect results, or the app crashes when a polygon has too few points (test with a 3-vertex triangle as an edge case).

---

## 7. Reference-based propagation

| Step | Action | Expected result |
|---|---|---|
| 7.1 | In **Propagate (Reference-Based)**, set an output name (e.g. `refprop_test`). | Free text field. |
| 7.2 | Check 1+ clusters as **Reference** and 1+ *different* clusters as **Source**. | Checkboxes are independent per row (a cluster could technically be checked in both, though normally you'd pick disjoint sets). |
| 7.3 | Click **Apply kNN vote to source clusters**. | Result message reports the new cluster key written and how many source cells were reassigned. |

---

## 8. Cluster naming / renaming

| Step | Action | Expected result |
|---|---|---|
| 8.1 | In the **Cluster Names** table, type a label into a cluster's text field. | Text updates locally; not yet saved. |
| 8.2 | Rename 2-3 clusters, then click **Save names to object**. | A progress indicator appears briefly (this writes to disk); success message reports "Saved N cluster names to `<column>`." |
| 8.3 | Reload the page, re-select the same object. | Renamed labels persist (confirms the write actually landed on disk, not just in memory). |
| 8.4 | Click **Undo last object change** immediately after a save. | Reverts the most recent on-disk change; status message describes what was undone. Button is disabled when nothing is available to undo. |
| 8.5 | Click **Move to** next to a cluster row, pick a destination object, review the preview (cells to move, overwritten IDs, assigned cluster ID/label). | Preview populates without committing anything. |
| 8.6 | Click **OK** to confirm the move (only if you're using disposable test copies!). | Cluster's cells are moved into the destination object's file; result message confirms cell count moved (and any overwritten count). |
| 8.7 | Click **Cancel** on the move dialog instead. | No changes made; dialog closes cleanly. |

**Fail if:** renamed labels don't survive a page reload, saving one cluster's label resets *other* clusters' labels back to their raw IDs (a known historical bug - check this specifically by renaming only a subset of clusters and confirming the untouched ones keep their prior names), or Undo silently does nothing.

---

## 9. Session save and crash recovery

| Step | Action | Expected result |
|---|---|---|
| 9.1 | After a successful propagation (section 6), click **Save reannotated object** in the Session panel. | Progress bar appears ("Saving reannotated object"); on completion, a file path appears under the Session panel. |
| 9.2 | Reload the page without saving a *new* propagation run. | No "Unsaved session found" banner (nothing pending). |
| 9.3 | Run a fresh propagation, then **without saving**, restart the backend container: `docker compose restart backend` (or equivalent), then reload the page and re-select the same object. | An orange **"Unsaved session found"** banner appears near the top, summarizing seed cells, polygon count, and labels, noting "propagation available" if applicable. |
| 9.4 | Click **Restore session**. | Banner disappears; polygons, propagation result, and Session summary reappear as if nothing happened. |
| 9.5 | Click **Save reannotated object** after restoring. | Save succeeds (this previously could fail - confirm no "Run propagation before saving" error appears). |
| 9.6 | Alternatively, from the recovery banner, click **Discard**. | Banner disappears; nothing is restored; session starts clean. |
| 9.7 | Click **Reset session**. | Clears the current in-progress session (polygons/propagation) without touching the saved object file. |

**Fail if:** the recovery banner never appears after a simulated crash, restoring loses data (compare assigned cell counts before/after), or Save fails on a restored session.

---

## 10. Differential expression

| Step | Action | Expected result |
|---|---|---|
| 10.1 | In the **Differential Expression** panel, check 1+ **Target clusters**. | "Run DE Analysis" button becomes enabled. |
| 10.2 | Leave **Reference clusters** empty, click **Run DE Analysis**. | Progress/wait, then a results table appears with gene, log2FC, adjusted p-value, mean target/reference expression, sorted meaningfully. Target/reference cell counts and method are shown above the table. |
| 10.3 | Check specific reference clusters instead of leaving empty, re-run. | Results change (comparison is now target vs. only the checked reference clusters, not "all others"). |
| 10.4 | Click **Add top 20 to Gene Panel**. | Those 20 genes become checked in the Gene Examination panel (verify by scrolling the gene panel / checking selected-gene chips). |

---

## 11. Annotation diff

*Requires at least two cluster/annotation columns to exist on the object - e.g. run this after you've saved at least one propagation or cluster-rename pass so a second column exists.*

| Step | Action | Expected result |
|---|---|---|
| 11.1 | If fewer than 2 cluster columns exist, confirm the panel shows a message asking you to save annotations first, instead of broken controls. | |
| 11.2 | Pick Column A and Column B (e.g. original Leiden cluster vs. your saved reannotation column), click **Compare columns**. | Summary cards show total/changed/unchanged cell counts and percentage. A transition table lists the top label-to-label changes by cell count. |
| 11.3 | Pick the same column for both A and B. | "Compare columns" stays disabled (A and B must differ). |

---

## 12. Export annotations

| Step | Action | Expected result |
|---|---|---|
| 12.1 | With an object selected, click **Export CSV** (top-right of the header). | Browser downloads a CSV file containing per-cell annotation data. |
| 12.2 | Open the downloaded file. | Contains cell IDs and label/annotation columns matching what's shown in the app. |

*Note: the backend also supports TSV and JSON export formats via the API, but no button in the current UI triggers them - out of scope for UI testing unless you want to test the API directly (`GET /api/objects/{id}/export-annotations?fmt=json`).*

---

## 13. Project dashboard

| Step | Action | Expected result |
|---|---|---|
| 13.1 | Click **Dashboard** (top-right of header, requires an object to be selected). | Modal opens showing total objects, total cells, count of annotated objects, and average annotation coverage across all detected lineage objects. |
| 13.2 | Review the per-lineage table (cells, clusters, annotated count, coverage bar). | Coverage bar/percentage roughly matches what you'd expect given your propagation/save actions so far. |
| 13.3 | Click **Open** on a different lineage's row. | Dashboard closes; that object loads in the main view. |
| 13.4 | Click **Close** or click outside the modal. | Dashboard closes without navigating away. |

---

## 14. Cross-cutting checks

| Step | Action | Expected result |
|---|---|---|
| 14.1 | Trigger any of the slow operations (UMAP reload on a large object, gene coloring, propagation, save) and click **Stop** on the status pill while it's running. | The operation is cancelled; UI returns to a usable, non-stuck state (no permanent "Working..." lock). |
| 14.2 | Resize the left/right side panels by dragging the vertical resize handles. | Panels resize smoothly between their min/max bounds; layout doesn't break. |
| 14.3 | Switch between Lineage View and Global View repeatedly while an operation is mid-flight. | No crashes; each view keeps its own independent state (polygons, color mode, gene selection). |
| 14.4 | Load a very large object (largest one you have) and time: UMAP load, gene coloring, propagation, save. | Record actual times below - compare against expectations if you have a baseline from prior testing. |
| 14.5 | Deliberately trigger an error (e.g. save with no propagation result, or select an invalid object). | Error is shown in the status pill area with a clear message - app doesn't silently fail or crash. |

Timing log (fill in):

| Operation | Object / cell count | Time observed | Progress bar shown? |
|---|---|---|---|
| UMAP load | | | |
| Gene coloring | | | |
| Propagation | | | |
| Save | | | |

---

## Known current limitations (not bugs)

- **Spatial View** and **Obs Metadata Coloring / QC Metrics** panels exist in the codebase but are currently disabled in the UI (commented out) - don't test these unless a developer has explicitly re-enabled them.
- Export only exposes CSV in the UI; TSV/JSON exist only at the API level.
- Saving a propagation to disk always requires an explicit **Save** click - nothing auto-writes to the `.h5ad` file. Only the crash-recovery *sidecar* (used to restore an in-progress session) is written automatically.

## Reporting a bug

For each issue found, note:
1. Section/step number from this plan.
2. Object used (name, approx. cell count).
3. Exact steps to reproduce.
4. What you expected vs. what happened.
5. Any error text shown in the status pill, or browser console errors (open DevTools, then the Console tab).
6. Screenshot if the issue is visual.
