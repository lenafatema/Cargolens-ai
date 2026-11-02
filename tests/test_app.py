import importlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path

import app as cargo

class CargoLensTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        cargo.DB_PATH=str(Path(self.tmp.name)/"test.db")
        cargo.UPLOAD_DIR=Path(self.tmp.name)/"uploads"
        cargo.init_db()
        cargo.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client=cargo.app.test_client()

    def tearDown(self): self.tmp.cleanup()

    def token(self):
        with self.client.session_transaction() as sess: return sess["csrf_token"]

    def login(self,email,password):
        self.client.get("/login")
        return self.client.post("/login",data={"csrf_token":self.token(),"email":email,"password":password},follow_redirects=True)

    def test_seeded_weight_mismatch_detected(self):
        with cargo.app.app_context():
            sid=cargo.db().execute("SELECT id FROM shipments WHERE ref='SHP-24811'").fetchone()[0]
            checks=cargo.checks_for(sid)
        weight=next(c for c in checks if c["label"]=="Gross weight")
        self.assertEqual(weight["severity"],"issue")
        self.assertEqual(weight["delta"],"45 kg difference")

    def test_extraction_without_provider_requires_manual_review(self):
        os.environ.pop("OPENAI_API_KEY",None)
        self.assertEqual(cargo.extract_fields("Invoice number: INV-1", "Commercial invoice"),({},0.0))

    def test_manager_can_approve_clear_shipment_and_export(self):
        self.login("manager@cargolens.demo","Manager2026!")
        with cargo.app.app_context(): sid=cargo.db().execute("SELECT id FROM shipments WHERE ref='SHP-24806'").fetchone()[0]
        response=self.client.post(f"/shipments/{sid}/approve",data={"csrf_token":self.token()},follow_redirects=True)
        self.assertIn(b"approved for export",response.data)
        exported=self.client.get(f"/shipments/{sid}/export.csv")
        self.assertEqual(exported.status_code,200)
        self.assertIn(b"shipment_ref",exported.data)

    def test_executive_cannot_approve_and_unresolved_export_is_blocked(self):
        self.login("reviewer@cargolens.demo","Review2026!")
        with cargo.app.app_context(): sid=cargo.db().execute("SELECT id FROM shipments WHERE ref='SHP-24806'").fetchone()[0]
        self.assertEqual(self.client.post(f"/shipments/{sid}/approve",data={"csrf_token":self.token()}).status_code,403)
        with cargo.app.app_context(): issue=cargo.db().execute("SELECT id FROM shipments WHERE ref='SHP-24811'").fetchone()[0]
        self.assertEqual(self.client.get(f"/shipments/{issue}/export.csv").status_code,409)

    def test_csrf_required_for_mutations(self):
        self.login("reviewer@cargolens.demo","Review2026!")
        self.assertEqual(self.client.post("/shipments",data={"ref":"SHP-99123"}).status_code,400)

    def test_unreadable_upload_can_be_filled_manually_and_audited(self):
        self.login("reviewer@cargolens.demo","Review2026!")
        with cargo.app.app_context(): sid=cargo.db().execute("SELECT id FROM shipments WHERE ref='SHP-24806'").fetchone()[0]
        response=self.client.post(f"/shipments/{sid}/upload",data={"csrf_token":self.token(),"kind":"Commercial invoice","document":(io.BytesIO(b"scan content"),"scan.txt")},content_type="multipart/form-data",follow_redirects=True)
        self.assertEqual(response.status_code,200)
        self.assertIn(b"No text was extracted",response.data)
        with cargo.app.app_context(): did=cargo.db().execute("SELECT id FROM documents WHERE filename='scan.txt'").fetchone()[0]
        response=self.client.post(f"/documents/{did}/confirm",data={"csrf_token":self.token()},follow_redirects=True)
        self.assertIn(b"Add at least one document value before confirming",response.data)
        response=self.client.post(f"/documents/{did}/field",data={"csrf_token":self.token(),"field":"invoice_number","value":"MANUAL-77"},follow_redirects=True)
        self.assertEqual(response.status_code,200)
        self.assertIn(b"MANUAL-77",response.data)
        self.assertIn(b"Updated invoice number",response.data)
        with cargo.app.app_context(): self.assertEqual(cargo.db().execute("SELECT state FROM documents WHERE id=?",(did,)).fetchone()[0],"Needs review")
        self.client.post(f"/documents/{did}/confirm",data={"csrf_token":self.token()})
        with cargo.app.app_context(): self.assertEqual(cargo.db().execute("SELECT state FROM documents WHERE id=?",(did,)).fetchone()[0],"Confirmed")

if __name__=="__main__": unittest.main()
