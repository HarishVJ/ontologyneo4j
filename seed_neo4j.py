"""
Seed Neo4j AuraDB for the NL2SQL Ontology POC.

Creates a structured knowledge graph encoding:
  - KPI Recipes with computation steps, formulas, and business rules
  - Snowflake Views with columns and join paths
  - Term dictionary (stations, status codes, pay classes, etc.)
  - Security scope definitions

Run once:
    python seed_neo4j_v2.py
"""

import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER")
PASSWORD = os.getenv("NEO4J_PASSWORD")

SCHEMA = "AIRCO_EDW_UAT.ILINKAICHAT"

# ═══════════════════════════════════════════════════════════════
# 1. VIEWS (Snowflake Entities)
# ═══════════════════════════════════════════════════════════════
VIEWS = [
    {
        "name": "DIMHISTORYEMPLOYEE_V",
        "alias": "e",
        "type": "dimension",
        "description": "Core employee dimension — profiles, status, pay class, termination dates",
        "columns": [
            "EMPLOYEE_ID", "FIRSTNAME", "LASTNAME", "FULLNAME",
            "HIREDATE", "EMPLOYMENTSTATUSCODE", "EMPLOYMENTTYPECODE",
            "EMPLOYEETYPECODE", "PAYCLASSCODE", "COSTCENTER",
            "DEPARTMENTCODE", "LOCATIONCODE", "JOBTYPECODE",
            "STATIONCODE", "CUSTOMERCODE", "SERVICETYPECODE",
            "TERMINATIONDATE", "MANAGERID", "COMPANYCODE", "DIVISIONCODE",
        ],
    },
    {
        "name": "DIMFINANCEBUSINESSSTRUCTURE_V",
        "alias": "b",
        "type": "dimension",
        "description": "Org hierarchy — regions, stations, customers, contracts, cost centers",
        "columns": [
            "GRANDPARENTREGIONCODE", "GRANDPARENTREGIONNAME",
            "REGIONCODE", "REGIONNAME", "ENTITYCODE", "ENTITYDESCRIPTION",
            "DIVISIONCODE", "DIVISIONNAME", "STATIONCODE", "STATIONNAME",
            "CUSTOMERCODE", "CUSTOMERNAME", "SERVICETYPECODE", "SERVICETYPENAME",
            "CONTRACTCODE", "CONTRACTNAME", "COSTCENTER", "DEPARTMENTNAME",
        ],
    },
    {
        "name": "FACTDAILYWORKDETAILS_MS_V",
        "alias": "f",
        "type": "fact",
        "description": "Daily punch-level work details — hours, pay codes, dates",
        "columns": [
            "EMPLOYEE_ID", "PUNCHID", "APPLYDATE",
            "PAYCODE_CODE", "PUNCH_HOURS",
        ],
    },
]

# ═══════════════════════════════════════════════════════════════
# 2. JOIN PATHS
# ═══════════════════════════════════════════════════════════════
JOIN_PATHS = [
    {
        "from_view": "DIMHISTORYEMPLOYEE_V",
        "to_view": "DIMFINANCEBUSINESSSTRUCTURE_V",
        "condition": "e.COSTCENTER = b.COSTCENTER",
    },
    {
        "from_view": "DIMHISTORYEMPLOYEE_V",
        "to_view": "FACTDAILYWORKDETAILS_MS_V",
        "condition": "e.EMPLOYEE_ID = f.EMPLOYEE_ID",
    },
]

