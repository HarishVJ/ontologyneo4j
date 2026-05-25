# Neo4j Ontology-Powered AI Chatbot — Proposal for Unifi Aviation

**Prepared by:** iLink Systems Inc.
**Date:** May 2026
**Use Case:** UC3 — Natural Language to SQL (NL2SQL) AI Chatbot

---

---

## SLIDE 1 — Title

### Neo4j Ontology-Powered AI Chatbot
**Intelligent Workforce Analytics for Unifi Aviation**

- **From:** iLink Systems Inc.
- **For:** Unifi Aviation — UC3 NL2SQL Initiative
- **Date:** May 2026

*Enabling the AI chatbot to answer complex workforce questions — attrition rates, headcount trends, overtime analysis, and more — accurately, securely, and at scale.*

---

---

## SLIDE 2 — The Challenge

### Workforce Analytics Requires Deep Business Logic — Not Just SQL

Unifi's workforce questions are deceptively complex. Consider one real question:

> *"What's the attrition rate at ATL last month?"*

**What the AI must actually compute:**

| Step | Logic Required | Views Involved |
|------|---------------|----------------|
| 1. Hard Terminations (Salaried) | Employees with TERMINATIONDATE in period AND PAYCLASSCODE = 'P' | DIMHISTORYEMPLOYEE_V |
| 2. Hard Terminations (Hourly) | Last punch date falls in period (not TERMINATIONDATE) | FACTDAILYWORKDETAILS_MS_V + DIMHISTORYEMPLOYEE_V |
| 3. Job Abandonment | Hourly + Active + No punch in 28+ days | FACTDAILYWORKDETAILS_MS_V + DIMHISTORYEMPLOYEE_V |
| 4. Active Headcount | Active employees with punch in last 28 days of period | FACTDAILYWORKDETAILS_MS_V + DIMHISTORYEMPLOYEE_V |
| 5. Inactive Headcount | Leave (L) + Suspended (S) employees | DIMHISTORYEMPLOYEE_V |
| 6. Attrition Formula | (Terminations / Headcount) × (365 / Days) × 100 | Calculated |
| 7. Station Filter | ATL → STATIONCODE via COSTCENTER JOIN | DIMFINANCEBUSINESSSTRUCTURE_V |

**That's 7 sub-steps, 3 views, 2 JOINs, conditional logic by pay class, and a 28-day rolling window — just for ONE question.**

The LLM cannot figure this out from a prompt alone. It needs a **semantic layer** that encodes the business rules, KPI formulas, table relationships, and domain-specific logic.

**Other complex KPIs with similar depth:**
- **Overtime %** = OT Hours / Total Hours (by station, customer, service type, period)
- **Month-over-Month Headcount Trend** = Compare 28-day pay period snapshots across months
- **FTE Calculation** = Full-time equivalents weighted by employment type and hours
- **Turnover by Region/Customer/Contract** = Attrition segmented across org hierarchy levels

---

---

## SLIDE 3 — Before: How It Works Today (Without Ontology)

### The AI Chatbot Guesses — And Frequently Gets It Wrong

When someone asks *"What's the attrition rate at ATL?"*, here's what happens **today** without an ontology:

```
           TODAY'S FLOW (Without Neo4j Ontology)
           ═══════════════════════════════════════

  Executive asks:                      What goes wrong:
  ─────────────                        ────────────────

  "What's the attrition          The AI doesn't know:
   rate at ATL?"                 • What "attrition rate" means at Unifi
                                 • That hourly vs salaried are computed differently
        │                        • That "ATL" maps to a STATIONCODE via COSTCENTER
        ▼                        • That job abandonment (no punch in 28 days) counts
  ┌──────────────┐               • Which 3 tables need to be joined
  │   AI / LLM   │               • The annualization formula (×365/Days)
  │              │
  │  Has ONLY:   │
  │  • Table     │
  │    names     │              ┌──────────────────────────────┐
  │  • Column    │───────────→ │     RESULT: WRONG ANSWER     │
  │    names     │              │                              │
  │  • No biz    │              │  • Misses hourly terminations│
  │    rules     │              │  • Ignores job abandonment   │
  │  • No KPI    │              │  • Wrong headcount formula   │
  │    formulas  │              │  • No annualization          │
  └──────────────┘              │  • Joins wrong tables        │
                                │  • Returns 12% instead of 47%│
                                └──────────────────────────────┘
```

