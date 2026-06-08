from core.neo4j_client import execute_query, get_driver

# Check before clear
records = execute_query("MATCH (tc:TermCategory) RETURN count(tc) AS cnt")
print(f"Before clear: {records[0]['cnt']} TermCategory nodes")

# Clear ontology
driver = get_driver()
with driver.session() as s:
    s.run("MATCH (n) DETACH DELETE n")

records = execute_query("MATCH (tc:TermCategory) RETURN count(tc) AS cnt")
print(f"After clear: {records[0]['cnt']} TermCategory nodes")
