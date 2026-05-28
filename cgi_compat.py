"""
Python 3.14 compatibility shim.
The 'cgi' module was removed in 3.13+. Snowflake connector's old botocore depends on it.
This module provides the minimal subset needed by botocore.vendored.requests.
Import this BEFORE importing snowflake.connector.
"""

import sys

if "cgi" not in sys.modules:
    import email.parser
    import tempfile
    import os

    class _FieldStorage:
        pass

    class _Module:
        """Minimal cgi stub."""
        FieldStorage = _FieldStorage

        @staticmethod
        def parse_header(line):
            """Parse a MIME header into main value and parameters dict."""
            parts = line.split(";")
            key = parts[0].strip()
            params = {}
            for part in parts[1:]:
                if "=" in part:
                    name, value = part.strip().split("=", 1)
                    params[name.strip()] = value.strip().strip('"')
            return key, params

        @staticmethod
        def valid_boundary(s):
            return True

    sys.modules["cgi"] = _Module()
