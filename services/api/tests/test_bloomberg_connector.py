"""The connector is the whole "no manual steps" promise.

If a placeholder survives rendering, or the local credential store stops being
picked up, the operator is back to typing keys on a locked-down bank computer.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from services.api.app.bloomberg_connector import (
    BRIDGE_SOURCE_PATH,
    CONNECTOR_PIP_PACKAGES,
    bridge_source,
    powershell_one_liner,
    python_one_liner,
    render_powershell_connector,
    render_python_connector,
)


ENDPOINT = "https://app.example.com"
TOKEN = "bbe_test-token"
BRIDGE_ID = "salle-des-marches"


@pytest.fixture(scope="module")
def bridge_module():
    spec = importlib.util.spec_from_file_location("_bridge_under_test", BRIDGE_SOURCE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.modules.pop(spec.name, None)


@pytest.mark.parametrize(
    "render",
    [render_powershell_connector, render_python_connector],
)
def test_rendered_connector_is_fully_substituted(render) -> None:
    body = render(endpoint=ENDPOINT, token=TOKEN, bridge_id=BRIDGE_ID, app_name="Test App")

    assert re.findall(r"__[A-Z_]+__", body) == []
    assert ENDPOINT in body
    assert TOKEN in body
    assert BRIDGE_ID in body
    for package in CONNECTOR_PIP_PACKAGES:
        assert package in body


def test_python_connector_is_valid_python() -> None:
    body = render_python_connector(
        endpoint=ENDPOINT, token=TOKEN, bridge_id=BRIDGE_ID, app_name="Test App"
    )
    compile(body, "connect_bloomberg.py", "exec")


def test_one_liners_target_the_token_authenticated_routes() -> None:
    powershell = powershell_one_liner(endpoint=ENDPOINT, token=TOKEN)
    jupyter = python_one_liner(endpoint=ENDPOINT, token=TOKEN)

    assert f"{ENDPOINT}/bridge/bloomberg/connect.ps1?token={TOKEN}" in powershell
    assert f"{ENDPOINT}/bridge/bloomberg/connect.py?token={TOKEN}" in jupyter
    # One pasteable line each; a wrapped command is a support call waiting to happen.
    assert "\n" not in powershell
    assert "\n" not in jupyter


def test_bridge_source_is_shipped_with_the_api_image() -> None:
    source = bridge_source()
    assert "def cmd_listen" in source
    assert "def cmd_enroll" in source


def test_enrolled_credential_is_reused_without_env_vars(bridge_module, tmp_path, monkeypatch) -> None:
    """After enrollment the operator never supplies endpoint or key again."""
    monkeypatch.setenv("BT_BLOOMBERG_CONFIG_DIR", str(tmp_path))
    for name in ("BT_BLOOMBERG_ENDPOINT", "BT_BLOOMBERG_BRIDGE_KEY", "BT_BLOOMBERG_BRIDGE_ID"):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr(
        bridge_module,
        "_enroll",
        lambda endpoint, token, bridge_id: {
            "bridge_id": BRIDGE_ID,
            "bridge_key": "bbk_issued",
            "endpoint_hint": ENDPOINT,
        },
    )

    args = bridge_module.build_parser().parse_args(
        ["enroll", "--endpoint", ENDPOINT, "--enroll-token", TOKEN]
    )
    assert bridge_module.cmd_enroll(args) == 0

    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert stored["bridge_id"] == BRIDGE_ID
    assert stored["bridge_key"] == "bbk_issued"

    listen_args = bridge_module.build_parser().parse_args(["listen"])
    endpoint, bridge_key, bridge_id = bridge_module._common_config(listen_args)
    assert (endpoint, bridge_key, bridge_id) == (ENDPOINT, "bbk_issued", BRIDGE_ID)


def test_missing_credential_explains_how_to_enroll(bridge_module, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BT_BLOOMBERG_CONFIG_DIR", str(tmp_path / "empty"))
    for name in ("BT_BLOOMBERG_ENDPOINT", "BT_BLOOMBERG_BRIDGE_KEY", "BT_BLOOMBERG_ENROLL_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    args = bridge_module.build_parser().parse_args(["listen"])
    with pytest.raises(SystemExit) as excinfo:
        bridge_module._common_config(args)
    assert "enroll" in str(excinfo.value)


def test_connector_packages_match_the_bridge_requirements() -> None:
    requirements = (Path(BRIDGE_SOURCE_PATH).parent / "requirements.txt").read_text(encoding="utf-8")
    declared = {
        re.split(r"[<>=;\s]", line.strip())[0]
        for line in requirements.splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert set(CONNECTOR_PIP_PACKAGES) == declared
