"""
Seed Neo4j with the lean semantic ontology.
Run after any YAML edit:

    python -m scripts.seed_ontology
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging_config import setup_logging
from ontology.loader import load_all
from ontology.validator import validate_ontology


def main() -> int:
    setup_logging()
    print("=" * 60)
    print("  Seeding Neo4j Ontology from YAML")
    print("=" * 60)

    counts = load_all()
    print("\nLoaded:")
    for k, v in counts.items():
        print(f"  {k:10s} {v}")

    print("\nRunning structural validation...")
    results = validate_ontology()
    print(f"\nOverall: {results['overall']}\n")
    for item in results["passed"]:
        print(f"  PASS  {item}")
    for item in results["warnings"]:
        print(f"  WARN  {item}")
    for item in results["failed"]:
        print(f"  FAIL  {item}")

    return 0 if results["overall"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
