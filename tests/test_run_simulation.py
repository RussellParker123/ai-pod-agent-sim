import unittest
from unittest.mock import patch

from app.sim import run_simulation


class RevenueGoalTests(unittest.TestCase):
    class SalesConnector:
        def __init__(self):
            self.sales = 0

        def get_total_sales_usd(self):
            return self.sales

    def test_revenue_goal_stops_when_live_sales_reach_target(self):
        connector = self.SalesConnector()
        runs = []

        def run_once(**kwargs):
            runs.append(kwargs)
            connector.sales = 100
            return "latest-run.json"

        with patch.object(
            run_simulation.EtsyConnector,
            "from_environment",
            return_value=connector,
        ), patch.object(
            run_simulation,
            "run_once",
            side_effect=run_once,
        ), patch.object(run_simulation.time, "sleep"):
            latest_run = run_simulation.run_until_revenue_goal(100, 60)

        self.assertEqual(latest_run, "latest-run.json")
        self.assertEqual(
            runs,
            [{"etsy_mode": False, "real": True, "require_real": True}],
        )

    def test_revenue_goal_does_not_list_if_already_met(self):
        connector = self.SalesConnector()
        connector.sales = 100

        with patch.object(
            run_simulation.EtsyConnector,
            "from_environment",
            return_value=connector,
        ), patch.object(
            run_simulation,
            "run_once",
            side_effect=AssertionError("unexpected listing"),
        ):
            self.assertEqual(run_simulation.run_until_revenue_goal(100, 60), "")
