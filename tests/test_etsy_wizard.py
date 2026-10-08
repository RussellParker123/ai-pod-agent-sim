import json

from app.setup import etsy_wizard


def test_wizard_keeps_configuration_cli(tmp_path):
    output = tmp_path / "etsy_config.json"
    etsy_wizard.main([
        "--niches", "coffee culture", "--product-types", "tote",
        "--margin", "0.5", "--output", str(output),
    ])
    config = json.loads(output.read_text())
    assert config["niches"] == ["coffee culture"]
    assert config["product_types"] == ["tote"]
    assert config["target_margin"] == 0.5
    assert config["fees"]["listing_fee"] == 0.2


def test_wizard_dispatches_guided_setup(monkeypatch):
    monkeypatch.setattr(etsy_wizard, "interactive_main", lambda: 130)
    assert etsy_wizard.main(["--interactive"]) == 130


def test_wizard_dispatches_live_oauth(monkeypatch):
    calls = []
    monkeypatch.setattr(etsy_wizard, "start_etsy_connect", lambda: calls.append("start"))
    monkeypatch.setattr(etsy_wizard, "complete_etsy_connect", calls.append)
    etsy_wizard.main(["--connect-etsy"])
    etsy_wizard.main(["--complete-etsy-auth", "--redirect-url", "http://localhost/callback"])
    assert calls == ["start", "http://localhost/callback"]
