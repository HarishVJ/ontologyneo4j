"""
Ontology Loader: reads YAML definitions and loads them into Neo4j.
Idempotent — uses MERGE to create-or-update. Safe to re-run.
"""

import yaml
from pathlib import Path
from core.neo4j_client import get_driver
from config.logging_config import get_logger

logger = get_logger(__name__)
ONTOLOGY_DIR = Path(__file__).parent


def load_all() -> dict[str, int]:
    counts = {}
    _clear_ontology()
    counts["views"] = _load_views()
    counts["joins"] = _load_joins()
    counts["terms"] = _load_terms()
    counts["disambiguation"] = _load_disambiguation()
    counts["kpis"] = _load_kpis()
    counts["roles"] = _load_roles()
    logger.info("ontology_loaded", **counts)
    return counts


def _clear_ontology():
    driver = get_driver()
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    logger.info("ontology_cleared")


def _load_views() -> int:
    with open(ONTOLOGY_DIR / "schema" / "views.yaml") as f:
        data = yaml.safe_load(f)
    driver = get_driver()
    count = 0
    with driver.session() as session:
        for view in data.get("views", []):
            columns = [c["name"] for c in view.get("columns", [])]
            aliases = view.get("approved_aliases", [])
            session.run(
                "MERGE (v:View {name: $name}) "
                "SET v.schema=$schema, v.alias=$alias, v.description=$desc, "
                "v.columns=$columns, v.column_count=$cc, v.approved_aliases=$aliases",
                {"name": view["name"], "schema": view.get("schema",""),
                 "alias": view.get("alias",""), "desc": view.get("description",""),
                 "columns": columns, "cc": len(columns), "aliases": aliases},
            )
            count += 1
    logger.info("views_loaded", count=count)
    return count


def _load_joins() -> int:
    with open(ONTOLOGY_DIR / "schema" / "joins.yaml") as f:
        data = yaml.safe_load(f)
    driver = get_driver()
    count = 0
    with driver.session() as session:
        for join in data.get("joins", []):
            session.run(
                "MATCH (fv:View {name:$fv}), (tv:View {name:$tv}) "
                "MERGE (fv)-[j:JOINS_TO {to_view:$tv}]->(tv) "
                "SET j.condition=$cond, j.type=$jtype, j.description=$desc, "
                "j.from_alias=$fa, j.to_alias=$ta, j.via=$via",
                {"fv": join["from_view"], "tv": join["to_view"],
                 "cond": join["condition"], "jtype": join.get("type","INNER"),
                 "desc": join.get("description",""),
                 "fa": join.get("from_alias",""), "ta": join.get("to_alias",""),
                 "via": join.get("via","")},
            )
            count += 1
    logger.info("joins_loaded", count=count)
    return count


def _load_disambiguation() -> int:
    disambiguation_file = ONTOLOGY_DIR / "schema" / "disambiguation.yaml"
    if not disambiguation_file.exists():
        logger.info("disambiguation_skipped", reason="file not found")
        return 0
    with open(disambiguation_file) as f:
        data = yaml.safe_load(f)
    driver = get_driver()
    count = 0
    with driver.session() as session:
        for rule in data.get("rules", []):
            term = rule["term"]
            for meaning in rule.get("meanings", []):
                session.run(
                    "MERGE (d:DisambiguationRule {term:$term, context:$ctx}) "
                    "SET d.resolves_to=$resolves, d.column=$col, d.value=$val, "
                    "d.description=$desc, d.applies_to_views=$views",
                    {"term": term, "ctx": meaning.get("context","any"),
                     "resolves": meaning.get("resolves_to",""),
                     "col": meaning.get("column",""),
                     "val": meaning.get("value",""),
                     "desc": meaning.get("description",""),
                     "views": meaning.get("applies_to_views",[])},
                )
                count += 1
    logger.info("disambiguation_loaded", count=count)
    return count


