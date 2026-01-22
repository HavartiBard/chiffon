# Phase 7 UI Deployment

## Overview

- **Dashboard API**: FastAPI proxy sitting in front of the orchestrator, exposing chat, plan, approval, and execution routes.
- **Frontend**: React/Vite UI that talks to the dashboard via HTTP and WebSocket.
- **Real-time Layer**: Socket.IO endpoint at `/ws` streams execution events to the browser.

## Docker Compose

### Start individual services

```bash
# Dashboard API (FastAPI)
docker-compose up -d dashboard

# Frontend (Vite dev server)
docker-compose up -d frontend
```

### Start everything

```bash
docker-compose up
```

### Endpoints

- UI: http://localhost:3000
- Dashboard API: http://localhost:8001
- Orchestrator API: http://localhost:8000

Front-end requests are proxied to the dashboard API. The dashboard, in turn, calls the orchestrator and exposes `/ws` for Socket.IO connections.

## Manual Setup (without Docker)

### Dashboard

```bash
poetry install
poetry run uvicorn src.dashboard.main:app --port 8001
```

### Frontend

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 3000
```

## Health Checks

- Dashboard: `http://localhost:8001/health`
- Frontend: `http://localhost:3000`

## Notes

- Ensure `ORCHESTRATOR_URL` points to `http://orchestrator:8000` when running in Docker.
- The Socket.IO client should connect to `/ws/socket.io` (Vite proxies `/ws` to the dashboard).
