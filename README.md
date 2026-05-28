# Unifi KPI Ontology-Enabled Chatbot

Neo4j ontology-powered NL2SQL engine for Unifi workforce analytics. Converts natural language questions into validated Snowflake SQL using a graph-driven KPI recipe system.

## Architecture

```
User Question → Intent Extractor → Neo4j Ontology Lookup → Context Builder → LLM SQL Generator → SQL Validator → Snowflake Executor → Result
```

All KPI knowledge lives in **YAML files** loaded into **Neo4j** — no business logic hardcoded in Python. Adding a new KPI = edit YAML + re-seed.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create .env from template and fill in secrets
cp .env.example .env

# 3. Seed Neo4j ontology from YAML
python -m scripts.seed_ontology

# 4. Run the app
uvicorn api.app:app --reload --port 8000

# 5. Open browser
# http://localhost:8000
```

## Project Structure

```
config/              Pydantic settings, structured logging
ontology/
  schema/            views.yaml, joins.yaml, terms.yaml
  kpis/              KPI recipe YAML files (one per domain)
  security/          roles.yaml (user authorization)
  governance/        metadata.yaml (versioning, ownership)
  loader.py          YAML → Neo4j (idempotent MERGE)
  validator.py       Structural completeness checks
core/
  models.py          Domain dataclasses
  neo4j_client.py    Connection pool + health check
  intent_extractor.py  Term/KPI/period detection (Neo4j-loaded)
  ontology_lookup.py   Cypher queries for KPI recipes
  context_builder.py   Graph output → structured LLM context
  sql_generator.py     Azure OpenAI SQL generation
  sql_validator.py     Safety/schema/RLS validation
  snowflake_executor.py  Real Snowflake key-pair execution
  pipeline.py          Full orchestration
api/
  app.py             FastAPI application
  routes/            /api/v1/ask, /health, /api/v1/examples
  schemas/           Pydantic request/response models
  middleware/         Request logging
static/              UI
tests/
  golden/            YAML-based regression test cases
scripts/
  seed_ontology.py   Load YAML → Neo4j
  validate_ontology.py  Structural checks
  extract_snowflake_meta.py  Pull INFORMATION_SCHEMA
```

## Adding a New View or KPI

1. Add/edit YAML in `ontology/schema/views.yaml` or `ontology/kpis/`
2. Run `python -m scripts.seed_ontology`
3. Run `python -m scripts.validate_ontology`
4. Add golden tests in `tests/golden/`
5. Run `pytest tests/ -v`

**No Python code changes needed.**

## Current Scope

| Domain | View | KPIs |
|--------|------|------|
| Contract Hierarchy | `DIMFINANCEBUSINESSSTRUCTURE_V` | List Contracts, Count Contracts, List Stations, List Customers, Hierarchy Lookup |

## Tech Stack

- **FastAPI** + Uvicorn
- **Neo4j** (AuraDB) — ontology graph
- **Azure OpenAI** (gpt-5.4) — SQL generation
- **Snowflake** — data warehouse (RSA key-pair auth)
- **Pydantic** v2 — type-safe models
- **structlog** — JSON structured logging
