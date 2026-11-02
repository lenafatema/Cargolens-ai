# CargoLens AI

CargoLens is a customs shipment document review demo. It supports shipment intake, invoice/packing-list/bill-of-lading upload, AI-assisted structured extraction, human correction and confirmation, cross-document checks, manager approval, and verified CSV export.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`. Add `OPENAI_API_KEY` to enable extraction for searchable document text. With no provider key or on extraction failure, the document is routed to manual review. See [deployment.md](deployment.md) for environment variable names, demo accounts, and deployment notes.

## Deploy a demo

The repository includes a Render Blueprint in `render.yaml`. It creates a free demo web service; the free service sleeps when idle and uses ephemeral storage, so uploaded documents and reviewer edits are not durable. See the deployment guide before using it with non-demo data.

## Demo access

- Executive: `reviewer@cargolens.demo` / `Review2026!`
- Manager: `manager@cargolens.demo` / `Manager2026!`

Seed records are fictional. Never use the demo passwords or development configuration on a public deployment.

## Tests

```bash
python -m unittest discover -s tests -v
```

This is a single-instance demo using SQLite and local file storage. Image-only scans, production-grade OCR, managed database/object storage and live deployment are outside the current scope.
