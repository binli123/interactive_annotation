# Sample Data

No real `.h5ad` files are bundled in this package.

Put a small lineage object here only if you want a private internal smoke test before sending the release to users.

Recommended structure for manual testing:

- copy one small viewable lineage object into `data/lineages_current/`
- start the app with `make up`
- open `http://localhost:5173`
- confirm the object is detected and loads

Do not commit patient or large production data into this folder.
