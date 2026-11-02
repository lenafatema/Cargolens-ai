from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

OUT="Technical_Design_Document.docx"
doc=Document(); sec=doc.sections[0]
sec.top_margin=Inches(.68); sec.bottom_margin=Inches(.66); sec.left_margin=Inches(.78); sec.right_margin=Inches(.78)
styles=doc.styles
styles['Normal'].font.name='Aptos'; styles['Normal'].font.size=Pt(9); styles['Normal'].font.color.rgb=RGBColor(49,65,77)
styles['Normal'].paragraph_format.space_after=Pt(5)
for style_name in ['Normal','Title','Heading 1','Heading 2']:
    el=styles[style_name]._element
    rpr=el.get_or_add_rPr()
    fonts=rpr.rFonts
    if fonts is None:
        fonts=OxmlElement('w:rFonts'); rpr.insert(0,fonts)
    fonts.set(qn('w:ascii'),'Aptos'); fonts.set(qn('w:hAnsi'),'Aptos'); fonts.set(qn('w:eastAsia'),'Aptos')
title_ppr=styles['Title']._element.get_or_add_pPr()
for border in list(title_ppr.findall(qn('w:pBdr'))): title_ppr.remove(border)
for st,size,color in [('Title',25,'17394B'),('Heading 1',16,'157873'),('Heading 2',11,'23495B')]:
    styles[st].font.name='Aptos Display'; styles[st].font.size=Pt(size); styles[st].font.bold=True; styles[st].font.color.rgb=RGBColor.from_string(color)
    styles[st].paragraph_format.space_before=Pt(12); styles[st].paragraph_format.space_after=Pt(5)

def shade(cell, fill):
    tcPr=cell._tc.get_or_add_tcPr(); shd=OxmlElement('w:shd'); shd.set(qn('w:fill'),fill); tcPr.append(shd)
def table(headers, rows, widths=None):
    t=doc.add_table(rows=1,cols=len(headers)); t.alignment=WD_TABLE_ALIGNMENT.CENTER; t.style='Light Shading Accent 1'
    for i,h in enumerate(headers):
        c=t.rows[0].cells[i]; c.text=h; shade(c,'17394B')
        for r in c.paragraphs[0].runs: r.font.bold=True; r.font.color.rgb=RGBColor(255,255,255); r.font.size=Pt(8)
    for row in rows:
        cells=t.add_row().cells
        for i,val in enumerate(row):
            cells[i].text=str(val); cells[i].vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for p in cells[i].paragraphs:
                p.paragraph_format.space_after=Pt(2)
                for r in p.runs: r.font.size=Pt(8)
    doc.add_paragraph().paragraph_format.space_after=Pt(0)
    return t
def para(text, boldlead=None):
    p=doc.add_paragraph()
    if boldlead and text.startswith(boldlead): p.add_run(boldlead).bold=True; p.add_run(text[len(boldlead):])
    else: p.add_run(text)
    return p
def bullet(text): doc.add_paragraph(text,style='List Bullet')

p=doc.add_paragraph(); p.paragraph_format.space_after=Pt(2); r=p.add_run('GitHub: https://github.com/lenafatema/Cargolens-ai'); r.bold=True; r.font.color.rgb=RGBColor.from_string('157873'); r.font.size=Pt(9)
p=doc.add_paragraph(); p.paragraph_format.space_after=Pt(12); r=p.add_run('Live app: Not deployed'); r.font.size=Pt(9); r.font.color.rgb=RGBColor.from_string('788893')
doc.add_paragraph('CargoLens AI Technical Design',style='Title')
para('CargoLens AI is a shipment-document review workspace for customs operations. It collects invoice, packing-list and bill-of-lading data, flags cross-document differences, and gates approval and CSV export on human review. The delivered core is intentionally narrow: a reviewer can work a shipment from intake through validated export, while an operations manager has a separate approval role.')

doc.add_heading('Problem and product boundary',level=1)
para('Shipment information is repeated across documents. A mismatch can travel downstream if staff compare records by eye or export before review. CargoLens keeps extracted values beside their document type, compares shared fields, and prevents approval while documents remain unconfirmed or values disagree.')
para('The end-to-end path is: sign in → create or open shipment → upload trade documents → inspect and correct extracted fields → confirm documents → resolve differences → manager approval → CSV export.')

doc.add_heading('Architecture',level=1)
table(['Layer','Choice','Reason'],[
('Web UI','Flask-rendered HTML, responsive CSS and small inline interactions','One deployable service keeps the review flow fast to build and easy to run; server rendering provides real forms and clear error paths.'),
('Application','Python 3 / Flask','Validates form values, manages sessions and roles, calls extraction provider, evaluates cross-checks, and gates approval/export.'),
('Data','SQLite','A compact local demo store with relational constraints and zero external database setup. A managed PostgreSQL database is the next production step.'),
('Documents','Private local upload directory; PyMuPDF for text PDFs','Files stay outside static paths. Searchable PDFs and text/CSV are extractable; image-only scans remain a manual-review case.'),
('AI','OpenAI-compatible chat completions JSON mode, configured by environment','Structured extraction is real when configured. Missing credentials, unreadable text, provider errors or malformed output yield an empty extraction for manual review.'),
])
para('The Flask app initializes schema and synthetic demo data at startup. Production uses a WSGI server. The current file-backed database and upload directory require persistent storage and a single application instance.')

