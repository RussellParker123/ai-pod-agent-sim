from unittest.mock import patch

from app.sim import run_simulation


class SalesConnector:
    def __init__(self):
        self.sales = 0

    def get_total_sales_usd(self):
        return self.sales


def test_revenue_goal_stops_when_live_sales_reach_target(monkeypatch):
    connector = SalesConnector()
    runs = []

    monkeypatch.setattr(
        run_simulation.EtsyConnector,
        "from_environment",
        lambda: connector,
    )

    def run_once(**kwargs):
        runs.append(kwargs)
        connector.sales = 100
        return "latest-run.json"

    monkeypatch.setattr(run_simulation, "run_once", run_once)
    with patch.object(run_simulation.time, "sleep"):
        latest_run = run_simulation.run_until_revenue_goal(100, 60)

    assert latest_run == "latest-run.json"
    assert runs == [{"etsy_mode": False, "real": True}]


def test_revenue_goal_does_not_list_if_already_met(monkeypatch):
    connector = SalesConnector()
    connector.sales = 100
    monkeypatch.setattr(
        run_simulation.EtsyConnector,
        "from_environment",
        lambda: connector,
    )
    monkeypatch.setattr(
        run_simulation,
        "run_once",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected listing")),
    )

    assert run_simulation.run_until_revenue_goal(100, 60) == ""
