import csv
from decimal import Decimal, InvalidOperation
import io
import os
import re
import secrets
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, Response, abort, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE = Path(__file__).parent
DB_PATH = os.environ.get("DATABASE_PATH", str(BASE / "cargolens.db"))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE / "uploads")))
ALLOWED = {"pdf", "png", "jpg", "jpeg", "txt", "csv"}
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-change-this")
if os.environ.get("FLASK_ENV") == "production" and not os.environ.get("SECRET_KEY"):
    raise RuntimeError("SECRET_KEY must be configured in production")
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('executive','manager')));
CREATE TABLE IF NOT EXISTS shipments(id INTEGER PRIMARY KEY, ref TEXT UNIQUE NOT NULL, importer TEXT NOT NULL, supplier TEXT NOT NULL, origin TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'In review', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id), kind TEXT NOT NULL, filename TEXT NOT NULL, stored_name TEXT NOT NULL, extracted_json TEXT NOT NULL DEFAULT '{}', confidence REAL NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'Needs review', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS edits(id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id), user_id INTEGER NOT NULL REFERENCES users(id), field TEXT NOT NULL, old_value TEXT, new_value TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id), user_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
"""

SAMPLE = [
    ("SHP-24811", "Northstar Components Ltd", "Asterion Controls GmbH", "Germany", [
        ("Commercial invoice", "Invoice CI-8842 · 2026-10-28", {"invoice_number":"CI-8842","invoice_date":"2026-10-28","currency":"USD","total_value":"48,600.00","line_items":[{"description":"Servo assemblies","quantity":"120","unit_price":"280.00","line_total":"33,600.00"},{"description":"Control modules","quantity":"60","unit_price":"250.00","line_total":"15,000.00"}],"packages":"120","gross_weight_kg":"3120","supplier":"Asterion Controls GmbH"}, .96),
        ("Packing list", "Packing list PL-8842 · 2026-10-29", {"invoice_number":"CI-8842","packages":"120","gross_weight_kg":"3165","net_weight_kg":"2980"}, .91),
        ("Bill of lading", "B/L OOLU-782640 · 2026-10-30", {"bill_number":"OOLU-782640","invoice_number":"CI-8842","packages":"120","gross_weight_kg":"3165","origin":"Hamburg"}, .94),
    ]),
    ("SHP-24806", "Meridian Medical Systems", "Haneul Precision Co.", "South Korea", [
        ("Commercial invoice", "Invoice INV-2026-771", {"invoice_number":"INV-2026-771","currency":"USD","total_value":"22,940.00","line_items":[{"description":"Precision pump bodies","quantity":"40","unit_price":"350.00","line_total":"14,000.00"},{"description":"Valve assemblies","quantity":"60","unit_price":"149.00","line_total":"8,940.00"}],"packages":"48","gross_weight_kg":"940","supplier":"Haneul Precision Co."}, .98),
        ("Packing list", "Packing list PL-771", {"invoice_number":"INV-2026-771","packages":"48","gross_weight_kg":"940","net_weight_kg":"810"}, .97),
        ("Bill of lading", "B/L EGLV-551029", {"bill_number":"EGLV-551029","invoice_number":"INV-2026-771","packages":"48","gross_weight_kg":"940","origin":"Busan"}, .95),
    ]),
    ("SHP-24798", "Bluepeak Outdoor Goods", "Vela Textiles S.A.", "Portugal", [
        ("Commercial invoice", "Invoice VT-1908", {"invoice_number":"VT-1908","currency":"EUR","total_value":"16,280.00","line_items":[{"description":"Merino crew sweaters","quantity":"40","unit_price":"220.00","line_total":"8,800.00"},{"description":"Cotton knit jackets","quantity":"20","unit_price":"374.00","line_total":"7,480.00"}],"packages":"86","gross_weight_kg":"1820","supplier":"Vela Textiles S.A."}, .82),
        ("Packing list", "Packing list PL-1908", {"invoice_number":"VT-1908","packages":"86","gross_weight_kg":"1818","net_weight_kg":"1650"}, .68),
    ]),
]

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(_=None):
    conn = g.pop("db", None)
    if conn: conn.close()

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")

def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH); conn.executescript(SCHEMA)
    if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        conn.executemany("INSERT INTO users(email,name,password_hash,role) VALUES(?,?,?,?)", [
            ("reviewer@cargolens.demo", "Maya Chen", generate_password_hash("Review2026!"), "executive"),
            ("manager@cargolens.demo", "Arjun Mehta", generate_password_hash("Manager2026!"), "manager")])
        for ref, importer, supplier, origin, docs in SAMPLE:
            sid = conn.execute("INSERT INTO shipments(ref,importer,supplier,origin,status,created_at) VALUES(?,?,?,?,?,?)", (ref,importer,supplier,origin,"Ready to verify" if ref=="SHP-24806" else "In review",now())).lastrowid
            for kind, filename, fields, confidence in docs:
                conn.execute("INSERT INTO documents(shipment_id,kind,filename,stored_name,extracted_json,confidence,state,created_at) VALUES(?,?,?,?,?,?,?,?)", (sid,kind,filename,"",__import__('json').dumps(fields),confidence,"Confirmed" if confidence>=.9 else "Needs review",now()))
    conn.commit(); conn.close()

def login_required(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        if not session.get("user_id"): return redirect(url_for("login", next=request.path))
        return fn(*a, **kw)
    return wrapped

def manager_required(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        if not session.get("user_id"): return redirect(url_for("login"))
        if session.get("role") != "manager": abort(403)
        return fn(*a, **kw)
    return wrapped

@app.before_request
def load_user():
    if request.method == "POST":
        token = session.get("csrf_token")
        if not token or not secrets.compare_digest(token, request.form.get("csrf_token", "")):
            abort(400, "Invalid CSRF token")
    g.user = db().execute("SELECT * FROM users WHERE id=?", (session.get("user_id"),)).fetchone() if session.get("user_id") else None

@app.context_processor
def inject_csrf():
    if "csrf_token" not in session: session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"]}

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        user = db().execute("SELECT * FROM users WHERE email=?", (request.form.get("email", "").strip().lower(),)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear(); session["user_id"]=user["id"]; session["role"]=user["role"]
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Email or password didn't match.", "error")
    return render_template("login.html")

@app.get("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.get("/")
@login_required
def dashboard():
    shipments = db().execute("SELECT s.*, COUNT(d.id) doc_count FROM shipments s LEFT JOIN documents d ON d.shipment_id=s.id GROUP BY s.id ORDER BY s.created_at DESC").fetchall()
    cards=[]
    for s in shipments:
        checks=checks_for(s["id"]); docs=db().execute("SELECT * FROM documents WHERE shipment_id=?",(s["id"],)).fetchall()
        cards.append({**dict(s),"checks":checks,"issue_count":sum(c["severity"]=="issue" for c in checks),"check_review_count":sum(c["severity"]=="review" for c in checks),"review_count":sum(d["state"]!="Confirmed" for d in docs)})
    doc_total=db().execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    confirmed=db().execute("SELECT COUNT(*) FROM documents WHERE state='Confirmed'").fetchone()[0]
    return render_template("dashboard.html", shipments=cards, total=len(cards), issue_total=sum(s["issue_count"] for s in cards), review_total=sum(bool(s["review_count"] or s["check_review_count"] or s["issue_count"]) for s in cards), doc_total=doc_total, confirmed_pct=round(confirmed*100/doc_total) if doc_total else 0, ready_total=sum(s["status"]=='Ready to verify' for s in cards))

REQUIRED_DOCUMENTS=("Commercial invoice","Packing list","Bill of lading")

def decimal_value(value):
    try:
        result=Decimal(str(value).replace(",","").replace("$","").replace("€","").strip())
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError): return None

def valid_line_items(items):
    if not isinstance(items,list) or not items or len(items)>200: return False
    return all(isinstance(item,dict) and item.get("description") and decimal_value(item.get("line_total")) is not None for item in items)

def checks_for(sid):
    import json
    docs=db().execute("SELECT * FROM documents WHERE shipment_id=? ORDER BY id",(sid,)).fetchall()
    parsed={d["kind"]:json.loads(d["extracted_json"]) for d in docs}
    checks=[]
    missing_docs=[kind for kind in REQUIRED_DOCUMENTS if kind not in parsed]
    checks.append({"label":"Required document set","severity":"review" if missing_docs else "clear","detail":("Missing: "+", ".join(missing_docs)) if missing_docs else "Invoice, packing list and bill of lading are present","delta":"Upload each required document" if missing_docs else "All three document types present"})
    def compare(label,key,kinds,units="",numeric=False):
        missing=[kind for kind in kinds if kind not in parsed or parsed[kind].get(key) in (None,"")]
        vals=[(kind,parsed[kind][key]) for kind in kinds if kind in parsed and parsed[kind].get(key) not in (None,"")]
        if missing:
            checks.append({"label":label,"severity":"review","detail":" · ".join(f"{k}: {v}{units}" for k,v in vals) or "No comparable values found","delta":"Add values for: "+", ".join(missing)})
            return
        normalized=[decimal_value(v) for _,v in vals] if numeric else [str(v).strip().casefold() for _,v in vals]
        if numeric and any(v is None for v in normalized):
            checks.append({"label":label,"severity":"review","detail":" · ".join(f"{k}: {v}{units}" for k,v in vals),"delta":"One or more values could not be parsed"}); return
        mismatch=len(set(normalized))>1
        difference=(max(normalized)-min(normalized)) if numeric and mismatch else None
        checks.append({"label":label,"severity":"issue" if mismatch else "clear","detail":" · ".join(f"{k}: {v}{units}" for k,v in vals),"delta":f"{difference:g} {units.strip()} difference" if difference is not None else "Values differ" if mismatch else "Values agree"})
    compare("Gross weight","gross_weight_kg",REQUIRED_DOCUMENTS," kg",True)
    compare("Package count","packages",REQUIRED_DOCUMENTS," packages",True)
    compare("Invoice reference","invoice_number",REQUIRED_DOCUMENTS)
    invoice=parsed.get("Commercial invoice",{})
    total=decimal_value(invoice.get("total_value"))
    items=invoice.get("line_items")
    if total is None or not valid_line_items(items):
        checks.append({"label":"Invoice total vs line items","severity":"review","detail":"Invoice total or valid line-item amounts are missing","delta":"Enter invoice total and each line total"})
    else:
        line_sum=sum((decimal_value(item["line_total"]) for item in items),Decimal("0"))
        difference=abs(total-line_sum)
        checks.append({"label":"Invoice total vs line items","severity":"clear" if difference<=Decimal("0.01") else "issue","detail":f"Invoice total: {total:.2f} · Line-item sum: {line_sum:.2f}","delta":"Values agree" if difference<=Decimal("0.01") else f"{difference:.2f} difference"})
    return checks

@app.get("/shipments/new")
@login_required
def new_shipment(): return render_template("new_shipment.html")

@app.post("/shipments")
@login_required
def create_shipment():
    ref=request.form.get("ref","").strip().upper(); importer=request.form.get("importer","").strip(); supplier=request.form.get("supplier","").strip(); origin=request.form.get("origin","").strip()
    if not re.fullmatch(r"SHP-[0-9]{5}",ref) or not importer or not supplier or not origin:
        flash("Enter a shipment ID in SHP-12345 format and complete all fields.","error"); return redirect(url_for("new_shipment"))
    try: sid=db().execute("INSERT INTO shipments(ref,importer,supplier,origin,created_at) VALUES(?,?,?,?,?)",(ref,importer,supplier,origin,now())).lastrowid; db().commit()
    except sqlite3.IntegrityError: flash("That shipment ID already exists.","error"); return redirect(url_for("new_shipment"))
    return redirect(url_for("shipment",sid=sid))

@app.get("/shipments/<int:sid>")
@login_required
def shipment(sid):
    s=db().execute("SELECT * FROM shipments WHERE id=?",(sid,)).fetchone()
    if not s: abort(404)
    docs=db().execute("SELECT * FROM documents WHERE shipment_id=? ORDER BY id",(sid,)).fetchall()
    import json
    document_views=[]
    for d in docs:
        fields=json.loads(d["extracted_json"])
        if isinstance(fields.get("line_items"),list): fields["line_items"]=json.dumps(fields["line_items"],ensure_ascii=False)
        document_views.append({**dict(d),"fields":fields})
    history=db().execute("SELECT e.*,u.name,d.kind FROM edits e JOIN users u ON u.id=e.user_id JOIN documents d ON d.id=e.document_id WHERE d.shipment_id=? ORDER BY e.id DESC LIMIT 8",(sid,)).fetchall()
    decisions=db().execute("SELECT d.*,u.name FROM decisions d JOIN users u ON u.id=d.user_id WHERE d.shipment_id=? ORDER BY d.id DESC",(sid,)).fetchall()
    return render_template("shipment.html", shipment=s, docs=document_views, checks=checks_for(sid), history=history, decisions=decisions)

def extract_fields(text, kind):
    """Ask an OpenAI-compatible provider for grounded JSON; never invent confidence."""
    api_key=os.environ.get("OPENAI_API_KEY")
    if not api_key or not text.strip(): return {}, 0.0
    fields="invoice_number, invoice_date, currency, total_value, line_items, packages, gross_weight_kg, net_weight_kg, supplier, bill_number, origin"
    prompt=(f"Extract fields from this {kind}. Return only JSON with keys fields and confidence. "
            f"fields must contain only values explicitly present, using empty string for absent values. "
            f"confidence is an object mapping each returned field to a number from 0 to 1. Do not infer missing facts.\n"
            f"Document text:\n{text[:18000]}")
    body=__import__('json').dumps({"model":os.environ.get("OPENAI_MODEL","gpt-4o-mini"),"temperature":0,"response_format":{"type":"json_object"},"messages":[{"role":"system","content":f"You extract customs document data. Allowed fields: {fields}. Be conservative and return valid JSON."},{"role":"user","content":prompt}]}).encode()
    req=urllib.request.Request(os.environ.get("OPENAI_BASE_URL","https://api.openai.com/v1")+"/chat/completions",data=body,headers={"Authorization":"Bearer "+api_key,"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=25) as resp: result=__import__('json').loads(resp.read())
        payload=__import__('json').loads(result["choices"][0]["message"]["content"])
        allowed=set(fields.split(", ")); values={k:(v if k=="line_items" else str(v)[:120]) for k,v in payload.get("fields",{}).items() if k in allowed and v not in (None,"")}
        if "line_items" in values and not valid_line_items(values["line_items"]): values.pop("line_items")
        scores=[float(payload.get("confidence",{}).get(k,0)) for k in values]
        return values, (sum(scores)/len(scores) if scores else 0.0)
    except (urllib.error.URLError, ValueError, KeyError, IndexError, TypeError, TimeoutError):
        return {}, 0.0

@app.post("/shipments/<int:sid>/upload")
@login_required
def upload(sid):
    if not db().execute("SELECT 1 FROM shipments WHERE id=?",(sid,)).fetchone(): abort(404)
    f=request.files.get("document"); kind=request.form.get("kind","")
    if kind not in {"Commercial invoice","Packing list","Bill of lading"} or not f or not f.filename:
        flash("Choose a document type and file.","error"); return redirect(url_for("shipment",sid=sid))
    name=secure_filename(f.filename); ext=name.rsplit(".",1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED: flash("Use a PDF, image, text or CSV file.","error"); return redirect(url_for("shipment",sid=sid))
    stored=secrets.token_hex(16)+"."+ext; UPLOAD_DIR.mkdir(parents=True,exist_ok=True); f.save(UPLOAD_DIR/stored)
    text=""
    try:
        if ext in {"txt","csv"}: text=(UPLOAD_DIR/stored).read_text(errors="ignore")[:50000]
        elif ext=="pdf":
            import fitz
            with fitz.open(UPLOAD_DIR/stored) as pdf: text="\n".join(p.get_text() for p in pdf)[:50000]
    except Exception: text=""
    fields,conf=extract_fields(text,kind)
    state="Needs review"
    import json
    db().execute("INSERT INTO documents(shipment_id,kind,filename,stored_name,extracted_json,confidence,state,created_at) VALUES(?,?,?,?,?,?,?,?)",(sid,kind,name,stored,json.dumps(fields),conf,state,now())); db().commit()
    flash("Document added. Extracted values are marked for human review.","success"); return redirect(url_for("shipment",sid=sid))

@app.post("/documents/<int:did>/field")
@login_required
def edit_field(did):
    import json
    d=db().execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
    if not d: abort(404)
    fields=json.loads(d["extracted_json"]); key=request.form.get("field",""); raw=request.form.get("value","").strip()
    allowed={"invoice_number","invoice_date","currency","total_value","line_items","packages","gross_weight_kg","net_weight_kg","supplier","bill_number","origin"}
    if key not in allowed or len(raw)>12000:
        abort(400)
    value=raw
    if key=="line_items":
        try: value=json.loads(raw)
        except ValueError: abort(400)
        if not valid_line_items(value): abort(400)
    elif len(raw)>120: abort(400)
    old=fields.get(key); fields[key]=value
    db().execute("UPDATE documents SET extracted_json=? WHERE id=?",(json.dumps(fields),did))
    db().execute("INSERT INTO edits(document_id,user_id,field,old_value,new_value,created_at) VALUES(?,?,?,?,?,?)",(did,session["user_id"],key,str(old or ""),value,now())); db().commit()
    return redirect(url_for("shipment",sid=d["shipment_id"]))

@app.post("/documents/<int:did>/confirm")
@login_required
def confirm_doc(did):
    import json
    d=db().execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
    if not d: abort(404)
    if not json.loads(d["extracted_json"]):
        flash("Add at least one document value before confirming.","error")
        return redirect(url_for("shipment",sid=d["shipment_id"]))
    db().execute("UPDATE documents SET state='Confirmed' WHERE id=?",(did,)); db().commit(); return redirect(url_for("shipment",sid=d["shipment_id"]))

@app.get("/documents/<int:did>/download")
@login_required
def download_document(did):
    d=db().execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
    if not d: abort(404)
    if not d["stored_name"]: abort(404)
    path=UPLOAD_DIR/d["stored_name"]
    if not path.is_file(): abort(404)
    return send_file(path, as_attachment=True, download_name=secure_filename(d["filename"]), conditional=True)

@app.post("/shipments/<int:sid>/approve")
@manager_required
def approve(sid):
    docs=db().execute("SELECT * FROM documents WHERE shipment_id=?",(sid,)).fetchall(); checks=checks_for(sid)
    if not docs or any(d["state"]!="Confirmed" for d in docs) or any(c["severity"]!="clear" for c in checks):
        flash("Approval is blocked. Confirm every document and resolve cross-document mismatches first.","error"); return redirect(url_for("shipment",sid=sid))
    db().execute("UPDATE shipments SET status='Approved' WHERE id=?",(sid,)); db().execute("INSERT INTO decisions(shipment_id,user_id,action,note,created_at) VALUES(?,?,?,?,?)",(sid,session["user_id"],"Approved","All documents confirmed; validation clear.",now())); db().commit()
    flash("Shipment approved for export.","success"); return redirect(url_for("shipment",sid=sid))

@app.get("/shipments/<int:sid>/export.csv")
@login_required
def export_csv(sid):
    s=db().execute("SELECT * FROM shipments WHERE id=?",(sid,)).fetchone()
    if not s: abort(404)
    docs=db().execute("SELECT * FROM documents WHERE shipment_id=?",(sid,)).fetchall()
    checks=checks_for(sid)
    if s["status"]!="Approved" or not docs or any(d["state"]!="Confirmed" for d in docs) or any(c["severity"]!="clear" for c in checks): abort(409)
    import json
    out=io.StringIO(); writer=csv.writer(out); writer.writerow(["shipment_ref","importer","supplier","origin","document_type","field","value"])
    for d in docs:
        for key,value in json.loads(d["extracted_json"]).items(): writer.writerow([s["ref"],s["importer"],s["supplier"],s["origin"],d["kind"],key,value])
    return Response(out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":f"attachment; filename={s['ref']}-verified.csv"})

@app.get("/health")
def health(): return jsonify(status="ok")

with app.app_context(): init_db()

if __name__ == "__main__": app.run(debug=os.environ.get("FLASK_DEBUG")=="1", port=int(os.environ.get("PORT",5000)))
