# Multi-Agent Audit Evidence Assistant — Implementation Guide
### Deloitte Capstone MVP (3-Day Build) — React + FastAPI + LangGraph + PostgreSQL

---

## 0. What I actually looked at before writing this

I opened your `synthetic_audit_bundles_v2.zip` (15 bundles, each `purchase_order.pdf` + `invoice.pdf` + `grn.pdf` + `bank_statement.pdf`, keyed by `TXN-2026-00X`). Real patterns in the data that your agents **must** handle, or the demo will look broken to a Deloitte auditor:

| Pattern found | Where | Implication |
|---|---|---|
| PO number is the only stable join key across all 4 docs | every bundle | Use `po_number` as the canonical match key, not invoice number |
| GRN "Total Amount" = **pre-tax subtotal**, PO/Invoice totals = **tax-inclusive** | all bundles with a GRN | Naive `GRN.total == PO.total` will fail on 100% of bundles. Must compare GRN vs `PO.subtotal` |
| `grn.pdf` **missing entirely** | bundle_03 | 3-way match must degrade gracefully, not crash |
| Invoice total (₹447,314.40) ≠ PO total (₹414,180.00), ≠ bank debit (₹414,180.00) | bundle_06 | This is your positive control for a **critical** discrepancy — build the demo around catching it |
| Bank NEFT narration embeds invoice number and a truncated vendor name, e.g. `NEFT-Ref9811335-Murthy, Oak and Palla Pvt Lt-INV200003` | all bundles | Vendor-name matching against bank text must tolerate truncation (prefix/fuzzy match, not exact) |
| Payment dated **before** invoice date and GRN date (03-05 payment vs 08-05 invoice, 09-05 GRN) | bundle_01 | Real auditors flag this as a control failure / possible backdating — build it as an explicit rule, not an afterthought |
| Normal chronology (PO → Invoice → GRN → Payment) | bundle_02, 04, 05 | Confirms the sequence check has both pass and fail cases in your own test data — good for a live demo |

I'll reference these bundle numbers throughout so you have ready-made demo cases without having to fabricate anomalies.

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         React 18 + Vite + TS                          │
│   Upload UI · Bundle Dashboard · Verification Report · Agent Trace    │
└───────────────────────────┬────────────────────────────────────────┘
                             │ REST (Axios) + SSE for streaming agent status
┌───────────────────────────▼────────────────────────────────────────┐
│                         FastAPI (async)                              │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │ /bundles   │ │ /documents │ │ /verification│ │ /reports /auth │  │
│  └────────────┘ └────────────┘ └──────────────┘ └────────────────┘  │
│         │ writes bundle+doc rows, enqueues orchestration job          │
└───────────────────────────┬────────────────────────────────────────┘
                             │
┌───────────────────────────▼────────────────────────────────────────┐
│                    LangGraph Orchestration Layer                     │
│   Router → Document Understanding (parallel) → Verification          │
│         → [conditional] → Search/Investigation → Report → END        │
│   Persisted checkpointer (Postgres) → resumable, replayable runs      │
└───────┬───────────────────────────┬───────────────────┬────────────┘
        │                           │                   │
┌───────▼───────┐         ┌─────────▼────────┐  ┌───────▼─────────┐
│ PDF/OCR layer  │         │ LLM layer         │  │ PostgreSQL 15   │
│ pdfplumber +   │         │ OpenRouter (cloud)│  │ structured data │
│ PyMuPDF +      │         │  ↓ fallback        │  │ + pgvector      │
│ pytesseract    │         │ Ollama (local)     │  │ (optional, for  │
│ (scanned PDFs) │         │ JSON-mode /        │  │ duplicate/     │
│                │         │ function-calling   │  │ semantic search)│
└────────────────┘         └───────────────────┘  └─────────────────┘
```

**Key production decisions, explained (this is what a Deloitte reviewer will probe):**

- **Verification is deterministic Python, not an LLM call.** An auditor cannot accept "the LLM said the amounts match." LLMs are used only for (a) structured extraction from documents, (b) fuzzy semantic reasoning where rules are ambiguous (e.g., "is this line-item description the same product?"), and (c) narrating findings in the final report. Every number in the report is computed once, in Python, and the LLM narrates it — never invents it. Say this explicitly in your capstone defense; it's the single biggest thing that separates a toy demo from something Deloitte would trust.
- **OpenRouter primary, Ollama fallback** — gives you a cost/latency story (cloud model for extraction accuracy) *and* a data-residency story (local model as fallback / for sensitive runs), which maps directly to "Security & Compliance" on the rubric.
- **LangGraph checkpointer backed by Postgres**, not in-memory — every agent run is resumable and inspectable. This alone gives you an "Agent Trace" page that's genuinely impressive in a 5-minute demo and speaks to "Scalability."
- **Async FastAPI + background task queue** (simplest viable: FastAPI `BackgroundTasks` for the 3-day MVP; note in your writeup that Celery/Redis is the obvious next step for horizontal scaling — mention it, don't build it, unless Day 3 goes very smoothly).

---

## 2. PostgreSQL Database Design

Design principle: **separate the immutable evidence layer (documents, extracted facts) from the derived judgment layer (checks, discrepancies, risk score)**. This is how real audit systems are built — you never overwrite extracted evidence; you append verification runs on top of it. It also means you can re-run verification logic (e.g., after fixing a tolerance rule) without re-extracting documents.

```sql
-- ============ EVIDENCE LAYER ============

