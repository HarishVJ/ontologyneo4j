# Neo4j Ontology-Powered NL2SQL POC

**Natural Language to SQL** chatbot powered by a Neo4j knowledge graph.
Demonstrates how structured ontology context enables accurate, auditable SQL generation for complex workforce KPIs.

## Quick Start

```bash
cd ontology_poc

# 1. Install dependencies
pip install -r requirements.txt

# 2. Seed Neo4j with KPI recipes, views, terms, and rules
python seed_neo4j.py

# 3. Start the web app
python -m uvicorn app:app --reload --port 8000
```

Open http://localhost:8000 in your browser.

## Demo Examples

| Question | Type | Expected Answer |
|----------|------|-----------------|
| "Show me headcount at ATL" | Simple KPI | ATL headcount is 489 |
| "What is the attrition rate at ATL last month?" | Complex KPI | 47.2% (23 terminations / 489 headcount) |

## Architecture

```
User Question
    ↓
┌─────────────────────────────────────┐
│ 1. Intent + Term Extraction         │  FastAPI Backend
│    (KPI detection, station, period) │
└───────────────┬─────────────────────┘
                ↓
┌─────────────────────────────────────┐
│ 2. Neo4j Ontology Lookup            │  Neo4j
│    (KPI recipe, views, joins, rules)│
└───────────────┬─────────────────────┘
                ↓
┌─────────────────────────────────────┐
│ 3. Structured Context Builder       │  Python Backend
│    (Compact context for LLM)        │
└───────────────┬─────────────────────┘
                ↓
┌─────────────────────────────────────┐
│ 4. LLM SQL Generator                │  Azure OpenAI (gpt-5.4)
│    (Generates Snowflake SQL)        │
└───────────────┬─────────────────────┘
                ↓
┌─────────────────────────────────────┐
│ 5. SQL Validator                    │  Python Validation Layer
│    (Safety, schema, security scope) │
└───────────────┬─────────────────────┘
                ↓
┌─────────────────────────────────────┐
│ 6. Snowflake / Mock Executor        │  Snowflake (simulated)
└───────────────┬─────────────────────┘
                ↓
            Final Answer
```

## Files

| File | Component | Responsibility |
|------|-----------|----------------|
| `intent_extractor.py` | Intent + Term Extraction | Rule-based KPI, station, period detection |
| `neo4j_ontology.py` | Ontology Lookup | Query Neo4j for KPI recipes and schema |
| `context_builder.py` | Context Builder | Transform Neo4j output → structured LLM input |
| `sql_generator.py` | SQL Generator | Azure OpenAI prompt + SQL extraction |
| `sql_validator.py` | SQL Validator | Safety checks, schema compliance, RLS |
| `mock_executor.py` | Mock Executor | Simulated Snowflake results |
| `pipeline.py` | Orchestrator | End-to-end pipeline coordination |
| `app.py` | API | FastAPI with `/ask` endpoint |
| `seed_neo4j.py` | Data Seeder | Loads KPI recipes, views, terms into Neo4j |
| `static/index.html` | UI | Executive-ready demo interface |
| `.env` | Config | Neo4j + Azure OpenAI credentials |

## What Neo4j Stores

- **2 KPI Recipes** (Headcount, Attrition Rate) with computation steps
- **3 Snowflake Views** with column metadata
- **2 JOIN paths** between views
- **39 Terms** (stations, status codes, pay classes, customers)
- **5 Business Rules** (hourly term logic, 28-day window, annualization)