def _load_terms() -> int:
    with open(ONTOLOGY_DIR / "schema" / "terms.yaml") as f:
        data = yaml.safe_load(f)
    driver = get_driver()
    count = 0
    with driver.session() as session:
        for category in data.get("categories", []):
            cat_name = category["name"]
            cat_column = category.get("column")
            for term in category.get("terms", []):
                session.run(
                    "MERGE (t:Term {code: $code, category: $cat}) "
                    "SET t.canonical=$canonical, t.column=$col, t.context=$ctx",
                    {"code": term["code"], "cat": cat_name,
                     "canonical": term.get("canonical", term["code"]),
                     "col": cat_column, "ctx": term.get("context","")},
                )
                count += 1
    logger.info("terms_loaded", count=count)
    return count


def _load_kpis() -> int:
    kpis_dir = ONTOLOGY_DIR / "kpis"
    driver = get_driver()
    count = 0
    for yaml_file in kpis_dir.glob("*.yaml"):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        with driver.session() as session:
            for kpi in data.get("kpis", []):
                # Create KPI node
                output_shape = kpi.get("output_shape", {})
                session.run(
                    "MERGE (k:KPI {id: $id}) "
                    "SET k.name=$name, k.description=$desc, k.complexity=$cx, "
                    "k.formula=$formula, k.version=$ver, k.status=$status, "
                    "k.owner=$owner, k.valid_from=$vf, "
                    "k.output_shape_type=$ost, k.output_columns=$oc, k.order_by=$ob",
                    {"id": kpi["id"], "name": kpi["name"],
                     "desc": kpi.get("description",""), "cx": kpi.get("complexity","simple"),
                     "formula": kpi.get("formula",""), "ver": kpi.get("version","1.0"),
                     "status": kpi.get("status","active"), "owner": kpi.get("owner",""),
                     "vf": kpi.get("valid_from",""),
                     "ost": output_shape.get("type","list"),
                     "oc": output_shape.get("columns",[]),
                     "ob": output_shape.get("order_by",[])},
                )
                # Link KPI → View
                for view_name in kpi.get("views", []):
                    session.run(
                        "MATCH (k:KPI {id:$kid}), (v:View {name:$vn}) MERGE (k)-[:USES_VIEW]->(v)",
                        {"kid": kpi["id"], "vn": view_name},
                    )
                # Create steps
                for step in kpi.get("steps", []):
                    session.run(
                        "MATCH (k:KPI {id:$kid}) "
                        "MERGE (s:KPIStep {name:$sn, kpi_id:$kid}) "
                        "SET s.order=$ord, s.logic=$logic, s.required_columns=$rc "
                        "MERGE (k)-[:REQUIRES_STEP]->(s)",
                        {"kid": kpi["id"], "sn": step["name"],
                         "ord": step["order"], "logic": step.get("logic",""),
                         "rc": step.get("required_columns",[])},
                    )
                # Create filters
                for filt in kpi.get("filters", []):
                    session.run(
                        "MATCH (k:KPI {id:$kid}) "
                        "MERGE (f:Filter {column:$col, kpi_id:$kid}) "
                        "SET f.source=$src, f.operator=$op "
                        "MERGE (k)-[:HAS_FILTER]->(f)",
                        {"kid": kpi["id"], "col": filt["column"],
                         "src": filt.get("source",""), "op": filt.get("operator","=")},
                    )
                # Link synonyms to KPI
                for syn in kpi.get("synonyms", []):
                    session.run(
                        "MERGE (t:Term {code:$code, category:'kpi_synonyms'}) "
                        "SET t.canonical=$canonical, t.kpi_id=$kid",
                        {"code": syn, "canonical": kpi["name"], "kid": kpi["id"]},
                    )
                count += 1
    logger.info("kpis_loaded", count=count)
    return count


def _load_roles() -> int:
    roles_file = ONTOLOGY_DIR / "security" / "roles.yaml"
    with open(roles_file) as f:
        data = yaml.safe_load(f)
    driver = get_driver()
    count = 0
    with driver.session() as session:
        for role in data.get("roles", []):
            session.run(
                "MERGE (u:User {user_id:$uid}) "
                "SET u.email=$email, u.authorized_stations=$stations, "
                "u.authorized_customers=$customers, u.description=$desc",
                {"uid": role["user_id"], "email": role.get("email",""),
                 "stations": role.get("authorized_stations",[]),
                 "customers": role.get("authorized_customers",[]),
                 "desc": role.get("description","")},
            )
            count += 1
    logger.info("roles_loaded", count=count)
    return count
