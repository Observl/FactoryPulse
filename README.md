# FactoryPulse

AI-powered industrial equipment health & maintenance decision platform. Windows desktop MVP (Electron + React + TypeScript + FastAPI).

> **Status: v0.1.0 scaffold.** Dashboard and API contain **synthetic demonstration data**. No trained failure model, optimization engine, Excel importer, AI API or production installer is implemented yet.

## Requirements

- Node.js LTS and npm
- Python 3.11+ (recommended 3.12)

## Run locally

Terminal A (API):

```powershell
cd backend
python -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Terminal B (desktop):

```powershell
npm install
npm run dev
```

Open http://127.0.0.1:8000/api/health to verify the API. When the backend is unavailable, the dashboard falls back to bundled demo data.

## Build frontend

```powershell
npm run build
```

**Note:** This builds the web assets only. Electron installer packaging and bundling the Python backend are tracked in [Issue #11](https://github.com/Observl/FactoryPulse/issues/11).

## Project structure

- `electron/`: Electron desktop process
- `src/`: React UI, dashboard and navigation
- `backend/`: FastAPI demonstration service

## Roadmap

See [GitHub Issues](https://github.com/Observl/FactoryPulse/issues). All risk scores and equipment records in this scaffold are synthetic and must not be used as evidence of predictive accuracy.