# ═══════════════════════════════════════════════════════════════
# 3. KPI RECIPES
# ═══════════════════════════════════════════════════════════════
KPI_RECIPES = [
    {
        "id": "kpi_headcount",
        "name": "Headcount",
        "complexity": "simple",
        "formula": "COUNT(DISTINCT e.EMPLOYEE_ID)",
        "description": "Count of active employees at a given station/location",
        "required_views": ["DIMHISTORYEMPLOYEE_V", "DIMFINANCEBUSINESSSTRUCTURE_V"],
        "default_filters": [
            {"column": "e.EMPLOYMENTSTATUSCODE", "operator": "=", "value": "A"},
        ],
        "allowed_columns": [
            "e.EMPLOYEE_ID", "e.COSTCENTER", "e.EMPLOYMENTSTATUSCODE",
            "b.COSTCENTER", "b.STATIONCODE",
        ],
        "steps": [
            {
                "name": "Active Employee Count",
                "order": 1,
                "logic": "Count distinct employees with EMPLOYMENTSTATUSCODE = 'A'",
                "required_columns": ["e.EMPLOYEE_ID", "e.EMPLOYMENTSTATUSCODE"],
            },
        ],
    },
    {
        "id": "kpi_attrition_rate",
        "name": "Attrition Rate",
        "complexity": "complex",
        "formula": "(total_terminations / total_headcount) * (365 / days_in_period) * 100",
        "description": "Annualized attrition rate using Unifi workforce rules",
        "required_views": [
            "DIMHISTORYEMPLOYEE_V",
            "FACTDAILYWORKDETAILS_MS_V",
            "DIMFINANCEBUSINESSSTRUCTURE_V",
        ],
        "default_filters": [],
        "allowed_columns": [
            "e.EMPLOYEE_ID", "e.COSTCENTER", "e.TERMINATIONDATE",
            "e.PAYCLASSCODE", "e.EMPLOYMENTSTATUSCODE",
            "f.EMPLOYEE_ID", "f.APPLYDATE",
            "b.COSTCENTER", "b.STATIONCODE",
        ],
        "steps": [
            {
                "name": "Salaried Terminations",
                "order": 1,
                "logic": "Count employees with TERMINATIONDATE between start_date and end_date and PAYCLASSCODE = 'P'",
                "required_columns": ["e.EMPLOYEE_ID", "e.TERMINATIONDATE", "e.PAYCLASSCODE"],
            },
            {
                "name": "Hourly Terminations",
                "order": 2,
                "logic": "Count hourly employees where MAX(f.APPLYDATE) falls between start_date and end_date and PAYCLASSCODE = 'H'",
                "required_columns": ["e.EMPLOYEE_ID", "e.PAYCLASSCODE", "f.APPLYDATE"],
            },
            {
                "name": "Job Abandonment",
                "order": 3,
                "logic": "Count hourly active employees with no punch in 28 or more days",
                "required_columns": ["e.EMPLOYEE_ID", "e.PAYCLASSCODE", "e.EMPLOYMENTSTATUSCODE", "f.APPLYDATE"],
            },
            {
                "name": "Active Headcount",
                "order": 4,
                "logic": "Count active employees with punch activity in the last 28 days of the period",
                "required_columns": ["e.EMPLOYEE_ID", "e.EMPLOYMENTSTATUSCODE", "f.APPLYDATE"],
            },
            {
                "name": "Leave Suspended Headcount",
                "order": 5,
                "logic": "Count employees with EMPLOYMENTSTATUSCODE in ('L', 'S')",
                "required_columns": ["e.EMPLOYEE_ID", "e.EMPLOYMENTSTATUSCODE"],
            },
        ],
    },
]

