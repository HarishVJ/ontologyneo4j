"""
Mock Snowflake Executor Module

Responsibility: Simulate Snowflake query execution with realistic
mock data for the POC demonstration.

Component: Snowflake / Mock Executor
Owner: Snowflake (simulated)
"""


# Pre-defined mock results for known KPIs + filters
MOCK_RESULTS = {
    ("Headcount", "ATL"): {
        "mock_result": {"headcount": 489},
        "answer": "ATL headcount is 489.",
    },
    ("Headcount", "JFK"): {
        "mock_result": {"headcount": 312},
        "answer": "JFK headcount is 312.",
    },
    ("Headcount", "LAX"): {
        "mock_result": {"headcount": 275},
        "answer": "LAX headcount is 275.",
    },
    ("Headcount", None): {
        "mock_result": {"headcount": 4821},
        "answer": "Total company headcount is 4,821.",
    },
    ("Attrition Rate", "ATL"): {
        "mock_result": {
            "attrition_rate": "47.2%",
            "total_terminations": 23,
            "total_headcount": 489,
            "breakdown": {
                "salaried_terminations": 12,
                "hourly_terminations": 8,
                "job_abandonment": 3,
            },
        },
        "answer": "The attrition rate at ATL for last month is 47.2%, based on 23 total terminations and 489 total headcount.",
    },
    ("Attrition Rate", "JFK"): {
        "mock_result": {
            "attrition_rate": "38.5%",
            "total_terminations": 15,
            "total_headcount": 312,
            "breakdown": {
                "salaried_terminations": 7,
                "hourly_terminations": 5,
                "job_abandonment": 3,
            },
        },
        "answer": "The attrition rate at JFK for last month is 38.5%, based on 15 total terminations and 312 total headcount.",
    },
    ("Attrition Rate", None): {
        "mock_result": {
            "attrition_rate": "42.1%",
            "total_terminations": 198,
            "total_headcount": 4821,
            "breakdown": {
                "salaried_terminations": 89,
                "hourly_terminations": 72,
                "job_abandonment": 37,
            },
        },
        "answer": "The company-wide attrition rate for last month is 42.1%, based on 198 total terminations and 4,821 total headcount.",
    },
}


def execute_mock(kpi_name: str, station: str = None) -> dict:
    """
    Return mock execution results for a given KPI and station filter.

    Returns:
        {"mock_result": {...}, "answer": "...", "execution_mode": "mock"}
    """
    key = (kpi_name, station)
    if key in MOCK_RESULTS:
        result = MOCK_RESULTS[key].copy()
        result["execution_mode"] = "mock"
        return result

    # Fallback for unknown combinations
    return {
        "mock_result": {"note": f"No mock data for {kpi_name} at {station or 'all stations'}"},
        "answer": f"Mock data not available for this combination. In production, this would execute against Snowflake.",
        "execution_mode": "mock",
    }
