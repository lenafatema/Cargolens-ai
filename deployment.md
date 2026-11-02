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

The app is a single Flask service with SQLite and a local upload directory. For a persistent single-instance host, install requirements and run behind a production WSGI server, for example:

```bash
pip install gunicorn
gunicorn --bind 0.0.0.0:${PORT:-8000} app:app
```

Configure the environment variable names above in the host's secret/configuration settings. Set `DATABASE_PATH` and `UPLOAD_DIR` to persistent mounted storage; both must be writable by the app. Set `FLASK_ENV=production` to enable the secure session cookie. Keep uploaded documents private, restrict host access, and configure HTTPS at the host or reverse proxy. The included SQLite/local-file deployment is intended for a demo or single instance; production multi-instance use requires managed PostgreSQL and private object storage. The public repository is https://github.com/lenafatema/Cargolens-ai. The application has not been deployed, so no live application URL is available.
