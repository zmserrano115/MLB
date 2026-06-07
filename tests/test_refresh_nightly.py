import unittest

from refresh_nightly import refresh_dates, season_to_date_lookback_days


class NightlyRefreshTests(unittest.TestCase):
    def test_season_to_date_starts_on_march_first(self):
        lookback_days = season_to_date_lookback_days("2026-06-06")
        dates = list(refresh_dates("2026-06-06", lookback_days))

        self.assertEqual(98, lookback_days)
        self.assertEqual("2026-03-01", dates[0])
        self.assertEqual("2026-06-06", dates[-1])


if __name__ == "__main__":
    unittest.main()
