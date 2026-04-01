# Interactive Annotation Docker Desktop Bundle

This package is set up for local use with Docker Desktop on macOS, including MacBook Air/Pro on Apple Silicon and Intel.

## Why the extra files exist

- `Makefile`: gives the user short commands instead of remembering full Docker Compose syntax.
- `scripts/create_release_bundle.sh`: creates a clean zip bundle for end users, without `node_modules`, build artifacts, or local junk.
- `scripts/release_test_bundle.sh`: unpacks the generated zip into a temporary directory, starts it on a test port, and checks that the release actually serves.

## What the user needs

- Docker Desktop installed
- lineage `.h5ad` objects placed under `./data/lineages_current`

## Quick start for users

1. Download the release zip or clone the repo.
2. Unzip it and open a terminal in this folder.
3. Put lineage `.h5ad` files into `data/lineages_current`.
4. Start the app:

```bash
make up
```

5. Open:

```text
http://localhost:5173
```

The app defaults to `/data/lineages_current` inside the containers, which maps to `./data/lineages_current` on the user's machine.

## Common commands

Start:

```bash
make up
```

Stop:

```bash
make down
```

Logs:

```bash
make logs
```

Rebuild after code changes:

```bash
make up
```

Create a distributable zip bundle:

```bash
make release
```

Validate the release zip before sending it out:

```bash
make release-test
```

## Do users need to clone the repo?

No. Cloning is optional.

Users can either:

1. clone the repo, then run `make up`
2. download a release zip produced by `make release`, unzip it, then run `make up`

For non-technical users, the release zip is the better delivery format.

## How to test the app locally yourself

Fastest path:

1. Put one or more real `.h5ad` lineage objects into `data/lineages_current`.
2. Run:

```bash
make up
```

3. Open `http://localhost:5173`.
4. Confirm the object list appears and at least one object loads.
5. When finished:

```bash
make down
```

Release validation path:

1. Run:

```bash
make release-test
```

2. That command will:
   - create a fresh release zip
   - unpack it into a temporary directory
   - start the packaged app on port `5183`
   - verify `http://127.0.0.1:5183/` and `/api/health`

If you want to inspect that tested bundle manually afterward, unzip the release from `releases/` and run it yourself with:

```bash
INTERACTIVE_ANNOTATION_PORT=5183 docker compose up -d --build
```

## Notes

- The frontend is served by `nginx` on port `5173`.
- API requests go through `/api` to the FastAPI backend.
- The backend reads and writes objects in place inside `./data`.
- For large `.h5ad` objects, first launch may take some time.

## macOS compatibility

Yes. This setup is suitable for a MacBook using Docker Desktop.

- `node:20-alpine`, `nginx:alpine`, and `python:3.10-slim` are multi-arch images.
- Docker Desktop will run this on both Apple Silicon and Intel Macs.
- Performance will depend mostly on RAM and the size of the `.h5ad` files.
