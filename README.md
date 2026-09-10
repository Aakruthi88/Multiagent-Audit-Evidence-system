# Multi-Agent Audit Evidence System

A multi-agent LLM system designed for automated audit evidence verification, cross-referencing purchase orders, invoices, goods received notes (GRNs), and bank statements.

## Project Structure

```
MultiAgentEvidenceSystem/
├── backend/
│   ├── alembic/              # Database migration scripts
│   ├── app/                  # FastAPI backend application & agent code
│   ├── storage/              # Document storage and ChromaDB vector store
│   ├── tests/                # Test suite
│   ├── audit_db.db           # SQLite database (pre-seeded with demo data)
│   ├── Dockerfile            # Container configuration
│   ├── requirements.txt      # Python dependencies
│   └── .env.example          # Environment configuration template
├── frontend/
│   ├── src/                  # React / TypeScript frontend application
│   ├── index.html            # Entry HTML page
│   ├── package.json          # Node.js dependencies & scripts
│   ├── tsconfig.json         # TypeScript configuration
│   └── vite.config.ts        # Vite configuration
├── docker-compose.yml        # Multi-container orchestrator configuration
├── Audit_Evidence_Assistant_Implementation_Guide.md
└── README.md
```

## Setup Instructions

### Prerequisites
- Python 3.10+
- Node.js 18+ and npm

### 1. Backend Setup

```bash
cd backend

# Create and activate virtual environment
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create environment configuration file
cp .env.example .env
# Edit .env to add your OPENROUTER_API_KEY if using LLM features

# Run FastAPI backend server
uvicorn app.main:app --reload --port 8000
```

The backend server will run at `http://localhost:8000`.

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

The frontend application will run at `http://localhost:5173`.

## Features
- **Multi-Agent Verification Pipeline**: Automated agent framework for document parsing, discrepancy detection, and audit trail logging.
- **Cross-Document Cross-Referencing**: Automatic reconciliation across POs, Invoices, GRNs, and Bank Statements.
- **Vector Search & RAG**: ChromaDB integration for audit evidence document similarity search.