**The root cause:** The LLM only sees table and column names. It has no understanding of:

| What's Missing | Business Impact |
|---------------|-----------------|
| KPI computation recipes | AI invents its own formula — produces wrong numbers |
| Business rules (hourly vs salaried) | Misses entire categories of terminations |
| 28-day active window logic | Overcounts headcount, deflates attrition |
| Organizational hierarchy | Can't filter by station, region, or customer correctly |
| Abbreviation context | "ATL" could mean anything without domain knowledge |
| Data relationships (JOINs) | Joins wrong tables or misses required joins entirely |

**Bottom line:** Executives receive **incorrect metrics** that don't match what Finance, HR, and Operations report. Trust in the AI erodes, adoption stalls.

---

---

## SLIDE 4 — After: How It Works With Neo4j Ontology

### The AI Knows Exactly What to Compute — Every Time

The same question, *"What's the attrition rate at ATL?"*, with the Neo4j ontology:

```
           AFTER: WITH NEO4J ONTOLOGY
           ══════════════════════════════

  Executive asks:
  ─────────────

  "What's the attrition
   rate at ATL?"
        │
        ▼
  ┌──────────────────┐
  │  Intent Extractor │    Instant recognition (Neo4j-loaded dictionary):
  │  (Neo4j Terms)    │    • "attrition rate" → KPI: Attrition Rate
  └────────┬─────────┘    • "ATL" → Station Code: Atlanta
           │
           ▼
  ┌──────────────────────────────────────────────────────┐
  │              NEO4J KNOWLEDGE GRAPH                    │
  │                                                      │
  │  KPI: Attrition Rate                                 │
  │  ┌─────────────────────────────────────────────┐     │
  │  │ Step 1: Salaried terminations (PAYCLASSCODE='P')│  │
  │  │ Step 2: Hourly terminations (last punch date)   │  │
  │  │ Step 3: Job abandonment (28-day no-punch)       │  │
  │  │ Step 4: Active headcount (28-day window)        │  │
  │  │ Step 5: Leave + Suspended headcount             │  │
  │  │ Formula: (Terms / HC) × (365 / Days) × 100     │  │
  │  └─────────────────────────────────────────────┘     │
  │                                                      │
  │  Filter: ATL → STATIONCODE via COSTCENTER JOIN       │
  │  Tables: DIMHISTORYEMPLOYEE_V + FACTDAILYWORK...     │
  │          + DIMFINANCEBUSINESSSTRUCTURE_V              │
  │  Rules: Hourly logic, 28-day window, annualize       │
  └────────────────────────┬─────────────────────────────┘
                           │
              Complete recipe handed to LLM
                           │
                           ▼
                  ┌──────────────────┐
                  │     AI / LLM     │
                  │                  │
                  │  Now has:        │
                  │  • Exact formula │
                  │  • All 5 steps   │
                  │  • Correct joins │
                  │  • Business rules│
                  │  • Filter values │
                  └────────┬─────────┘
                           │
                  Generates precise SQL
                           │
                           ▼
                  ┌──────────────────┐
                  │    SQL Validator  │   Checks: safe tables, valid columns,
                  └────────┬─────────┘   no destructive ops
                           │
                           ▼
                  ┌──────────────────┐
                  │    Snowflake     │   Executes against real data
                  └────────┬─────────┘
                           │
                           ▼
              ┌──────────────────────────────┐
              │     RESULT: CORRECT ANSWER    │
              │                              │
              │  "The attrition rate at ATL   │
              │   for last month is 47.2%,    │
              │   based on 23 terminations    │
              │   (12 salaried, 8 hourly,     │
              │   3 job abandonment) out of   │
              │   489 total headcount."       │
              └──────────────────────────────┘
```

