"""Reproducer for pipeline KeyError: 'name'"""
import traceback
from core.intent_extractor import extract, load_terms_from_neo4j
from core.ontology_lookup import lookup_kpi
from core.context_builder import build_context
from core.neo4j_client import verify_connectivity

verify_connectivity()
load_terms_from_neo4j()

questions = [
    "Give me the stations whose attrition is more than 10% in the last quarter",
    "What is the attrition rate for January 2026?",
    "What is the attrition rate for ATL January 2026?",
]

for q in questions:
    print(f"\n{'='*60}\nQUESTION: {q}\n{'='*60}")
    try:
        extraction = extract(q)
        print(f"Detected KPI: {extraction.detected_kpi}")
        if extraction.detected_kpi:
            recipe = lookup_kpi(extraction.detected_kpi)
            print(f"Recipe: {recipe.name if recipe else None}")
            if recipe:
                context = build_context(extraction, recipe)
                print(f"Context built. Views: {len(context.views)}")
    except Exception as e:
        traceback.print_exc()
