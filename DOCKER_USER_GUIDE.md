# Docker User Guide

This guide explains how to run the app with Docker.

Use this guide if you want the frontend and backend packaged together as one portable app.

For how to use the app itself after it is running, read:

- [README.md](/Users/binli/Projects/interactive_annotation/README.md)

## 1. Install Docker Desktop

First, install Docker Desktop on your computer.

Download it from:

- https://www.docker.com/products/docker-desktop/

After installation:

1. open Docker Desktop
2. wait until Docker says it is running

You may need to restart your computer after installation.

## 2. Open The Project Folder In A Terminal

You need a terminal window opened in this project folder.

Example:

```bash
cd /path/to/interactive_annotation
```

For example, on this machine the folder is:

```bash
cd /Users/binli/Projects/interactive_annotation
```

Check that you are in the correct folder:

```bash
ls
```

You should see files such as:

- `docker-compose.yml`
- `README.md`
- `backend/`
- `frontend/`
- `data/`

## 3. Make Sure The Data Files Are Present

The Docker app expects the data files to already exist in this repository.

Important paths:

- `data/lineages_current/`
- `data/adata_global.h5ad`

If these files are missing, the app can start but it will not be able to load your objects correctly.

## 4. Build And Start The Docker App

From the project root, run:

```bash
docker compose up --build
```

This command:

- builds the backend image
- builds the frontend image
- starts both containers
- keeps logs visible in the terminal

If you want the app to keep running in the background, use:

```bash
docker compose up -d --build
```

## 5. Check Whether The App Started Successfully

Open another terminal in the same project folder and run:

```bash
docker compose ps
```

You want to see both services listed:

- `backend`
- `frontend`

The frontend row will also show the browser port mapping.

Example:

```text
0.0.0.0:5173->80/tcp
```

That means you should open:

```text
http://127.0.0.1:5173
```

You can also usually open:

```text
http://localhost:5173
```

## 6. How To Check Which Browser Port To Use

The easiest way is:

```bash
docker compose ps
```

Look at the `PORTS` column for the `frontend` service.

If you see:

```text
0.0.0.0:5173->80/tcp
```

then use:

```text
http://127.0.0.1:5173
```

If you started Docker with a custom port, for example:

```bash
INTERACTIVE_ANNOTATION_PORT=5183 docker compose up -d --build
```

then `docker compose ps` will show something like:

```text
0.0.0.0:5183->80/tcp
```

and you should open:

```text
http://127.0.0.1:5183
```

## 7. Confirm The Frontend Is Reachable

You can test the browser page from a terminal:

```bash
curl http://127.0.0.1:5173
```

If you are using a different port, replace `5173` with that port.

If the app is working, the command should return HTML text.

## 8. Stop The Docker App

To stop the containers, press `Ctrl+C` in the terminal where `docker compose up` is running.

If you started the app in background mode, stop it with:

```bash
docker compose down
```

## 9. Start It Again Later

If the images were already built before, you can usually restart with:

```bash
docker compose up
```

or in the background:

```bash
docker compose up -d
```

## 10. Where To Learn The App Workflow

This Docker guide only explains how to start the packaged app.

For the actual app workflow, read:

- [README.md](/Users/binli/Projects/interactive_annotation/README.md)

That file explains:

- scanning and loading objects
- changing UMAP view settings
- drawing polygons
- propagating labels
- saving reannotated objects
- coloring by gene
- previewing dotplots
- renaming clusters
- highlighting clusters in the global view
- moving clusters between objects

## Common Problems

### `docker` Command Is Not Found

Docker Desktop is probably not installed correctly, or the terminal needs to be reopened.

Try:

1. close the terminal
2. reopen it
3. run:

```bash
docker --version
```

### Docker Desktop Is Installed But Containers Do Not Start

Open Docker Desktop and make sure it is actually running.

Then try again:

```bash
docker compose up --build
```

### The Browser Page Does Not Open

Check the published port:

```bash
docker compose ps
```

Then open the port shown for the `frontend` service.

### The App Opens But No Objects Load

Make sure these paths exist in the project folder:

- `data/lineages_current/`
- `data/adata_global.h5ad`

### A Move Takes A Long Time

That can be normal.

Moving a large cluster also recomputes PCA and UMAP for the affected objects, so some actions can take several minutes.
