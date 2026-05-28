"""
Extract Snowflake metadata: pulls INFORMATION_SCHEMA columns for ILINKAICHAT views.
Outputs a views.yaml-compatible format.

Usage: python -m scripts.extract_snowflake_meta
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from core.snowflake_executor import execute_sql


def main():
    settings = get_settings()
    sql = f"""
    SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
    FROM {settings.snowflake_database}.INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = '{settings.snowflake_schema}'
    ORDER BY TABLE_NAME, ORDINAL_POSITION
    """
    print(f"Querying INFORMATION_SCHEMA for schema: {settings.snowflake_schema}...")
    result = execute_sql(sql)

    if result.get("error"):
        print(f"Error: {result['error']}")
        return

    # Group by view
    views = {}
    for row in result.get("rows", []):
        vname = row.get("TABLE_NAME", "")
        if vname not in views:
            views[vname] = []
        dtype = row.get("DATA_TYPE", "VARCHAR")
        max_len = row.get("CHARACTER_MAXIMUM_LENGTH", "")
        type_str = f"{dtype}({max_len})" if max_len else dtype
        views[vname].append({"name": row["COLUMN_NAME"], "type": type_str})

    # Output YAML
    print("\n# Generated views.yaml snippet:")
    print("views:")
    for vname, cols in sorted(views.items()):
        print(f"  - name: {vname}")
        print(f"    schema: {settings.snowflake_database}.{settings.snowflake_schema}")
        print(f"    alias: {vname[0].lower()}")
        print(f"    columns:")
        for col in cols:
            print(f'      - {{ name: {col["name"]}, type: {col["type"]} }}')


if __name__ == "__main__":
    main()
