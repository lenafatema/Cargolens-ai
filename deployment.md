# CargoLens AI deployment guide

Project repository: https://github.com/lenafatema/Cargolens-ai


## Prerequisites

- Python 3.11 or newer
- pip
- A compatible OpenAI API key for AI extraction (optional; manual entry remains available without it)

## Run locally

1. Clone the project and open its root folder.
2. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Set a unique session secret. Add the following names to your shell environment or a local `.env` file (never commit `.env`):

   ```text
   SECRET_KEY
   DATABASE_PATH
   UPLOAD_DIR
   OPENAI_API_KEY
   OPENAI_MODEL
   OPENAI_BASE_URL
   FLASK_ENV
   PORT
   ```

   `OPENAI_API_KEY` is optional. `OPENAI_MODEL` defaults to `gpt-4o-mini`, and `OPENAI_BASE_URL` defaults to `https://api.openai.com/v1`. Without the key, the product stores the document and routes it to manual review. Text-based PDF extraction uses PyMuPDF. Image-only scans are not OCR processed in this build.

5. Start the server:

   ```bash
   python app.py
   ```

   SQLite is initialized on first startup and seeded with three synthetic shipments. Open `http://127.0.0.1:5000`.

6. Run the automated checks:

   ```bash
   python -m unittest discover -s tests -v
   ```

## Demo accounts

- Executive: `reviewer@cargolens.demo` / `Review2026!`
- Manager: `manager@cargolens.demo` / `Manager2026!`

The demo database is local-only. Change demo credentials and set a strong `SECRET_KEY` before exposing a deployment. Sample company names and shipment records are fictional.

## Deployment

The repository includes a Render Blueprint in `render.yaml`. To create a public demo, sign in to Render, choose **New → Blueprint**, connect `lenafatema/Cargolens-ai`, and apply the blueprint. It builds the Flask app, runs Gunicorn, generates a `SECRET_KEY`, enables production cookie settings, and checks `/health`. Add `OPENAI_API_KEY` in the service environment if AI extraction is required; it is optional for manual review. Render provides the live URL after the service becomes healthy.

The Blueprint uses a free single instance. Render free web services spin down after 15 idle minutes, and their local filesystem is ephemeral; SQLite changes and uploaded files are lost on spin-down, restart or redeploy. Sample records are seeded again at startup, but reviewer changes and uploaded files will be lost. See [Render free plan limitations](https://render.com/docs/free). For a durable single-instance demo, use a paid service with a persistent disk and set `DATABASE_PATH` and `UPLOAD_DIR` to paths on that disk. For production multi-instance use, migrate to managed PostgreSQL and private object storage, configure retention and backups, and restrict access to uploaded trade documents. The application has not been deployed yet, so no live URL is available.