### Side-by-Side Comparison

| | Without Ontology (Today) | With Neo4j Ontology |
|---|---|---|
| **What the AI knows** | Table names and column names only | Full KPI recipe, business rules, JOIN paths, org hierarchy |
| **Attrition calculation** | AI guesses a simple COUNT | 5-step recipe with hourly/salaried logic, job abandonment, 28-day window |
| **"ATL" resolution** | May search wrong column or ignore | Resolves to STATIONCODE = 'ATL' via COSTCENTER JOIN |
| **Business rules** | None — AI makes assumptions | Encoded as graph nodes: hourly termination logic, pay class rules |
| **Answer accuracy** | ~20-30% for complex KPIs | ~95%+ — follows exact computation recipe |
| **Time to answer** | Often wrong, requires manual correction | Correct on first ask, with full breakdown |
| **Audit trail** | None — black box | Full path: Question → KPI → Steps → SQL → Result |
| **Adding new KPIs** | Rewrite prompts, redeploy code | Add nodes in Neo4j — no code change |

### What This Means for Executives

```
  ┌─────────────────────────────────────────────────────────────┐
  │                                                             │
  │   BEFORE                          AFTER                     │
  │   ──────                          ─────                     │
  │                                                             │
  │   "The attrition number           "47.2% annualized         │
  │    doesn't match what              attrition at ATL,        │
  │    HR reported."                   matching HR's report.    │
  │                                    Here's the breakdown."  │
  │                                                             │
  │   "I don't trust the               "I can see exactly how  │
  │    chatbot's numbers."              it was calculated —     │
  │                                     step by step."         │
  │                                                             │
  │   "It takes 2 days to get          "I asked and got the    │
  │    this from the analytics          answer in 3 seconds."  │
  │    team."                                                   │
  │                                                             │
  │   "We need a new KPI for           "Done — added to the    │
  │    contract profitability."         knowledge graph today." │
  │                                                             │
  └─────────────────────────────────────────────────────────────┘
```

---

---

## SLIDE 5 — Our Approach

### Neo4j as the Semantic Brain — Encoding Business Intelligence, Not Just Vocabulary

The knowledge graph doesn't just store abbreviations. It encodes **how Unifi's business works**:

```
┌─────────────────────────────────────────────────────────────┐
│                    NEO4J KNOWLEDGE GRAPH                     │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────┐  │
│  │ KPI RECIPES  │   │ TABLE SCHEMA │   │ BUSINESS RULES│  │
│  │              │   │              │   │               │  │
│  │ Attrition %  │   │ 13 Views     │   │ Salaried vs   │  │
│  │ Headcount    │   │ 150+ Columns │   │ Hourly logic  │  │
│  │ Overtime %   │   │ JOIN paths   │   │ 28-day window │  │
│  │ FTE          │   │ Column types │   │ Pay class     │  │
│  │ Turnover     │   │ FK mappings  │   │ Status rules  │  │
│  └──────────────┘   └──────────────┘   └───────────────┘  │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────┐  │
│  │ ORG HIERARCHY│   │ TERM RESOLVER│   │ RLS / SECURITY│  │
│  │              │   │              │   │               │  │
│  │ Regions      │   │ 57+ terms    │   │ Per-user      │  │
│  │ Divisions    │   │ KPI synonyms │   │ station scope │  │
│  │ Stations     │   │ Stations     │   │ Contract auth │  │
│  │ Customers    │   │ Customers    │   │ Audit trail   │  │
│  │ Contracts    │   │              │   │               │  │
│  └──────────────┘   └──────────────┘   └───────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Key Principle:** The LLM generates SQL. Neo4j tells it *what to compute, which tables to use, how to join them, what business rules apply, and what the user is authorized to see*.

---

---

## SLIDE 6 — Architecture Overview

### End-to-End Pipeline

```
┌──────────┐     ┌──────────────────┐     ┌────────────────────────┐
│  User    │────→│  FastAPI Gateway  │────→│  Step 1: Intent         │
│  (Chat)  │     │                  │     │  Extractor              │
└──────────┘     └──────────────────┘     │  (Neo4j-loaded terms)   │
                                          └────────┬───────────────┘
                                                   │
                                          Detected: KPI type, station/customer, time range
                                          (25 KPI synonyms, 21 stations, 5 customers)
                                                   │
                                                   ▼
                                          ┌──────────────────────────┐
                                          │  Step 2: Neo4j Ontology   │
                                          │  Lookup                   │
                                          │                           │
                                          │  1. Fetch KPI recipe      │
                                          │  2. Get computation steps │
                                          │  3. Map JOIN paths        │
                                          │  4. Get business rules    │
                                          │  5. Get default filters   │
                                          └────────┬─────────────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────────────┐
                                          │  Step 3: Context Builder  │
                                          │                           │
                                          │  Transforms Neo4j output  │
                                          │  into structured LLM      │
                                          │  prompt (views, joins,    │
                                          │  filters, steps, formula) │
                                          └────────┬─────────────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────────────┐
                                          │  Step 4: LLM SQL          │
                                          │  Generator                │
                                          │  (Azure OpenAI gpt-5.4)   │
                                          └────────┬─────────────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────────────┐
                                          │  Step 5: SQL Validator    │
                                          │                           │
                                          │  • SELECT-only check      │
                                          │  • Approved views/columns │
                                          │  • Security scope (RLS)   │
                                          │  • No destructive ops     │
                                          └────────┬─────────────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────┐
                                          │  Step 6: Execute  │
                                          │  (Snowflake)      │
                                          └────────┬─────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────┐
                                          │  Response to User │
                                          └──────────────────┘
```

**Technology Stack:**
- **Neo4j AuraDB:** Stores KPI recipes, schema, business rules, term dictionary, security
- **Intent Extractor:** Rule-based regex + Neo4j-loaded synonym dictionary (25 KPI phrases, 21 stations, 5 customers — all from Neo4j at startup)
- **Azure OpenAI (gpt-5.4):** Generates Snowflake SQL from structured context
- **SQL Validator:** Enforces safety, schema compliance, and per-user security scope
- **FastAPI:** High-performance Python API layer with executive-ready UI
- **Snowflake:** 13 views in `AIRCO_EDW_UAT.ILINKAICHAT` (150+ columns)

---

---

## SLIDE 7 — What Neo4j Encodes

### Six Layers of Intelligence — Beyond Term Resolution

**Layer 1: KPI Recipes** (The Core Differentiator)

Each complex KPI is stored as a graph of computation steps:

```
(KPI: Attrition Rate)
    ├── REQUIRES → (Step: Hard Term Salaried)
    │       └── USES → DIMHISTORYEMPLOYEE_V.TERMINATIONDATE
    │       └── FILTER → PAYCLASSCODE = 'P'
    ├── REQUIRES → (Step: Hard Term Hourly)
    │       └── USES → FACTDAILYWORKDETAILS_MS_V (MAX APPLYDATE)
    │       └── FILTER → PAYCLASSCODE = 'H'
    ├── REQUIRES → (Step: Job Abandonment)
    │       └── USES → FACTDAILYWORKDETAILS_MS_V
    │       └── RULE  → Active + No punch in 28 days
    ├── REQUIRES → (Step: Total Headcount)
    │       └── USES → Active + Leave + Suspended
    └── FORMULA → (Terminations / Headcount) × (365 / Days) × 100