# ═══════════════════════════════════════════════════════════════
# 4. TERMS DICTIONARY
# ═══════════════════════════════════════════════════════════════
TERMS = {
    "stations": {
        "column": "b.STATIONCODE",
        "values": {
            "ATL": "Atlanta", "LAX": "Los Angeles", "JFK": "New York JFK",
            "LGA": "LaGuardia", "ORD": "Chicago O'Hare", "DFW": "Dallas/Fort Worth",
            "DEN": "Denver", "SEA": "Seattle", "SFO": "San Francisco",
            "MIA": "Miami", "CLT": "Charlotte", "EWR": "Newark",
            "MSP": "Minneapolis", "DTW": "Detroit", "LAS": "Las Vegas",
            "PHX": "Phoenix", "MCO": "Orlando", "BOS": "Boston",
            "IAH": "Houston", "SLC": "Salt Lake City", "PHL": "Philadelphia",
        },
    },
    "employment_status": {
        "column": "e.EMPLOYMENTSTATUSCODE",
        "values": {
            "A": "Active", "T": "Terminated", "L": "Leave of Absence", "S": "Suspended",
        },
    },
    "pay_class": {
        "column": "e.PAYCLASSCODE",
        "values": {"H": "Hourly", "P": "Salaried"},
    },
    "kpi_names": {
        "column": None,
        "values": {
            "headcount": "Headcount", "HC": "Headcount",
            "head count": "Headcount", "employee count": "Headcount",
            "how many people": "Headcount", "how many employees": "Headcount",
            "staff count": "Headcount", "total employees": "Headcount",
            "number of employees": "Headcount", "employee numbers": "Headcount",
            "workforce size": "Headcount", "total staff": "Headcount",
            "attrition": "Attrition Rate", "attrition rate": "Attrition Rate",
            "turnover": "Attrition Rate", "turnover rate": "Attrition Rate",
            "people leaving": "Attrition Rate", "quit rate": "Attrition Rate",
            "employee turnover": "Attrition Rate", "churn rate": "Attrition Rate",
            "resignation rate": "Attrition Rate", "retention": "Attrition Rate",
            "overtime": "Overtime Percentage", "OT %": "Overtime Percentage",
            "overtime percentage": "Overtime Percentage",
        },
    },
    "customers": {
        "column": "b.CUSTOMERCODE",
        "values": {
            "DL": "Delta Air Lines", "AA": "American Airlines", "UA": "United Airlines",
            "WN": "Southwest Airlines", "AS": "Alaska Airlines",
        },
    },
}

# ═══════════════════════════════════════════════════════════════
# 5. BUSINESS RULES
# ═══════════════════════════════════════════════════════════════
BUSINESS_RULES = [
    {
        "id": "rule_hourly_term",
        "name": "Hourly Termination Logic",
        "applies_to": "kpi_attrition_rate",
        "description": "For hourly employees (PAYCLASSCODE='H'), use last punch date (MAX APPLYDATE) as termination indicator, not TERMINATIONDATE",
    },
    {
        "id": "rule_salaried_term",
        "name": "Salaried Termination Logic",
        "applies_to": "kpi_attrition_rate",
        "description": "For salaried employees (PAYCLASSCODE='P'), use TERMINATIONDATE directly",
    },
    {
        "id": "rule_ja_28day",
        "name": "Job Abandonment (28-Day Rule)",
        "applies_to": "kpi_attrition_rate",
        "description": "Hourly + Active + No punch in 28+ days = Job Abandonment",
    },
    {
        "id": "rule_active_hc_window",
        "name": "Active Headcount 28-Day Window",
        "applies_to": "kpi_attrition_rate",
        "description": "Active headcount requires a punch in the last 28 days of the period",
    },
    {
        "id": "rule_annualize",
        "name": "Annualize Attrition",
        "applies_to": "kpi_attrition_rate",
        "description": "Attrition = (Terminations / Headcount) * (365 / Days_in_Period) * 100",
    },
]


