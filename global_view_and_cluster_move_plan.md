## Goal

Add two new capabilities to the interactive annotation app:

1. A dual-view UMAP workflow that can switch between the active lineage object and a fixed global object at `data/adata_global.h5ad`.
2. An in-place cluster transfer workflow that moves all cells from one lineage-specific object into another lineage-specific object.

## Requested Product Changes

### Global / Comparative View

- Add a center-stage tab switcher with:
  - `Lineage View`
  - `Global View`
- Add matching tabs inside the left-side `View` panel so each view has its own UMAP parameters.
- Keep the default parameter values aligned between the two views:
  - embedding key
  - cluster key
  - max points
  - min per cluster
- In `Cluster Names`, add a per-cluster action that highlights the matching cells inside the global UMAP:
  - highlighted cells rendered in saturated cluster color
  - all non-highlighted cells rendered in muted grey
  - matching performed by `cell_id`
  - display still respects the current global-view sampling limits
- Add a `Restore cluster colors` button beside `Save names to object` so the global highlight mode can be cleared without using the gene panel.

### Cross-Object Cluster Move

- In `Cluster Names`, add a per-cluster `Move to` action.
- Clicking `Move to` opens a lightweight confirmation popup with a destination-object dropdown.
- Confirming moves every cell in that cluster from the current source object into the destination object.
- The move is in-place and updates both `.h5ad` files.
- Moved cells are written into the current cluster key on the destination object.
- The destination display-name value should copy the source cluster display name and append:
  - `(from <source object name>)`

## Assumptions

- `data/adata_global.h5ad` is the fixed global comparison object for this app session.
- The lineage-specific objects and the global object all share `cell_id`, `X_umap`, and the same gene space.
- The cluster move operation is only safe when source and destination objects have matching `var_names`.
- The global highlight action is read-only; it does not edit either object.
- The cluster move action should be conservative rather than implicit when data compatibility is unclear.

## Necessary Safeguards

### Global View

- If the global object is missing or unreadable, expose a clear error and disable highlight actions.
- If a highlighted lineage cluster has no matching `cell_id` values in the global object, return a non-fatal result and show zero highlighted cells.
- Ensure highlighted cells are preferentially retained in the sampled global display payload so the requested comparison is actually visible.

### Cluster Move

- Abort the move if source and destination have different `var_names`.
- Abort the move if the source cluster key does not exist in the destination and cannot be created safely.
- Abort the move if the destination already contains the same cluster ID under the target cluster key.
  - merging by default is too risky because identical IDs may mean different biology in different objects
- Drop or rebuild object-level graph matrices that become invalid after row removal / insertion.
  - keeping stale `obsp` shapes would corrupt the files
- Refresh object caches after each successful move so the UI does not read stale AnnData instances.

## Backend Work

- Add fixed global-object discovery/configuration support.
- Add global metadata and global UMAP endpoints.
- Add a global highlight endpoint that:
  - takes source object ID, source cluster key, source cluster ID
  - finds matching `cell_id` values in the global object
  - returns a sampled global UMAP payload with `is_highlighted`
- Add a move-cluster endpoint that:
  - validates compatibility
  - removes source-cluster cells from the source object
  - appends them to the destination object
  - updates the destination cluster key and display column
  - writes both objects back safely

## Frontend Work

- Extend store state with:
  - active center view tab
  - per-view UMAP parameters
  - global metadata
  - global points
  - global highlight state
  - move-cluster modal state
- Add tab UI in:
  - center canvas region
  - left `View` panel
- Add per-cluster action buttons in `Cluster Names`:
  - `Highlight in global`
  - `Move to`
- Add a modal for destination-object selection and move confirmation.
- Add a local restore action near cluster-name save to clear global highlighting.

## UX Decisions

- Triggering `Highlight in global` should also switch the center canvas to `Global View`.
- The existing lineage polygon workflow remains unchanged and only applies in `Lineage View`.
- The global canvas stays view-only.
- The new `Restore cluster colors` button clears only the global highlight override; it should not modify gene-panel state.

## Validation

- Backend:
  - Python syntax check
  - route smoke tests for global metadata, global UMAP, highlight, and cluster move validation paths
- Frontend:
  - production build
  - confirm tab switching works
  - confirm highlight switches to global view and renders highlighted points
  - confirm restore clears the highlight override
  - confirm move modal appears and successful moves refresh the object list

## Open Risk To Handle Conservatively

- The instruction says to append the moved cluster ID “to the bottom”.
  - The current UI sorts cluster rows, so preserving “bottom” literally requires changing row ordering semantics.
  - Implementation should preserve a stable backend row order where practical, but must prioritize correctness over cosmetic ordering.
