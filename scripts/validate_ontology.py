"""
Validate ontology: runs structural checks against Neo4j.
Usage: python -m scripts.validate_ontology
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging_config import setup_logging
from ontology.validator import validate_ontology


def main():
    setup_logging()
    print("Running ontology structural validation...\n")
    results = validate_ontology()
    print(f"Overall: {results['overall']}\n")
    for item in results["passed"]:
        print(f"  PASS: {item}")
    for item in results["warnings"]:
        print(f"  WARN: {item}")
    for item in results["failed"]:
        print(f"  FAIL: {item}")

    sys.exit(0 if results["overall"] == "PASSED" else 1)


if __name__ == "__main__":
    main()
