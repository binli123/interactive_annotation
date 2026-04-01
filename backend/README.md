# Interactive Annotation Backend

Local API for lineage-object discovery, UMAP serving, polygon-based seeding,
graph-aware label propagation, and saving reannotated `.h5ad` outputs.

## Dev

```bash
cd /Users/binli/Projects/uc_reannotating/interactive_annotation/backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Notes

- The scientific stack already exists in `st_env`, but `fastapi` and `uvicorn`
  may need to be installed into the runtime you use to start the server.
- The service layer is separated from the HTTP layer so the data logic can be
  tested without the API server itself.
