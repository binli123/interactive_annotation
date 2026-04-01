## Goal

Add three capabilities to the local interactive reannotation app without disrupting the existing polygon propagation workflow:

1. Cluster-level visibility toggles in the `Cluster Names` editor.
2. A gene-examination panel with search, favorites, single-gene UMAP coloring, and marker dotplot preview/save.
3. Scrollable left and right side panels so larger objects and long gene lists remain usable.

## Scope

### Cluster Visibility

- Extend the `Cluster Names` editor rows with a `visible` checkbox.
- Default every cluster to visible whenever a new object or cluster key is loaded.
- Hide unchecked clusters at render time only.
- Keep hidden clusters available for:
  - propagation
  - saving cluster names
  - polygon hit-testing
- Visibility is a frontend display filter, not a backend edit to the object.

### Gene Examination Panel

- Add a dedicated right rail with:
  - search bar
  - gene list for the current object
  - checkbox per gene
  - heart/favorite toggle per gene
  - `Uncheck all` action
- Favorites should sort to the top of the list while preserving search behavior.
- Persist favorites client-side so they survive refreshes.

### Single-Gene UMAP Coloring

- Allow UMAP coloring by expression only when exactly one gene is checked.
- Add a backend path that returns sampled UMAP points with optional gene-expression values attached.
- Keep the existing sampled-point workflow to avoid loading the full matrix into the browser.
- Frontend should switch into a dedicated gene-expression color mode only when the user clicks the trigger button.
- Cluster visibility filters must still apply while gene coloring is active.

### Marker Dotplot

- Use a backend-generated standard Scanpy-style dotplot.
- Group rows by the active cluster key, but if a display-name column exists for that key, use the display names on the y-axis.
- Use the checked genes in the exact client order.
- Support drag-and-drop reordering of the selected genes in the frontend.
- Render the preview below the `Cluster Names` editor.
- Add a save action that writes the PNG beside the loaded object with a sensible default name.

## Backend Changes

- Extend metadata/service APIs with a gene-list endpoint.
- Extend the UMAP endpoint with an optional `gene_name` field and return `gene_expression` for sampled points when requested.
- Add a dotplot endpoint that:
  - validates the selected genes
  - generates a standard built-in Scanpy dotplot
  - returns a preview image payload
  - optionally saves the figure into the lineage object directory
- Keep all new backend work object-scoped and cache-friendly.

## Frontend Changes

- Extend store state for:
  - cluster visibility map
  - gene list / search / favorites / selected genes
  - gene-expression color mode
  - dotplot preview/save result
- Reset or reload these states safely when the object or cluster key changes.
- Preserve current polygon, propagation, and cluster-name-save flows.

## Layout / UX

- Move to a 3-column desktop layout:
  - left rail: object browser + session controls
  - center: UMAP + cluster names + dotplot
  - right rail: gene examination
- Make left and right rails independently scrollable.
- Keep mobile fallback simple by collapsing to a single-column stack.

## Validation

- Backend:
  - Python syntax check
  - route smoke test against one existing lineage object
- Frontend:
  - production build
  - confirm object loads
  - confirm hiding/showing clusters updates immediately
  - confirm single-gene coloring updates immediately after trigger
  - confirm dotplot preview renders and save writes a PNG beside the object