def seed():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    print(f"Connecting to {URI}...")

    with driver.session() as session:
        # ── Clean existing data ──
        print("Clearing existing graph...")
        session.run("MATCH (n) DETACH DELETE n")

        # ── Create constraints ──
        print("Creating constraints...")
        session.run("CREATE CONSTRAINT view_unique IF NOT EXISTS FOR (v:View) REQUIRE v.name IS UNIQUE")
        session.run("CREATE CONSTRAINT kpi_unique IF NOT EXISTS FOR (k:KPI) REQUIRE k.id IS UNIQUE")
        session.run("CREATE CONSTRAINT term_unique IF NOT EXISTS FOR (t:Term) REQUIRE t.code IS UNIQUE")

        # ── 1. Create View nodes ──
        print("Creating View nodes...")
        for v in VIEWS:
            session.run(
                """
                CREATE (view:View {
                    name: $name, alias: $alias, type: $type,
                    description: $description, columns: $columns
                })
                """,
                name=v["name"], alias=v["alias"], type=v["type"],
                description=v["description"], columns=v["columns"],
            )
        print(f"   {len(VIEWS)} views created")

        # ── 2. Create JOIN path edges ──
        print("Creating JOIN paths...")
        for jp in JOIN_PATHS:
            session.run(
                """
                MATCH (a:View {name: $from_view})
                MATCH (b:View {name: $to_view})
                CREATE (a)-[:JOINS_TO {condition: $condition}]->(b)
                """,
                from_view=jp["from_view"], to_view=jp["to_view"],
                condition=jp["condition"],
            )
        print(f"   {len(JOIN_PATHS)} join paths created")

        # ── 3. Create KPI nodes with steps ──
        print("Creating KPI recipes...")
        for kpi in KPI_RECIPES:
            session.run(
                """
                CREATE (k:KPI {
                    id: $id, name: $name, complexity: $complexity,
                    formula: $formula, description: $description,
                    required_views: $required_views,
                    allowed_columns: $allowed_columns
                })
                """,
                id=kpi["id"], name=kpi["name"], complexity=kpi["complexity"],
                formula=kpi["formula"], description=kpi["description"],
                required_views=kpi["required_views"],
                allowed_columns=kpi["allowed_columns"],
            )
            # Create step nodes linked to KPI
            for step in kpi["steps"]:
                session.run(
                    """
                    MATCH (k:KPI {id: $kpi_id})
                    CREATE (s:KPIStep {
                        name: $name, order: $order,
                        logic: $logic, required_columns: $required_columns
                    })
                    CREATE (k)-[:REQUIRES_STEP]->(s)
                    """,
                    kpi_id=kpi["id"], name=step["name"], order=step["order"],
                    logic=step["logic"], required_columns=step["required_columns"],
                )
            # Create default filter nodes
            for f in kpi.get("default_filters", []):
                session.run(
                    """
                    MATCH (k:KPI {id: $kpi_id})
                    CREATE (flt:Filter {column: $column, operator: $operator, value: $value})
                    CREATE (k)-[:HAS_DEFAULT_FILTER]->(flt)
                    """,
                    kpi_id=kpi["id"], column=f["column"],
                    operator=f["operator"], value=f["value"],
                )
            # Link KPI to required views
            for view_name in kpi["required_views"]:
                session.run(
                    """
                    MATCH (k:KPI {id: $kpi_id})
                    MATCH (v:View {name: $view_name})
                    CREATE (k)-[:USES_VIEW]->(v)
                    """,
                    kpi_id=kpi["id"], view_name=view_name,
                )
        print(f"   {len(KPI_RECIPES)} KPIs created")

        # ── 4. Create Term nodes ──
        print("Creating Term nodes...")
        term_count = 0
        for category, data in TERMS.items():
            for code, canonical in data["values"].items():
                session.run(
                    """
                    CREATE (t:Term {
                        code: $code, canonical: $canonical,
                        category: $category, column: $column
                    })
                    """,
                    code=code, canonical=canonical,
                    category=category, column=data["column"] or "",
                )
                term_count += 1
        print(f"   {term_count} terms created")

        # ── 5. Create Business Rule nodes ──
        print("Creating Business Rules...")
        for rule in BUSINESS_RULES:
            session.run(
                """
                CREATE (r:BusinessRule {
                    id: $id, name: $name,
                    applies_to: $applies_to,
                    description: $description
                })
                """,
                id=rule["id"], name=rule["name"],
                applies_to=rule["applies_to"],
                description=rule["description"],
            )
            # Link to KPI
            session.run(
                """
                MATCH (r:BusinessRule {id: $rule_id})
                MATCH (k:KPI {id: $kpi_id})
                CREATE (k)-[:HAS_RULE]->(r)
                """,
                rule_id=rule["id"], kpi_id=rule["applies_to"],
            )
        print(f"   {len(BUSINESS_RULES)} rules created")

    driver.close()
    print("\n✓ Neo4j seeded successfully!")
    print(f"  Views: {len(VIEWS)}")
    print(f"  KPIs: {len(KPI_RECIPES)}")
    print(f"  Terms: {term_count}")
    print(f"  Rules: {len(BUSINESS_RULES)}")
    print(f"  Joins: {len(JOIN_PATHS)}")


if __name__ == "__main__":
    seed()