doc.add_heading('Data model',level=1)
table(['Entity','Important fields','Purpose'],[
('users','id, email, password_hash, role','Hashed credentials and executive/manager authorization.'),
('shipments','id, ref, importer, supplier, origin, status','Shipment workspace and lifecycle state.'),
('documents','shipment_id, kind, filename, stored_name, extracted_json, confidence, state','Uploaded artifact and structured extraction awaiting confirmation.'),
('edits','document_id, user_id, field, old_value, new_value, created_at','Append-only record of reviewer corrections.'),
('decisions','shipment_id, user_id, action, note, created_at','Manager approval audit entry.'),
])
para('Foreign keys are enabled. Shipment reference and user email are unique. Documents and audit rows belong to their parent records. Extracted fields are JSON in SQLite for this bounded demo; query-critical and shared fields should become typed columns as the product expands.')

doc.add_heading('AI extraction and uncertainty',level=1)
para('On upload, the server validates extension and size, writes the file under a random server-generated name, and extracts text from TXT, CSV and searchable PDF. It submits document type plus bounded text to a configured OpenAI-compatible endpoint and requests JSON-only fields explicitly present in the source. The response is parsed, keys are allow-listed, values are length-limited, and per-field confidence is averaged for display.')
para('The model’s confidence is a self-reported signal, not a calibrated probability. Values below 0.80 are marked for review. Every value still requires a human confirmation action before manager approval. If a provider key is absent, the file contains no extractable text, or the request/response fails, the application returns no extracted values with zero confidence and asks the reviewer to enter values manually. It does not manufacture a successful extraction. Scanned image OCR is outside this build.')

doc.add_heading('Cross-document rules and release gates',level=1)
para('For each comparable field, the validation engine collects non-empty values from documents and compares them. Gross weight, package count and invoice reference are shown as matched or mismatched. A mismatch blocks manager approval and export. Correction forms update the stored value and append the old/new value, user and timestamp to the edit history.')
para('A manager can approve only when at least one document exists, every document is confirmed, and no cross-check is mismatched. Export repeats those server-side checks and returns HTTP 409 when the shipment is not approved or no longer valid. The UI also reflects the gate, but the backend is authoritative.')

doc.add_heading('Screens and design decisions',level=1)
table(['Screen','Design choice'],[
('Sign in','A focused two-column welcome screen establishes the workspace identity; compact form, visible demo roles and secure-session cue reduce first-run friction.'),
('Shipment dashboard','A restrained queue with four operational metrics, search, status tabs, discrepancy badges and row-level navigation helps reviewers prioritize exceptions.'),
('Shipment review','Document field cards and cross-check results sit side by side on desktop and stack on mobile. Low confidence, unresolved mismatches and release state are visible at the point of action.'),
('Shipment intake','A short validated form creates the shipment shell before any file upload, avoiding an overlong all-in-one wizard.'),
])
para('The visual system uses deep marine blue, teal for progress, amber for review, and red for discrepancies. Typography, spacing and status chips repeat across screens. The layout adapts to narrow screens, and empty states explain the next action.')

doc.add_heading('Authentication, access and security',level=1)
bullet('Passwords use Werkzeug password hashing. Flask sessions use a secret key; cookies are HttpOnly and SameSite=Lax, and become Secure in production.')
bullet('CSRF tokens are checked on every POST. Managers alone can approve; the server denies executive approval requests.')
bullet('Inputs are validated, database access uses parameterized SQL, upload types and maximum size are constrained, and uploaded files are not served from a public static directory.')
bullet('No API key is committed. Configure secrets in the host environment. Use HTTPS and persistent private storage for a deployed instance.')
para('Synthetic demo accounts and sample shipment data are seeded for reviewer access. Demo passwords are for local evaluation and must be changed before public hosting.')

doc.add_heading('Verification',level=1)
para('Six automated tests cover seeded weight mismatch detection, no-key manual fallback, manager approval and verified CSV export, executive role denial and unresolved export blocking, and CSRF enforcement. Run with `python -m unittest discover -s tests -v`. The checks exercise the Flask app against temporary SQLite databases.')

doc.add_heading('Assumptions and limits',level=1)
for x in [
'Assumption: the selected problem is Brief 2, the customs broker document extraction and cross-check tool; the detailed source brief was not present in the workspace, so scope follows the supplied CargoLens recommendation.',
'Assumption: invoice, packing list and bill of lading are the initial supported document types; the MVP compares gross weight, package count and invoice reference when present.',
'Assumption: a manager role represents the approval authority and an executive role performs documentation work.',
'Assumption: synthetic shipment and company records are sufficient for reviewer demonstration; no real personal or customer data is used.',
'Limit: scanned image OCR is not implemented. Text extraction from searchable PDFs, TXT and CSV works; other uploads fall into manual review.',
'Limit: the provider response confidence is model-reported and is not calibrated or audited. Extraction is advisory and human confirmation is mandatory.',
'Limit: SQLite and local file storage support a single-instance demo only. Production needs managed relational storage, private object storage, retention controls, monitoring and backups.',
'Limit: the application is not deployed yet; add a live URL here if a host is configured.',
]: bullet(x)

doc.add_heading('Cut scope and next work',level=1)
para('Cut from this build: scanned-image OCR, multi-page visual document annotation, container-level matching, customs tariff classification, external customs integrations, multi-tenant organization management and production cloud deployment. These depend on requirements not included in the supplied brief or exceed the selected review slice.')
para('Next: add a real OCR pipeline with page-level evidence citations; calibrate extraction confidence against a labeled document set; normalize line items and container records; move to PostgreSQL and private object storage; add retention and deletion workflows; expand audit history; deploy to a persistent HTTPS host and publish the repository.')

doc.save(OUT)
print(OUT)
