# Facility Safety Intelligence Portal — "Add Facility" Wizard

A Flask app implementing the full **Add Facility** onboarding wizard: download
a structured Word template, fill it out, upload it as a PDF, let Gemini
extract sensors/employees and flag gaps, answer follow-up questions in a
chat UI, configure sensor/attendance APIs with live connectivity testing,
and manage the employee directory.

Built for the ET AI Hackathon 2026 — Compound Risk Detection Engine.

---

## 1. The Wizard — 7 Steps

| Step | Route | What happens |
|---|---|---|
| 1. Upload | `/factory/new` | Download the `.docx` template, fill it in, upload as PDF |
| 2. Validate | `/factory/<id>/validate` | Chat UI: AI-generated follow-up questions for anything missing/thin |
| 3. Sensors | `/factory/<id>/sensors` | Review/edit/add sensors, configure live API per sensor, test connectivity |
| 4. Layout | `/factory/<id>/layout` | Placeholder — not built yet, Next button only |
| 5. History | `/factory/<id>/negligence` | Free-text incident/negligence history |
| 6. Employees | `/factory/<id>/employees` | Review/edit/add employee directory (AI-prepopulated) |
| 7. Attendance | `/factory/<id>/attendance` | Configure + test the attendance system API, finish setup |

The landing page (`/`) has three cards: **Add Facility** (fully built, above),
**View / Edit Facility** and **Monitor Facility** (both placeholders —
"Coming Soon").

**Naming note:** the product is now called "Add Facility" in the UI. The
code still uses `factory`/`Factory` throughout internally (routes, models,
variables) — renaming the entire codebase for a label-only change was
judged not worth the risk. Only user-facing text says "Facility".

---

## 2. Folder Structure

```
factory_ai_portal/
├── app.py                              # Flask app entry point (run this)
├── config.py                           # All settings, read from environment variables
├── requirements.txt                    # Python dependencies
├── .env.example                        # Copy to .env and fill in your own values
│
├── models/
│   ├── factory.py                      # Factory record: profile, AI results, wizard state
│   ├── sensor.py                       # Sensor + live API config fields
│   └── employee.py                     # Employee record (mirrors Sensor's pattern)
│
├── services/
│   ├── storage.py                      # JSON-file "database" (data/factories.json)
│   ├── ai_extraction.py                # ONE Gemini call -> sensors + employees + gaps + questions
│   └── api_tester.py                   # Server-side "Test Connection" for sensor/attendance APIs
│
├── routes/
│   ├── main_routes.py                  # Landing page ("/")
│   └── factory_routes.py               # All 7 wizard steps + JSON CRUD/test APIs
│
├── templates/
│   ├── base.html, landing.html
│   ├── add_facility_step1_upload.html
│   ├── add_facility_step2_validate.html
│   ├── add_facility_step3_sensors.html
│   ├── add_facility_step4_layout.html
│   ├── add_facility_step5_negligence.html
│   ├── add_facility_step6_employees.html
│   ├── add_facility_step7_attendance.html
│   └── partials/
│       ├── wizard_progress.html        # Shared 7-step progress bar
│       ├── sensor_card.html / sensor_form_modal.html
│       └── employee_card.html / employee_form_modal.html
│
├── static/
│   ├── css/style.css
│   ├── js/upload.js, sensors.js, employees.js, validation_chat.js, attendance.js
│   ├── templates_download/facility_onboarding_template.docx   # the downloadable template
│   └── uploads/                        # Uploaded completed PDFs are saved here
│
├── data/factories.json                 # Auto-created on first run — your "database"
└── tests/test_app.py                   # 20 automated end-to-end tests (pytest)
```

---

## 3. Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Optionally paste in a real GEMINI_API_KEY (free, no credit card --
# get one at https://aistudio.google.com/apikey). Leave blank for MOCK MODE.
```

## 4. Run

```bash
python app.py
```
Open **http://127.0.0.1:5000**.

- **Mock mode** (no `GEMINI_API_KEY`): every uploaded document returns the
  same fixed demo data (3 sensors, 3 employees, 2 missing sections, 5
  clarifying questions) — good enough to click through the entire wizard
  and test every screen with zero cost or API key.
- **Live mode** (real key set): Gemini actually reads your uploaded PDF and
  extracts real sensors/employees/gaps specific to that document.

## 5. Test

```bash
pytest
```
Runs all 20 tests in `tests/test_app.py`, covering every step of the wizard
end-to-end: template download, upload + mock extraction, validation Q&A
submission, sensor CRUD + API test (both the "Active" and "Inactive"
paths), the layout stub, negligence history persistence, employee CRUD,
and the attendance system test + finish. All run in mock mode, offline,
zero configuration needed.

*(Environment note: this suite was validated in a sandbox without pytest
installed, by running the exact same test bodies through a manual shim —
all 20 passed. A real `pytest` run on your machine exercises identical
test code.)*

### Manual click-through checklist

1. `/` → three cards, only "Add Facility" clickable.
2. Download the template, confirm it opens in Word (14 sections, ~18 pages).
3. Upload any PDF as the completed template → lands on Step 2 with 2 missing
   sections flagged and a 5-question chat.
4. Answer each question (typed answers appear as chat bubbles) → Continue.
5. Step 3: 3 sensors prepopulated. Edit one, delete one, add one with an API
   URL of `http://127.0.0.1:5000/` → Test Connection → should go green
   ("Active"). Change the URL to something unreachable → Test again → red
   ("Inactive").
6. Step 4: stub page, Next only.
7. Step 5: type negligence history → Next → confirm it's still there if you
   click Back.
8. Step 6: 3 employees prepopulated (with blood group, emergency contact,
   etc.) — same edit/delete/add pattern as sensors.
9. Step 7: configure an attendance API, Test Connection, Finish Setup →
   redirected to landing → facility now shows as fully onboarded.

---

## 6. Known Limitations / Assumptions Made

- **The validation "chat" is a single-batch Q&A, not a dynamic multi-turn
  conversation.** All questions are generated by ONE Gemini call at upload
  time; answering one question does not trigger a new AI call to decide the
  next one. This was a deliberate choice to keep AI usage to exactly one
  call per document, given Gemini free-tier rate limits (see below).
- **Sensor/Attendance API testing is connectivity-only.** "Active" means an
  HTTP response was received (even a 401/403 counts) — it does not validate
  the response body, authentication correctness, or data format.
- **No wizard-order enforcement.** Every step route is independently
  reachable given a valid facility ID; there's no state machine preventing
  you from jumping to Step 6 before finishing Step 3. This was a deliberate
  simplicity/robustness trade-off.
- **"No upload size limit"** is enforced at the Flask layer
  (`MAX_CONTENT_LENGTH = None`), but Gemini's Files API has its own limits.
- **Storage is a flat JSON file**, not a real database — fine for a
  hackathon demo; swap `services/storage.py` for a real DB before any
  production use.
- **LLM fallback-model chain deliberately NOT included** in this version,
  per an explicit decision to revisit that separately.
- **Free-tier Gemini rate limits and 503 "high demand" errors** are real
  and will interrupt rapid testing — see the project's prior discussion on
  this; `services/ai_extraction.py` falls back to mock data on any failure
  rather than crashing the wizard.
- **"View / Edit Facility" and "Monitor Facility"** are placeholder cards
  only — not built in this version.
- **"Factory Layout" (Step 4)** is a stub page — floor-plan/zone editing is
  future work.
