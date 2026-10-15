# FactoryPulse · MVP v0.2.0

Windows-oriented industrial equipment health monitoring and maintenance decision-support desktop prototype.

> **Data honesty:** The provided Excel test workbook is synthetic. Risk scores come from its **08_风险评分演示** sheet, not from a trained ML model. The maintenance simulation is a deterministic greedy heuristic with an explicit 60% assumed risk reduction; it is not validated production optimization and does not prove ROI.

## Implemented

- Electron + React + TypeScript Dashboard (orange #F97316)
- Excel workbook import, schema and foreign-key validation, SQLite persistence
- 12-device demonstration overview, warning cards, risk chart and monitoring readings
- Strategy laboratory: scenario budget, staff and downtime constraint filtering; 3 comparison strategies
- Developer settings: provider, HTTPS base URL, model ID, masked API key, connection test
- FastAPI endpoints, smoke tests and GitHub Actions CI

## Not yet implemented

- Trained failure prediction, feature attribution, grounded AI explanations and Copilot
- Optimized staff/order Gantt scheduling, Excel export, packaged Windows installer
- Secure persistent API key storage (currently only process memory, or backend environment variable)

## Requirements

Node.js 22 LTS, Python 3.12.

## Windows Quick Start

Clone this repository and open **two PowerShell terminals** from its root.

Backend (terminal 1):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Desktop (terminal 2):

```powershell
npm install
npm run dev
```

The Electron window should open at the local development app. Alternatively run `npm run web` and visit http://127.0.0.1:5173.

1. Download the previously supplied **FactoryPulse_完整功能测试数据与字段字典.xlsx** workbook.
2. Open **设备管理**, click **选择测试Excel文件**, and import it.
3. Check **设备总览** for 12 devices and monitoring trends.
4. Open **维护策略** and run each strategy, observing budget and downtime constraints.
5. Open **开发者设置** and enter your AI API provider, base URL, model and key. Save first, then use **测试连接**. This only tests the endpoint; it does not enable Copilot yet.

If Windows PowerShell blocks virtual-environment activation, use the `.venv\Scripts\python.exe` commands shown above; activation is not necessary.

## API and data

API documentation: http://127.0.0.1:8000/docs

- `POST /api/import`: multipart form field `file` (max 8 MB, .xlsx)
- `GET /api/overview`, `GET /api/records/{table_name}`
- `POST /api/simulate`
- `GET/POST /api/developer/settings`, `POST /api/developer/test-connection`

Imported data persist to `~/.factorypulse/factorypulse.sqlite3`. Do not upload confidential production data to unreviewed demo builds. Imported data overwrite previously imported data in the eight business tables.

The developer API key stays in **backend process memory**; for scripted launches you can instead set `FACTORYPULSE_AI_API_KEY`. Do not commit keys to GitHub or store them in Excel. The connection tester sends a minimal prompt to the user-configured external endpoint.

## Checks

```powershell
npm run build
python -m pip install -r backend/requirements.txt pytest
python -m pytest -q
```

Continuous integration: [GitHub Actions](https://github.com/Observl/FactoryPulse/actions). These checks must pass before treating the MVP as verified.

Work items: [Issues](https://github.com/Observl/FactoryPulse/issues).