```

**Layer 2: Schema & JOIN Paths**

| From View | To View | JOIN Key | Type |
|-----------|---------|----------|------|
| DIMHISTORYEMPLOYEE_V | DIMFINANCEBUSINESSSTRUCTURE_V | COSTCENTER | FK |
| DIMHISTORYEMPLOYEE_V | FACTDAILYWORKDETAILS_MS_V | EMPLOYEE_ID | FK |
| DIMHISTORYEMPLOYEE_V | DIMJOBTYPE_V | JOBTYPECODE | FK |
| DIMHISTORYEMPLOYEE_V | DIMSERVICETYPE_V | SERVICETYPECODE | FK |
| DIMHISTORYEMPLOYEE_V | DIMRLSCONTRACTHIERARCHY_V | EMPLOYEE_ID | FK |
| FACTDAILYWORKDETAILS_MS_V | AGGRHOURS_ACTUALHOURS_DETAILS_V | PAYCODE_CODE | REF |
| ...and 8 total JOIN paths | | | |

**Layer 3: Business Rules**

| Rule | Logic | Applied To |
|------|-------|-----------|
| Hourly termination | Use last punch date, not TERMINATIONDATE | Attrition, Turnover |
| Job abandonment | Active + No punch in 28+ days | Attrition |
| Active headcount | Status = 'A' + punch in last 28 days of period | Headcount, Attrition |
| Salaried termination | Use TERMINATIONDATE directly | Attrition |
| 28-day pay period | Rolling window for headcount calculation | Headcount, FTE |

**Layer 4: Org Hierarchy** (5-level traversal)
Grandparent Region → Region → Sub-Region → Division → Station → Customer → Contract

**Layer 5: Term Resolution** (57+ terms across 5 categories — stations, customers, KPI synonyms, employment status, pay class)

**Layer 6: Row-Level Security** (per-user station/contract/customer scope)

---

---

## SLIDE 8 — Complex KPI Example: Attrition Rate

### User Asks: *"What's the attrition rate at ATL last month?"*

**Without Neo4j:** The LLM would need to guess a 255-line SQL query. It will fail.

**With Neo4j:** The graph provides the full recipe:

```
Neo4j returns to LLM:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

KPI: Attrition Rate
FORMULA: (Total Terminations / Total Headcount) × (365 / Days in Period) × 100

TERMINATION COMPONENTS:
  1. Hard Term (Salaried): COUNT employees WHERE TERMINATIONDATE in period
     AND PAYCLASSCODE = 'P'
     TABLE: DIMHISTORYEMPLOYEE_V
     
  2. Hard Term (Hourly): COUNT employees WHERE MAX(APPLYDATE) in period
     AND PAYCLASSCODE = 'H'
     TABLES: FACTDAILYWORKDETAILS_MS_V JOIN DIMHISTORYEMPLOYEE_V ON EMPLOYEE_ID
     
  3. Job Abandonment: COUNT employees WHERE PAYCLASSCODE = 'H'
     AND EMPLOYMENTSTATUSCODE = 'A' AND TERMINATIONDATE IS NULL
     AND MAX(APPLYDATE) < (Period End - 28 days)
     TABLES: FACTDAILYWORKDETAILS_MS_V JOIN DIMHISTORYEMPLOYEE_V ON EMPLOYEE_ID

HEADCOUNT COMPONENTS:
  4. Active: COUNT DISTINCT where status = 'A' AND punch in last 28 days
  5. Leave: COUNT DISTINCT where status = 'L'
  6. Suspended: COUNT DISTINCT where status = 'S'

FILTERS:
  ATL → STATIONCODE = 'ATL'
  JOIN: DIMHISTORYEMPLOYEE_V.COSTCENTER = DIMFINANCEBUSINESSSTRUCTURE_V.COSTCENTER

