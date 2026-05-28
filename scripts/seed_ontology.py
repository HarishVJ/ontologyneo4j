"""
Seed ontology: loads all YAML definitions into Neo4j.
Run this after any ontology YAML changes.

Usage: python -m scripts.seed_ontology
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging_config import setup_logging
from ontology.loader import load_all
from ontology.validator import validate_ontology


def main():
    setup_logging()
    print("=" * 60)
    print("  Seeding Neo4j Ontology from YAML")
    print("=" * 60)

    counts = load_all()
    print(f"\nLoaded: {counts}")

    print("\nRunning structural validation...")
    results = validate_ontology()
    print(f"\nOverall: {results['overall']}")
    for item in results["passed"]:
        print(f"  ✓ {item}")
    for item in results["warnings"]:
        print(f"  ⚠ {item}")
    for item in results["failed"]:
        print(f"  ✗ {item}")


if __name__ == "__main__":
    main()
