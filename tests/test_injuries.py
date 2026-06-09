from datetime import date
import unittest

import pandas as pd

from src.injuries import (
    add_injury_columns,
    eligible_return_date,
    fetch_injury_report,
    injured_list_days,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class InjuryTests(unittest.TestCase):
    def test_injured_list_status_and_return_date(self):
        self.assertEqual(injured_list_days("D10"), 10)
        self.assertIsNone(injured_list_days("A"))
        self.assertEqual(
            eligible_return_date("D10", "2026-06-02"),
            date(2026, 6, 12),
        )

    def test_fetch_injury_report_builds_hover_detail(self):
        def fake_get(url, params, headers, timeout):
            if url.endswith("/roster"):
                return FakeResponse(
                    {
                        "roster": [
                            {
                                "person": {"id": 592450},
                                "status": {
                                    "code": "D10",
                                    "description": "Injured 10-Day",
                                },
                            },
                            {
                                "person": {"id": 1},
                                "status": {
                                    "code": "A",
                                    "description": "Active",
                                },
                            },
                        ]
                    }
                )
            return FakeResponse(
                {
                    "transactions": [
                        {
                            "person": {"id": 592450},
                            "effectiveDate": "2026-06-02",
                            "description": (
                                "New York Yankees placed RF Aaron Judge on the "
                                "10-day injured list retroactive to June 2, 2026. "
                                "Right rib stress fracture."
                            ),
                        }
                    ]
                }
            )

        report = fetch_injury_report(
            [147],
            date(2026, 6, 9),
            request_get=fake_get,
        )

        self.assertIn(592450, report)
        self.assertIn("Right rib stress fracture", report[592450]["injury_tooltip"])
        self.assertIn("Est. eligible return", report[592450]["injury_tooltip"])
        self.assertIn("06/12/26", report[592450]["injury_tooltip"])

    def test_add_injury_columns_matches_player_id(self):
        data = pd.DataFrame([{"batter_id": 592450, "batter": "Aaron Judge"}])
        report = {
            592450: {
                "injury_status": "Injured 10-Day",
                "injury_tooltip": "Injured 10-Day.",
                "injury_return_date": "2026-06-12",
            }
        }
        result = add_injury_columns(data, "batter_id", report)
        self.assertEqual(result.iloc[0]["injury_status"], "Injured 10-Day")


if __name__ == "__main__":
    unittest.main()