PERIOD: Last month (auto-calculated)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Result:** The LLM receives a complete, structured recipe and generates accurate 255-line SQL — not a guess.

---

---

## SLIDE 9 — KPI Coverage Roadmap

### Complex Analytics the Chatbot Will Support

**Tier 1 — Core Workforce KPIs (Phase 2 target):**

| KPI | Complexity | Views Required | Business Rules |
|-----|-----------|----------------|----------------|
| **Attrition Rate** | Very High | 3 views, 3 termination types, 28-day window | Salaried vs hourly logic, JA pending, annualization |
| **Headcount** | High | 2 views, 3 status categories | Active (with punch window) + Leave + Suspended |
| **Overtime %** | Medium | 2 views | OT hours / Total hours by pay code |
| **FTE (Full-Time Equivalent)** | High | 3 views | Weighted by employment type + actual hours |
| **Turnover by Region** | Very High | 4 views | Attrition segmented by 5-level org hierarchy |
| **Month-over-Month Trend** | High | Aggregate views | 28-day period comparisons, AGGEMPCOUNT_PAY_28DAYS_V |

**Tier 2 — Operational KPIs (Phase 3):**

| KPI | Segmentation Dimensions |
|-----|------------------------|
| Hours per Station per Customer | Station × Customer × Service Type × Pay Code |
| New Hire Retention | HIREDATE-based cohort analysis over time |
| Cost per FTE | Hours × Pay class across org hierarchy |
| Staffing vs Demand | Headcount by service type vs. contract targets |

**Tier 3 — Strategic KPIs (Phase 4):**

| KPI | Data Scope |
|-----|-----------|
| Regional Performance Scorecard | All KPIs rolled up to Grandparent Region level |
| Contract Profitability Indicators | Hours + headcount + attrition per contract |
| Workforce Planning Forecasts | Trend-based projections using historical aggregate views |

---

---

## SLIDE 10 — Data Model Scope

### 13 Snowflake Views — Full Coverage

| # | View | Type | Columns | Role in Chatbot |
|---|------|------|---------|-----------------|
| 1 | DIMHISTORYEMPLOYEE_V | Dimension | 32 | Central employee record — every query touches this |
| 2 | DIMFINANCEBUSINESSSTRUCTURE_V | Dimension | 26 | Org hierarchy: Region → Station → Customer → Contract |
| 3 | FACTDAILYWORKDETAILS_MS_V | Fact | 11 | Punch-level hours — core for OT, attrition, FTE |
| 4 | DIMRLSCONTRACTHIERARCHY_V | Security | 13 | Row-Level Security — who can see what |
| 5 | AGGEMPCOUNT_ATTRITION_DATA_V | Aggregate | 5 | Pre-aggregated attrition/headcount by station |
| 6 | AGGRHOURS_ACTUALHOURS_DETAILS_V | Aggregate | 5 | Pre-aggregated hours by employee/date/paycode |
| 7 | AGGEMPCOUNT_PAY_28DAYS_V | Aggregate | 6 | 28-day pay period headcount snapshots |
| 8 | DIMJOBTYPE_V | Dimension | 5 | 700+ job codes across 24 families |
| 9 | DIMSERVICETYPE_V | Dimension | 4 | 100 service types (Ramp, Cabin, Cargo, etc.) |
| 10 | DIMEMPLOYEETYPE_V | Dimension | 2 | ADM, REG, SUP, TMP, etc. |
| 11 | DIMEMPLOYMENTSTATUS_V | Dimension | 2 | Active, Terminated, Leave, Suspended |
| 12 | DIMEMPLOYMENTSTATUS_HR_V | Dimension | 2 | HR-specific status view |
| 13 | DIMEMPLOYMENTTYPE_V | Dimension | 2 | Full-Time, Part-Time |

