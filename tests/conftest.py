import logging
import socket

import pytest


@pytest.fixture
def offline_data_dir(tmp_path, monkeypatch):
    """Point the simulator (and dashboard) at an empty temp data dir and
    fail loudly on any network connection attempt."""
    import app.sim.run_simulation as run_simulation
    import app.sim.utils as sim_utils

    monkeypatch.setattr(sim_utils, "DATA_DIR", tmp_path)
    monkeypatch.setattr(run_simulation, "DATA_DIR", tmp_path)

    def no_network(*args, **kwargs):
        raise AssertionError("network access attempted during an offline test")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    yield tmp_path
    etsy_logger = logging.getLogger("app.connectors.etsy_connector")
    for handler in list(etsy_logger.handlers):
        if str(tmp_path) in str(getattr(handler, "baseFilename", "")):
            etsy_logger.removeHandler(handler)
            handler.close()
