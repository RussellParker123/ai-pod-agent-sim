from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_updates_price_on_selection_and_passes_product_to_pipeline(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.sim.run_simulation.run_once",
        lambda **kwargs: calls.append(kwargs),
    )
    dashboard = Path(__file__).resolve().parents[1] / "app" / "dashboard.py"
    app = AppTest.from_file(str(dashboard)).run()

    for product, price in [("mug", "$10.84"), ("tote", "$11.67"), ("tshirt", "$15.00")]:
        app.sidebar.selectbox[0].select(product).run()
        assert not app.exception
        assert app.sidebar.metric[0].value == price

    app.sidebar.button[0].click().run()
    assert not app.exception
    assert calls == [{"product_type": "tshirt"}]
