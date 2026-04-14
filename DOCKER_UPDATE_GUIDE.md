# Docker Update Guide

Use this guide when you already have an older Docker bundle and want to replace it with a newer one.

## 1. Keep Your Data First

If your old bundle folder contains your real data, do not delete it yet.

Typical paths to keep:

- `data/lineages_current/`
- `data/adata_global.h5ad`

If needed, copy the whole `data/` folder somewhere safe before continuing.

## 2. Stop The Old App

Open a terminal in the old bundle folder:

```bash
cd /path/to/old/interactive_annotation_bundle
```

Stop the old containers:

```bash
docker compose down --remove-orphans
```

This frees the old app from port `5173` and removes the old running containers.

## 3. Delete The Old Bundle Folder

Only do this after the old app is stopped and your `data/` folder is safe.

Example:

```bash
rm -rf /path/to/old/interactive_annotation_bundle
```

## 4. Unzip The New Bundle

Move the new release zip to the location you want, then unzip it.

Example:

```bash
unzip interactive_annotation_bundle_YYYYMMDD_HHMMSS.zip
cd interactive_annotation_bundle
```

## 5. Put Your Data Into The New Bundle

If the new bundle does not already contain your real data, copy your saved `data/` folder into the new bundle folder.

The new bundle should end up with:

- `interactive_annotation_bundle/data/lineages_current/`
- `interactive_annotation_bundle/data/adata_global.h5ad`

## 6. Start The New App

From the new bundle folder, run:

```bash
docker compose up -d --build
```

## 7. Confirm It Is Running

Check container status:

```bash
docker compose ps
```

Check backend health:

```bash
curl http://127.0.0.1:5173/api/health
```

If the app is running, open:

```text
http://127.0.0.1:5173
```

You can also usually use:

```text
http://localhost:5173
```

## 8. If Port 5173 Still Looks Busy

That usually means the old app was not stopped.

Go back to the old bundle folder and run:

```bash
docker compose down --remove-orphans
```

Then return to the new bundle folder and run:

```bash
docker compose up -d --build
```