CREATE TABLE vendors (
    vendor_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_raw        TEXT NOT NULL,
    name_normalized TEXT NOT NULL,          -- lowercased, punctuation-stripped, for fuzzy match
    address         TEXT,
    phone           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
-- Why: vendor names appear slightly differently on PO / Invoice / bank narration
-- (e.g. "Murthy, Oak and Palla Pvt Ltd" vs bank's truncated
-- "Murthy, Oak and Palla Pvt Lt"). A normalized name lets the verification
-- agent do fuzzy identity resolution once, not re-derive it per check.

CREATE TABLE audit_bundles (
    bundle_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    txn_reference TEXT UNIQUE NOT NULL,      -- e.g. 'TXN-2026-006'
    status        TEXT NOT NULL DEFAULT 'uploaded',  -- uploaded|extracting|verifying|investigating|reported|failed
    uploaded_by   UUID REFERENCES users(user_id),
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);
-- Why: the unit of work an auditor cares about is "this transaction's evidence
-- pack," not an individual PDF. Everything else hangs off bundle_id.

CREATE TABLE documents (
    document_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bundle_id      UUID NOT NULL REFERENCES audit_bundles(bundle_id) ON DELETE CASCADE,
    doc_type       TEXT NOT NULL CHECK (doc_type IN ('purchase_order','invoice','grn','bank_statement')),
    file_path      TEXT NOT NULL,            -- object storage / local path
    file_hash      TEXT NOT NULL,            -- SHA-256, for tamper/duplicate-upload detection
    raw_text       TEXT,                     -- pdfplumber/OCR output, kept for auditability
    extraction_status  TEXT DEFAULT 'pending', -- pending|success|low_confidence|failed
    extraction_confidence NUMERIC(4,3),
    extraction_model   TEXT,                 -- which LLM/model version did the extraction (for audit trail)
    uploaded_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (bundle_id, doc_type)              -- MVP: one of each type per bundle
);
-- Why: keeps the raw evidence immutable and traceable to a specific model
-- version — required for any "why did the AI say this" audit question.

CREATE TABLE purchase_orders (
    po_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  UUID UNIQUE NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    bundle_id    UUID NOT NULL REFERENCES audit_bundles(bundle_id),
    po_number    TEXT NOT NULL,
    po_date      DATE,
    vendor_id    UUID REFERENCES vendors(vendor_id),
    requisitioner TEXT,
    shipping_terms TEXT,
    subtotal     NUMERIC(14,2) NOT NULL,
    tax_rate     NUMERIC(5,2),
    tax_amount   NUMERIC(14,2),
    total_amount NUMERIC(14,2) NOT NULL
);

CREATE TABLE po_line_items (
    line_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    po_id        UUID NOT NULL REFERENCES purchase_orders(po_id) ON DELETE CASCADE,
    item_code    TEXT,
    description  TEXT NOT NULL,
    qty          NUMERIC(12,2) NOT NULL,
    unit_price   NUMERIC(14,2) NOT NULL,
    line_total   NUMERIC(14,2) NOT NULL
);

CREATE TABLE invoices (
    invoice_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id    UUID UNIQUE NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    bundle_id      UUID NOT NULL REFERENCES audit_bundles(bundle_id),
    invoice_number TEXT NOT NULL,
    invoice_date   DATE,
    due_date       DATE,
    po_ref_raw     TEXT,               -- as printed on the invoice, before matching
    po_id          UUID REFERENCES purchase_orders(po_id),  -- resolved match, nullable
    vendor_id      UUID REFERENCES vendors(vendor_id),
    subtotal       NUMERIC(14,2) NOT NULL,
    tax_rate       NUMERIC(5,2),
    tax_amount     NUMERIC(14,2),
    total_amount   NUMERIC(14,2) NOT NULL
);

CREATE TABLE invoice_line_items (
    line_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id   UUID NOT NULL REFERENCES invoices(invoice_id) ON DELETE CASCADE,
    description  TEXT NOT NULL,
    qty          NUMERIC(12,2),
    unit_price   NUMERIC(14,2),
    line_total   NUMERIC(14,2)
);

CREATE TABLE grns (
    grn_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID UNIQUE NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    bundle_id       UUID NOT NULL REFERENCES audit_bundles(bundle_id),
    grn_number      TEXT NOT NULL,
    grn_date        DATE,
    delivery_note_number TEXT,
    po_ref_raw      TEXT,
    po_id           UUID REFERENCES purchase_orders(po_id),
    vendor_id       UUID REFERENCES vendors(vendor_id),
    total_amount    NUMERIC(14,2) NOT NULL,   -- NOTE: pre-tax by design in source docs
    received_condition TEXT
);

CREATE TABLE grn_line_items (
    line_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    grn_id       UUID NOT NULL REFERENCES grns(grn_id) ON DELETE CASCADE,
    description  TEXT NOT NULL,
    qty_ordered  NUMERIC(12,2),
    qty_received NUMERIC(12,2),
    unit_price   NUMERIC(14,2),
    line_total   NUMERIC(14,2)
);

CREATE TABLE bank_statements (
    statement_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id    UUID UNIQUE NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    bundle_id      UUID NOT NULL REFERENCES audit_bundles(bundle_id),
    account_number TEXT,
    statement_date DATE,
    period_start   DATE,
    period_end     DATE,
    opening_balance NUMERIC(14,2),
    closing_balance NUMERIC(14,2)
);

CREATE TABLE bank_transactions (
    txn_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    statement_id       UUID NOT NULL REFERENCES bank_statements(statement_id) ON DELETE CASCADE,
    txn_date           DATE NOT NULL,
    description_raw    TEXT NOT NULL,
    credit_amount      NUMERIC(14,2),
    debit_amount       NUMERIC(14,2),
    running_balance    NUMERIC(14,2),
    extracted_ref      TEXT,     -- e.g. 'Ref9811335' parsed from narration
    extracted_invoice_number TEXT, -- e.g. 'INV200003' parsed from narration
    extracted_vendor_fragment TEXT, -- truncated vendor text as it appears in narration
    matched_invoice_id UUID REFERENCES invoices(invoice_id)  -- resolved by verification agent
);
-- Why split raw vs extracted fields: bank narrations are free text
-- ("NEFT-Ref9811335-Murthy, Oak and Palla Pvt Lt-INV200003"). We keep the raw
-- string for auditability and store what regex/LLM parsing derived from it
-- separately, so a bad parse never corrupts the source evidence.

-- ============ JUDGMENT LAYER ============

CREATE TABLE verification_runs (
    run_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bundle_id     UUID NOT NULL REFERENCES audit_bundles(bundle_id) ON DELETE CASCADE,
    started_at    TIMESTAMPTZ DEFAULT now(),
    completed_at  TIMESTAMPTZ,
    overall_status TEXT,          -- clean|flagged|critical|incomplete
    overall_risk_score NUMERIC(5,2),
    rules_version TEXT NOT NULL   -- pin which version of the rule engine ran, for reproducibility
);

CREATE TABLE verification_checks (
    check_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id       UUID NOT NULL REFERENCES verification_runs(run_id) ON DELETE CASCADE,
    check_type   TEXT NOT NULL,   -- see catalogue in Section 6
    status       TEXT NOT NULL CHECK (status IN ('pass','warning','fail','not_applicable')),
    expected_value TEXT,
    actual_value   TEXT,
    variance       NUMERIC(14,2),
    severity       TEXT CHECK (severity IN ('low','medium','high','critical')),
    explanation    TEXT NOT NULL  -- human-readable, generated deterministically (template, not LLM)
);

CREATE TABLE discrepancies (
    discrepancy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id         UUID NOT NULL REFERENCES verification_runs(run_id) ON DELETE CASCADE,
    check_id       UUID REFERENCES verification_checks(check_id),
    category       TEXT NOT NULL,  -- amount_mismatch|missing_document|date_sequence|duplicate_invoice|vendor_mismatch|qty_mismatch
    severity       TEXT NOT NULL,
    description    TEXT NOT NULL,
    recommended_action TEXT,
    resolved       BOOLEAN DEFAULT false,
    resolved_by    UUID REFERENCES users(user_id),
    resolved_at    TIMESTAMPTZ
);

CREATE TABLE agent_execution_log (
    log_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id       UUID REFERENCES verification_runs(run_id) ON DELETE CASCADE,
    bundle_id    UUID REFERENCES audit_bundles(bundle_id),
    agent_name   TEXT NOT NULL,   -- router|document_understanding|verification|search|report
    input_snapshot  JSONB,
    output_snapshot JSONB,
    model_used   TEXT,
    tokens_used  INTEGER,
    latency_ms   INTEGER,
    status       TEXT,            -- success|error|retried
    error_message TEXT,
    created_at   TIMESTAMPTZ DEFAULT now()
);
-- Why: this table IS your "Agent Trace" UI page and your Security & Compliance
-- story — full lineage of every LLM call, what it saw, what it returned, cost,
-- and latency. Deloitte auditors care enormously about explainability; this
-- table is the cheapest, highest-leverage thing you can build for that.

CREATE TABLE reports (
    report_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id       UUID NOT NULL REFERENCES verification_runs(run_id),
    format       TEXT DEFAULT 'pdf',
    file_path    TEXT,
    content_json JSONB NOT NULL,   -- structured report, source of truth; file is a rendering of it
    generated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE users (
    user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    role          TEXT DEFAULT 'auditor' CHECK (role IN ('auditor','reviewer','admin')),
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Indexes that matter for the demo and for the "scalability" story
CREATE INDEX idx_invoices_number ON invoices(invoice_number);      -- duplicate invoice detection
CREATE INDEX idx_po_number ON purchase_orders(po_number);
CREATE INDEX idx_bank_txn_invoice ON bank_transactions(extracted_invoice_number);
CREATE INDEX idx_vendor_normalized ON vendors(name_normalized);
CREATE INDEX idx_agent_log_run ON agent_execution_log(run_id);
```

**Entity relationships, one sentence each:**
- One `audit_bundle` → up to 4 `documents` (1:many, but capped by the `UNIQUE(bundle_id, doc_type)` constraint for MVP) → each document optionally resolves into exactly one typed row (`purchase_orders`/`invoices`/`grns`/`bank_statements`).
- One bundle → many `verification_runs` (you re-run verification after fixing a rule, without re-extracting) → each run → many `verification_checks` → some checks → `discrepancies`.
- `agent_execution_log` is a flat audit trail keyed to both `run_id` and `bundle_id` so you can show lineage even for runs that failed before a `verification_run` row was created.

---

## 3. Folder Structure

```
backend/
├── app/
│   ├── main.py                     # FastAPI app, CORS, startup events
│   ├── core/
│   │   ├── config.py                # pydantic-settings: DB URL, OPENROUTER_API_KEY, OLLAMA_HOST
│   │   ├── security.py              # JWT auth, password hashing
│   │   └── logging.py
│   ├── api/v1/
│   │   ├── bundles.py               # POST /bundles (upload 4 files), GET /bundles, GET /bundles/{id}
│   │   ├── documents.py             # GET /documents/{id} (raw extraction view)
│   │   ├── verification.py          # POST /bundles/{id}/verify, GET /runs/{id}
│   │   ├── reports.py               # GET /runs/{id}/report, GET /runs/{id}/report.pdf
│   │   ├── agents.py                # GET /runs/{id}/trace (agent_execution_log)
│   │   └── auth.py
│   ├── models/                      # SQLAlchemy ORM, 1:1 with schema above
│   ├── schemas/                     # Pydantic request/response + LLM structured-output schemas
│   │   ├── extraction_schemas.py    # POExtraction, InvoiceExtraction, GRNExtraction, BankExtraction
│   │   └── ...
│   ├── services/
│   │   ├── pdf_service.py           # pdfplumber + PyMuPDF + pytesseract fallback
│   │   ├── extraction_service.py    # calls LLM with JSON schema, validates, retries
│   │   ├── verification_service.py  # the deterministic rule engine (Section 6)
│   │   ├── matching_utils.py        # fuzzy vendor match, name normalization, regex parsers
│   │   └── storage_service.py       # local disk for MVP; interface ready for S3
│   ├── agents/
│   │   ├── state.py                 # BundleState TypedDict (LangGraph state)
│   │   ├── graph.py                 # StateGraph definition + conditional edges
│   │   ├── router_agent.py
│   │   ├── document_agent.py
│   │   ├── verification_agent.py    # thin wrapper calling verification_service
│   │   ├── search_agent.py
│   │   ├── report_agent.py
│   │   └── prompts/                 # .txt/.jinja prompt templates, versioned
│   ├── db/
│   │   ├── session.py
│   │   └── base.py
│   └── workers/
│       └── tasks.py                 # background task entrypoint (BackgroundTasks for MVP)
├── alembic/                         # migrations — use these, don't hand-edit schema
├── tests/
│   ├── test_verification_rules.py   # unit-test EVERY rule in Section 6 against your 15 bundles
│   └── fixtures/                    # copies of the synthetic bundles as golden test data
├── requirements.txt
├── Dockerfile
└── docker-compose.yml                # postgres + backend + (optional) ollama

frontend/
├── src/
│   ├── api/
│   │   ├── client.ts                 # axios instance, interceptors
│   │   └── endpoints.ts
│   ├── components/
│   │   ├── ui/                       # Button, Badge, Card, Table (shadcn-style primitives)
│   │   ├── UploadDropzone.tsx        # 4-slot upload: PO / Invoice / GRN / Bank Statement
│   │   ├── DocumentPreviewCard.tsx
│   │   ├── VerificationMatrix.tsx    # 4-way match table with pass/fail/warning cells
│   │   ├── DiscrepancyList.tsx
│   │   ├── RiskScoreGauge.tsx
│   │   └── AgentTraceTimeline.tsx    # visualizes agent_execution_log
│   ├── pages/
│   │   ├── Dashboard.tsx             # list of bundles + status
│   │   ├── BundleUpload.tsx
│   │   ├── BundleDetail.tsx          # extracted fields, side by side
│   │   ├── VerificationReport.tsx    # the money page for your demo
│   │   └── AgentTrace.tsx
│   ├── hooks/
│   │   └── useVerificationRun.ts     # polling / SSE for run status
│   ├── store/                        # zustand
│   ├── types/                        # mirror backend Pydantic schemas
│   └── App.tsx
├── package.json
└── vite.config.ts
```

---

## 4. LangGraph Workflow

```python
# app/agents/state.py
from typing import TypedDict, Optional, Literal
from typing_extensions import Annotated
import operator

class BundleState(TypedDict):
    bundle_id: str
    doc_paths: dict[str, str]                # {'purchase_order': path, 'invoice': path, ...}
    extracted: dict                          # populated per-doc after extraction
    missing_docs: list[str]
    verification_checks: Annotated[list, operator.add]
    discrepancies: Annotated[list, operator.add]
    risk_score: float
    needs_investigation: bool
    investigation_findings: Optional[dict]
    report: Optional[dict]
    errors: Annotated[list, operator.add]

# app/agents/graph.py
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver

graph = StateGraph(BundleState)

graph.add_node("router", router_node)
graph.add_node("extract_po", extract_po_node)
graph.add_node("extract_invoice", extract_invoice_node)
graph.add_node("extract_grn", extract_grn_node)
graph.add_node("extract_bank", extract_bank_node)
graph.add_node("merge_extractions", merge_extractions_node)
graph.add_node("verify", verification_node)
graph.add_node("investigate", search_agent_node)
graph.add_node("report", report_agent_node)

graph.set_entry_point("router")

# Fan-out: extraction is embarrassingly parallel across doc types
graph.add_conditional_edges(
    "router",
    lambda s: "no_docs" if not s["doc_paths"] else "extract",
    {"extract": ["extract_po", "extract_invoice", "extract_grn", "extract_bank"], "no_docs": END},
)
for node in ["extract_po", "extract_invoice", "extract_grn", "extract_bank"]:
    graph.add_edge(node, "merge_extractions")   # fan-in

graph.add_edge("merge_extractions", "verify")

def route_after_verification(state: BundleState) -> str:
    critical = [d for d in state["discrepancies"] if d["severity"] == "critical"]
    duplicate_or_vendor_flags = [
        d for d in state["discrepancies"]
        if d["category"] in ("duplicate_invoice", "vendor_mismatch")
    ]
    if critical or duplicate_or_vendor_flags or state["risk_score"] >= 60:
        return "investigate"
    return "report"

graph.add_conditional_edges("verify", route_after_verification,
                             {"investigate": "investigate", "report": "report"})
graph.add_edge("investigate", "report")
graph.add_edge("report", END)

checkpointer = PostgresSaver.from_conn_string(DATABASE_URL)
app_graph = graph.compile(checkpointer=checkpointer)
```

**Why fan-out/fan-in for extraction:** the 4 documents are independent — extracting the PO tells you nothing you need before extracting the invoice. Running them concurrently (via LangGraph's parallel branches, or `asyncio.gather` inside one node if you're short on time) cuts wall-clock latency roughly 4x, which matters live in a demo.

**Why route through `investigate` on duplicate/vendor flags specifically, not just risk score:** a duplicate-invoice check requires querying *across bundles* (SQL), which is naturally a tool-call, agentic step — different in kind from the in-memory numeric checks in `verify`. Keeping that distinction (deterministic single-bundle rules vs. cross-bundle/tool-using investigation) is a good talking point for "why LangGraph and not just a script."

---

## 5. Agent Responsibilities

**Router Agent** — cheap, fast (small local Ollama model or a rule-based classifier is fine — don't burn cloud tokens here). Validates the bundle has at least one document, sets `missing_docs`, decides whether this is a fresh run or a re-verification of an already-extracted bundle (skip straight to `verify` if `extracted` already populated — supports your "re-run after fixing a rule" story from Section 2).

**Document Understanding Agent** (x4, one per doc type, same pattern): `pdf_service` extracts text via `pdfplumber`; if text extraction yields <20 chars (scanned image), falls back to `pytesseract` OCR. The extracted text is passed to the LLM with a **strict JSON schema** (Pydantic model → JSON schema → OpenRouter JSON mode / function-calling) so output is directly `.model_validate()`-able — no regex-scraping of LLM prose. On schema validation failure, retry once with the error appended to the prompt, then mark `extraction_status='failed'` and surface it as a discrepancy rather than silently dropping the document (this is exactly the bundle_03-missing-GRN case, except here it'd be an *extraction* failure rather than a missing file — same downstream handling).

**Verification Agent** — thin orchestration wrapper around `verification_service.run_all_checks(state)`, which is **plain Python, not an LLM call**. See Section 6 for the full rule catalogue. This agent's only "intelligence" is invoking an LLM for the handful of *fuzzy* judgments regex can't make reliably (vendor name equivalence when similarity is borderline, e.g. 70-90%; line-item description equivalence like "Office Chairs - Ergonomic" vs a hypothetical "Ergonomic Office Chair (Black)"). Everything with a clean numeric or exact-string answer stays deterministic.

**Search/Investigation Agent** — a small ReAct-style LangGraph subgraph with tools:
- `check_duplicate_invoice(invoice_number, amount, vendor_id)` → SQL query across all bundles
- `get_vendor_history(vendor_id)` → past bundles for this vendor, prior discrepancy rate
- `check_amount_pattern(po_id)` → has this exact PO number been referenced by more than one invoice (classic double-billing pattern)
Only invoked when `route_after_verification` decides it's needed — keep it out of the happy path so most demo runs are fast.

**Report Agent** — receives the *structured* `verification_checks` + `discrepancies` + `investigation_findings` in the prompt context and is instructed to narrate, not compute. Output is itself a structured JSON (`ReportSchema`: executive_summary, match_table, discrepancy_narrative per item, overall_recommendation) which is then rendered to HTML/PDF. This guarantees every number in the final PDF traces back to a row in `verification_checks` — critical if anyone asks "how do I know the AI didn't hallucinate this."

---

## 6. Verification Agent — Business Rules (the auditor logic)

Canonical matching key: **`po_number`**, normalized (strip whitespace, uppercase, strip leading zeros). Every document type carries a reference back to it (`invoice.po_ref_raw`, `grn.po_ref_raw`).

### 6.1 Document completeness
```
For each expected doc_type in [purchase_order, invoice, grn, bank_statement]:
    if missing → discrepancy(category='missing_document', severity='high',
                             description=f'{doc_type} not provided — cannot complete 4-way match')
```
This alone correctly flags **bundle_03** (no GRN). Verification must still run all *other* applicable checks with the missing document's checks marked `not_applicable`, not abort — a partial audit trail is more useful than none.

### 6.2 PO ↔ Invoice
- `po_ref_raw` (invoice) == `po_number` (PO), normalized → **fail if mismatch, severity critical** (wrong transaction entirely)
- Vendor identity: fuzzy match (`rapidfuzz.token_sort_ratio`) between PO vendor name and invoice vendor name. Threshold ≥ 90 → pass; 70–89 → warning (LLM double-checks); < 70 → fail, severity high
- Recompute arithmetic independently: `subtotal_calc = Σ(qty × unit_price)`; `tax_calc = subtotal_calc × tax_rate`; `total_calc = subtotal_calc + tax_calc`. Compare `total_calc` to `invoice.total_amount` — catches internal arithmetic errors even if PO/invoice "agree" with each other
- **Total amount, PO vs Invoice**: tolerance = max(₹1, 0.1% of PO total) for rounding. Beyond tolerance → **critical**, with `variance_pct` computed and stated explicitly. *This is the exact rule that catches bundle_06 (invoice ₹447,314.40 vs PO ₹414,180.00, an 8% / ₹33,134.40 overbill with no corresponding PO amendment on file).*
- Line-item quantities: exact match required (no tolerance — audit convention: quantity discrepancies are never "rounding")

### 6.3 PO ↔ GRN (tax normalization is the critical trap)
- **`grn.total_amount` compares to `po.subtotal`, not `po.total_amount`.** State this rule explicitly in code with a comment — it's the single easiest mistake to make and it will fail every bundle if you get it wrong, because GRNs in this dataset never include tax.
  ```python
  tolerance = max(Decimal("1.00"), po.subtotal * Decimal("0.001"))
  if abs(grn.total_amount - po.subtotal) > tolerance:
      flag(...)
  ```
- Quantity ordered vs received, per line:
  - `qty_received < qty_ordered` → `category='short_shipment'`, severity medium, `variance = qty_ordered - qty_received`
  - `qty_received > qty_ordered` → `category='over_delivery'`, severity medium (possible unauthorized extra goods)
  - `qty_received == 0` → severity critical (goods not received, invoice should not be payable)
- Unit price on GRN vs PO: should be identical (GRN doesn't renegotiate price) — any mismatch is a data-entry flag, severity low/medium depending on magnitude

### 6.4 Invoice ↔ GRN (the real substance of a 3-way match)
- `invoice.subtotal` vs `grn.total_amount` — same tax-normalization rule as 6.3
- Quantity invoiced vs quantity received: **this is the check that actually protects against paying for goods never delivered.** If GRN is missing (bundle_03 case), mark `not_applicable` but escalate the missing-document discrepancy to critical instead of just high, since it means this protection cannot be exercised at all.

### 6.5 Invoice ↔ Bank Statement (payment verification)
- Parse `bank_transactions.description_raw` with regex: pattern observed in this dataset is
  `NEFT-Ref(?P<ref>\d+)-(?P<vendor_fragment>.+?)-(?P<invoice_ref>INV\d+)`. Store into `extracted_ref` / `extracted_vendor_fragment` / `extracted_invoice_number`.
- Match `extracted_invoice_number` to `invoice.invoice_number` (exact, after stripping the `INV` prefix)
- Vendor fragment match: since narrations **truncate** long vendor names, use prefix/fuzzy match — `bank_fragment` should be a fuzzy-prefix (`rapidfuzz.partial_ratio ≥ 90`) of `vendor.name_normalized`, not an exact match
- Amount: compare `debit_amount` (this is the buyer's own account, so vendor payment is a **debit**, not a credit — verify this against `bank_statements.opening/closing_balance` reconciliation, not just presence in a column) to `invoice.total_amount`, tolerance ₹1
- **Chronology check — payment must not precede invoice or GRN:**
  ```python
  if bank_txn.txn_date < invoice.invoice_date:
      flag(category='date_sequence', severity='high',
           description='Payment recorded before invoice date — verify for '
                        'backdated invoice, advance payment without proper '
                        'authorization, or extraction date error')
  if grn and bank_txn.txn_date < grn.grn_date:
      flag(category='date_sequence', severity='high',
           description='Payment recorded before goods receipt confirmed')
  ```
  *This exact rule fires on bundle_01 (payment 03-05, invoice 08-05, GRN 09-05) and passes cleanly on bundle_02/04/05 — use bundle_01 vs bundle_02 as your live "here's a pass, here's a fail" demo pair.*
- Unmatched bank transactions of significant amount with no corresponding invoice in the bundle set → flag for manual review (possible payment for an undocumented transaction)

### 6.6 Cross-cutting checks
- **Duplicate invoice detection** (needs Search Agent / cross-bundle SQL): same `invoice_number`, or same `(vendor_id, total_amount, invoice_date)` triple appearing in >1 bundle
- **Tax rate consistency**: PO tax_rate == Invoice tax_rate; flag any deviation from the organization's expected rate (18% in this dataset) even if internally consistent, since an incorrect-but-consistent rate is still a compliance issue
- **Materiality-based risk scoring**: `risk_score = min(100, Σ severity_weight)` where `critical=40, high=20, medium=10, low=5`, capped. `overall_status`: `risk_score == 0` → clean; `<20` → flagged; `≥20` → critical; any missing core document → incomplete regardless of score.

### 6.7 Test this against your own data before demo day
Write `tests/test_verification_rules.py` against the 15 real bundles as golden fixtures:
- bundle_03 → expect exactly one `missing_document` discrepancy, GRN-dependent checks `not_applicable`
- bundle_06 → expect one `critical` `amount_mismatch` on PO↔Invoice
- bundle_01 → expect `high` `date_sequence` discrepancy; bundle_02 → expect zero date-sequence discrepancies
- bundle_02/04/05/07-15 (no known injected anomaly) → expect `overall_status == 'clean'` after tax normalization is correctly applied
This gives you a regression suite you can literally screen-share during evaluation ("here are our unit tests passing against known-good and known-bad transactions") — very few capstones will have this, and it directly serves "Completeness" and "Requirement Specification" on the rubric.

---

## 7. API Design & Request Flow

```
POST   /api/v1/bundles
       multipart: txn_reference, purchase_order?, invoice?, grn?, bank_statement?
       → creates audit_bundle + documents rows, kicks off LangGraph run (background task)
       → 202 { bundle_id, status: 'extracting' }

GET    /api/v1/bundles                       list + status, paginated
GET    /api/v1/bundles/{bundle_id}            bundle detail + document list
GET    /api/v1/bundles/{bundle_id}/status     lightweight poll target (or use SSE below)
GET    /api/v1/bundles/{bundle_id}/stream     SSE: pushes state transitions as the graph runs
                                               (router → extracting → verifying → investigating → reported)

GET    /api/v1/documents/{document_id}        raw extraction result, confidence, raw_text

POST   /api/v1/bundles/{bundle_id}/verify     manually re-trigger verification (after a rule fix)
GET    /api/v1/runs/{run_id}                  verification_run + all checks + discrepancies
GET    /api/v1/runs/{run_id}/trace            agent_execution_log entries, ordered — the trace UI

GET    /api/v1/runs/{run_id}/report           structured JSON report
GET    /api/v1/runs/{run_id}/report.pdf       rendered PDF (weasyprint/reportlab)

POST   /api/v1/discrepancies/{id}/resolve     human-in-the-loop sign-off — auditor marks reviewed
POST   /api/v1/auth/login                     JWT
```

**Request flow for one bundle:** `POST /bundles` writes rows and returns immediately (202) → background task invokes `app_graph.ainvoke(initial_state, config={'thread_id': bundle_id})` → frontend either polls `/status` every 1.5s or subscribes to `/stream` (SSE) for live "Router → Extracting PO... → Verifying... → Investigating vendor history... → Report ready" UI feedback, which is a much stronger demo than a spinner. Every node write also appends to `agent_execution_log`, so `/runs/{id}/trace` doesn't need any extra plumbing — it's just a `SELECT ... WHERE run_id = ...`.

---

## 8. Frontend Page Structure

1. **Dashboard** — table of bundles: txn_reference, status badge, risk score, last updated. Click-through to detail. This is your "production feel" page — sortable, filterable by status.
2. **Bundle Upload** — 4-slot dropzone (PO / Invoice / GRN / Bank Statement), allows partial upload (demonstrates the missing-document path live using a bundle_03-style scenario), triggers run, redirects to detail page in "processing" state.
3. **Bundle Detail** — side-by-side extracted fields for each of the 4 documents (raw PDF thumbnail + structured JSON view), extraction confidence badges. Good place to show "here's what the LLM actually extracted, here's its confidence" — transparency sells well to auditors.
4. **Verification Report** (the page you demo the most) — 4-way match matrix (rows = fields like PO#, vendor, subtotal, tax, total, qty; columns = PO/Invoice/GRN/Bank; cells colored pass/warning/fail), discrepancy list sorted by severity with plain-English explanation and recommended action, overall risk gauge, "Generate/Download PDF Report" button, "Mark reviewed" for human sign-off.
5. **Agent Trace** — timeline of `agent_execution_log`: which agent ran, what model, tokens, latency, expandable input/output JSON. This page alone demonstrates you understand production LLM-ops, not just prompt engineering.
6. **(Stretch) Login / role gate** — auditor vs reviewer role, ties into Security & Compliance criterion.

---

## 9. 3-Day Development Plan

Mapped against the rubric you shared (Working Prototype 15, Completeness 15, Requirement Spec 5, Scalability 5, Security & Compliance 5, Potential Impact 5 = 50 total). **Working Prototype + Completeness is 30/50 points — an end-to-end working flow on real data beats a partially-built "more impressive" architecture. Prioritize accordingly.**

### Day 1 — Foundation + working single-bundle pipeline (targets: Working Prototype, Completeness)
- Postgres schema up via Alembic; Docker Compose (postgres + backend)
- `pdf_service`: pdfplumber extraction working on all 15 bundles (verify by hand against the text I extracted above — you already know what correct output looks like)
- Extraction schemas (Pydantic) for all 4 doc types + LLM extraction call (OpenRouter) with JSON-mode, validated end to end on at least bundle_01
- Minimal FastAPI: `POST /bundles`, background task runs extraction only (no LangGraph yet, just sequential calls) — get raw data into `purchase_orders`/`invoices`/`grns`/`bank_statements` tables for all 15 bundles
- **End of day 1 checkpoint: all 15 bundles extracted and sitting correctly in Postgres.** If extraction isn't reliably working for all 15 by end of Day 1, treat Day 2's LangGraph work as at risk and simplify (see Section 10).

### Day 2 — Verification engine + LangGraph orchestration (targets: Working Prototype, Completeness, Requirement Specification)
- `verification_service.py`: implement every rule in Section 6, in order 6.1 → 6.6
- Unit tests against the 15 bundles as golden fixtures (Section 6.7) — this is high leverage, do not skip it
- Wire up the LangGraph graph (Section 4): router → parallel extraction nodes (can reuse Day 1 extraction logic, just wrapped as nodes) → merge → verify → conditional → report
- `agent_execution_log` writes from every node
- Report Agent: structured JSON report + basic HTML→PDF rendering
- **End of day 2 checkpoint: `POST /bundles` → full graph run → PDF report, for at least bundle_01 (fail case), bundle_02 (clean case), bundle_03 (missing doc), bundle_06 (amount mismatch).**

### Day 3 — Frontend + Search Agent + polish (targets: Scalability, Security & Compliance, Potential Impact, presentation)
- Morning: React scaffold — Dashboard, Upload, Bundle Detail, Verification Report pages wired to the working API
- Midday: Search/Investigation Agent (duplicate invoice + vendor history tools) — this is the most cuttable item if time is short (see Section 10)
- Afternoon: Agent Trace page, JWT auth (even minimal), SSE status streaming for demo polish
- Evening: run all 15 bundles through the full pipeline once, screenshot/record the bundle_06 and bundle_01 "catch" cases specifically for your defense — these are your strongest, most concrete demo moments
- Write a one-page README covering architecture, the tax-normalization gotcha, and your test results — reviewers reward evidence of rigor, and you now have genuinely good evidence

---

## 10. Critique & How to Get Closer to "Enterprise Deloitte" in 3 Days

**What's already right:** separating evidence from judgment in the schema, keeping verification deterministic instead of LLM-hallucinated, and building an agent trace for explainability are all things that map directly onto how Deloitte's own risk-advisory tooling is actually built (auditability and explainability are non-negotiable in that world, more than raw AI cleverness). Lead with that framing in your defense — it signals you understand the *domain*, not just the tech stack.

**Where to be honest about scope, not defensive:**
- **Celery/Redis vs FastAPI BackgroundTasks**: don't build a task queue in 3 days. Do explicitly say in your README "BackgroundTasks is fine for MVP concurrency; production would move this to Celery + Redis for retry semantics and horizontal worker scaling" — naming the gap and the fix is worth more than pretending it doesn't exist.
- **OCR quality**: pytesseract on scanned docs is genuinely unreliable. If your synthetic PDFs are all text-based (they are, per my inspection — pdfplumber extracted them cleanly), you may never need the OCR fallback for the demo. Build it as a stub with a clear "would integrate Azure Document Intelligence / AWS Textract in production" note rather than fighting Tesseract accuracy under time pressure.
- **Search Agent is your first cut if Day 3 runs long.** A version of this capstone with 5 rock-solid deterministic checks and no investigation agent will score better than one with a flaky agentic search layer and buggy core verification. Cut here first, not from Section 6.
- **Multi-tenant / org isolation**: you don't need real RBAC in 3 days, but the `users.role` column and a note in your README about row-level security being the next step covers the "Security & Compliance" criterion credibly without building it.
- **"Potential Impact" (5 pts) is really an articulation exercise, not a build exercise.** Spend 20 minutes writing 3 concrete sentences: current manual 4-way match time per transaction at Deloitte's audit scale, time this reduces it to, and the specific risk category (revenue recognition / procurement fraud) this class of check protects against. That's worth more per minute spent than any additional code.
- **One thing to add if you have any slack at all**: a "confidence-weighted" extraction — surface `extraction_confidence` in the UI and let discrepancies inherit a caveat when the underlying extraction was low-confidence ("this invoice-vs-PO mismatch is based on a low-confidence OCR read — verify manually"). This is a small change that makes the whole system noticeably more trustworthy-looking and is a favorite thing real audit-tech reviewers probe for.

If you want, I can now write the actual `verification_service.py` rule engine and the Pydantic extraction schemas against your real bundle structure — that's the highest-risk piece to get subtly wrong (especially the tax-normalization rule), and I already have the field names your data actually uses.