**Org Hierarchy Depth (DIMFINANCEBUSINESSSTRUCTURE_V):**
- **13 Grandparent Regions** (Central, East, Northeast, Southeast, West, ...)
- **13 Legal Entities** (Unifi Aviation, ERMC, Prospect, Unifi UK, ...)
- **35+ Departments** (Operations, HR, Safety, Payroll, IT, ...)
- **100 Service Types** (Ramp, Cabin, Cargo, Deicing, Security, ...)
- **Stations, Customers, Contracts** at the leaf level

---

---

## SLIDE 11 — Why Neo4j for Complex KPIs

### The Graph Advantage Over Alternatives

| Challenge | Neo4j Ontology (Our Approach) | Static Prompt / RAG | Foundry / Vector DB |
|-----------|------------------------------|---------------------|---------------------|
| **Attrition = 7-step formula** | Stored as graph recipe with steps, rules, joins | Must be hardcoded in prompt (breaks at scale) | Not designed for computation graphs |
| **Salaried vs Hourly logic** | Business rules as graph nodes with conditions | Prompt engineering for each edge case | Requires custom coding per KPI |
| **28-day rolling window** | Rule node with parameterized date logic | Hardcoded date math in prompt | Separate logic layer needed |
| **5-level org hierarchy drill** | Graph traversal (Region → Station → Contract) | Flattened, no traversal | Requires manual hierarchy mapping |
| **Add a new KPI** | Add nodes + edges in Neo4j, no code change | Rewrite prompt, redeploy | Retrain / re-index |
| **Row-Level Security** | User → authorized stations/contracts as graph edges | Hardcoded WHERE clauses | Separate security system |
| **Auditability** | Graph path: Question → KPI → Steps → SQL | Black box | Similarity scores only |

**The Core Advantage:**
> Neo4j doesn't just resolve words — it encodes **how Unifi computes its KPIs**. When a new KPI is added, it's a graph update, not a code change.

---

---

## SLIDE 12 — Roadmap & Summary

### Phased Delivery Plan

```
Phase 1 (DONE ✓)            Phase 2 (4 weeks)           Phase 3 (4 weeks)           Phase 4 (3 weeks)
─────────────────          ──────────────────          ──────────────────          ──────────────────
POC — Full NL2SQL Pipeline  Scale KPIs + Schema         RLS + Ops KPIs             Production
                                                                                  
• End-to-end pipeline live  • Overtime % recipe         • DIMRLSCONTRACTHIERARCHY  • Load testing
• Attrition Rate (complex)  • FTE calculation recipe    • Per-user scope in graph  • Admin UI for KPIs
• Headcount (simple)        • Turnover by Region        • Staffing vs Demand       • Monitoring + alerts
• Neo4j ontology (terms,    • Full 13 views + columns   • New Hire Retention       • CI/CD pipeline
  KPI recipes, rules, joins)• Org hierarchy (5 levels)  • Cost per FTE             • Documentation
• Azure OpenAI integration  • 700+ job codes, 100 svc   • Regional scorecards      • Ops handoff
• SQL Validator (security)  • Business rules as nodes   • Audit logging            •
• Executive-ready UI        • Month-over-month trends   • Trend/forecasting KPIs   •
```

### Key Takeaways

| What | Detail |
|------|--------|
| **The Problem** | Workforce KPIs like attrition require multi-step, multi-table, rule-heavy SQL (255+ lines) that LLMs cannot reliably generate without structured guidance |
| **The Solution** | Neo4j knowledge graph encodes KPI recipes, schema, business rules, org hierarchy, and security — feeding the LLM exactly what it needs |
| **The Result** | Accurate, auditable, secure workforce analytics via natural language — attrition, headcount, overtime, FTE, and more |
| **The Ask** | Approve Phase 2: 4-week sprint to encode core KPI recipes and full schema into Neo4j |
| **The Promise** | Every complex workforce question answered correctly, first time, with full audit trail |

---

*iLink Systems Inc. — Confidential*
