"""Endpoint tests for the billboard app, using demo:// feeds (no network)."""
import json
import os
import sys

sys.path.insert(0, os.getcwd())

import examples.billboard_app as ba  # noqa: E402
from lab_flightboard import parse_billboard_config  # noqa: E402


def _client():
    ba.app.config["BILLBOARD"] = parse_billboard_config({"instruments": []})
    ba.app.config["CONFIG_PATH"] = None
    ba.ALLOW_WRITE = True
    return ba.app.test_client()


def test_inspect_returns_suggestion_per_url():
    c = _client()
    r = c.post("/api/inspect", json={"urls": ["demo://booking", "demo://free"]})
    d = json.loads(r.data)
    assert d["ok"] is True
    assert len(d["instruments"]) == 2
    assert all(i["error"] is None for i in d["instruments"])
    # demo feeds carry X-WR-CALNAME, so a name is suggested
    assert d["instruments"][0]["equipment_name"]
    assert d["instruments"][0]["event_count"] >= 1


def test_inspect_empty_list():
    c = _client()
    r = c.post("/api/inspect", json={"urls": []})
    assert json.loads(r.data)["instruments"] == []


def test_inspect_bad_url_reports_error_not_crash():
    c = _client()
    r = c.post("/api/inspect", json={"urls": ["http://"]})
    d = json.loads(r.data)
    assert d["ok"] is True
    assert d["instruments"][0]["error"] is not None
