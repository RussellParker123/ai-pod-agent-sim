from unittest.mock import patch

from app.marketplace.adapter import EtsyAdapter
from app.marketplace.etsy_client import EtsyClient, EtsyError
from app.sim.agents import Design


def design():
    return Design("D001", "pet lovers", 0.8, product_type="mug", price=19.99, approved=True)


def test_simulated_default():
    r = EtsyAdapter().list_design(design())
    assert r["mode"] == "simulated" and r["listing_id"] == "SIM-D001"


def test_real_without_credentials_fails_closed(monkeypatch):
    for k in ("ETSY_API_KEY", "ETSY_SHOP_ID", "ETSY_ACCESS_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    try:
        EtsyAdapter(client=EtsyClient(api_key="", shop_id="", access_token="")).list_design(design(), real=True)
        assert False, "Expected live publishing without credentials to fail"
    except EtsyError as exc:
        assert "Etsy listing failed" in str(exc)


class Resp:
    def __init__(self, code, body=None):
        self.status_code, self._b, self.headers, self.content = code, body or {}, {}, b"x"
        self.ok = code < 400
        self.text = ""

    def json(self):
        return self._b


def test_real_api_failure_is_not_reported_as_simulated():
    client = EtsyClient("k", "s", "1", "t", max_retries=0, backoff_base=0)
    with patch("requests.request", return_value=Resp(500)):
        try:
            EtsyAdapter(client=client).list_design(design(), real=True)
            assert False, "Expected Etsy API failure to propagate"
        except EtsyError as exc:
            assert "Etsy listing failed" in str(exc)


def test_backoff_then_success():
    c = EtsyClient("k", "s", "1", "t", backoff_base=0)
    with patch("requests.request", side_effect=[Resp(429), Resp(200, {"listing_id": 5, "state": "draft"})]) as m:
        r = EtsyAdapter(client=c, draft_only=True).list_design(design(), real=True)
    assert m.call_count == 2 and r["mode"] == "real" and r["listing_id"] == 5


def test_retries_exhausted():
    c = EtsyClient("k", "s", "1", "t", max_retries=1, backoff_base=0)
    with patch("requests.request", return_value=Resp(429)):
        try:
            c.get_orders()
            assert False
        except EtsyError:
            pass
