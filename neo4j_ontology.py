"""
Neo4j Ontology Lookup Module

Responsibility: Query Neo4j knowledge graph for KPI recipes, views,
join paths, filters, computation steps, and allowed columns.

Component: Ontology Lookup
Owner: Neo4j
"""

import os
from typing import Optional
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()


class Neo4jOntology:
    """Queries Neo4j for structured KPI context."""

    def __init__(self):
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USER")
        password = os.getenv("NEO4J_PASSWORD")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        # Verify connectivity
        self.driver.verify_connectivity()

    def close(self):
        self.driver.close()

    def lookup_kpi(
        self,
        kpi_name: str,
        station_filter: Optional[str] = None,
        period: Optional[dict] = None,
    ) -> dict:
        """
        Look up KPI recipe from Neo4j and return structured context.

        Returns the exact format expected by the Structured Context Builder.
        """
        with self.driver.session() as session:
            # 1. Fetch KPI node
            kpi_result = session.run(
                """
                MATCH (k:KPI)
                WHERE toLower(k.name) = toLower($name)
                RETURN k.id AS id, k.name AS name, k.complexity AS complexity,
                       k.formula AS formula, k.description AS description,
                       k.required_views AS required_views,
                       k.allowed_columns AS allowed_columns
                """,
                name=kpi_name,
            ).single()

            if not kpi_result:
                return {"error": f"KPI '{kpi_name}' not found in ontology"}

            kpi_id = kpi_result["id"]

            # 2. Fetch computation steps
            steps_result = session.run(
                """
                MATCH (k:KPI {id: $kpi_id})-[:REQUIRES_STEP]->(s:KPIStep)
                RETURN s.name AS name, s.order AS order,
                       s.logic AS logic, s.required_columns AS required_columns
                ORDER BY s.order
                """,
                kpi_id=kpi_id,
            )
            steps = [
                {
                    "name": r["name"],
                    "order": r["order"],
                    "logic": r["logic"],
                    "required_columns": r["required_columns"],
                }
                for r in steps_result
            ]

            # 3. Fetch join paths for required views
            required_views = kpi_result["required_views"]
            join_paths = []
            for view_name in required_views:
                joins = session.run(
                    """
                    MATCH (a:View {name: $view_name})-[j:JOINS_TO]->(b:View)
                    WHERE b.name IN $all_views
                    RETURN a.name AS from_view, b.name AS to_view, j.condition AS condition
                    """,
                    view_name=view_name, all_views=required_views,
                )
                for j in joins:
                    join_entry = {
                        "from": j["from_view"],
                        "to": j["to_view"],
                        "condition": j["condition"],
                    }
                    if join_entry not in join_paths:
                        join_paths.append(join_entry)

            # 4. Fetch default filters
            default_filters = []
            filters_result = session.run(
                """
                MATCH (k:KPI {id: $kpi_id})-[:HAS_DEFAULT_FILTER]->(f:Filter)
                RETURN f.column AS column, f.operator AS operator, f.value AS value
                """,
                kpi_id=kpi_id,
            )
            for f in filters_result:
                default_filters.append({
                    "column": f["column"],
                    "operator": f["operator"],
                    "value": f["value"],
                })

            # 5. Build filters list (default + station)
            filters = list(default_filters)
            if station_filter:
                filters.append({
                    "column": "b.STATIONCODE",
                    "operator": "=",
                    "value": station_filter,
                })

            # 6. Assemble structured result
            result = {
                "kpi": kpi_result["name"],
                "complexity": kpi_result["complexity"],
                "formula": kpi_result["formula"],
                "description": kpi_result["description"],
                "required_views": required_views,
                "join_paths": join_paths,
                "filters": filters,
                "allowed_columns": kpi_result["allowed_columns"],
            }

            if steps:
                result["steps"] = steps

            if period:
                result["period"] = period

            return result

    def get_view_aliases(self) -> dict:
        """Return mapping of view name to alias."""
        with self.driver.session() as session:
            result = session.run("MATCH (v:View) RETURN v.name AS name, v.alias AS alias")
            return {r["name"]: r["alias"] for r in result}
