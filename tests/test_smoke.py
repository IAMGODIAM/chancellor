"""Smoke tests: every module imports, the client guards itself, the CLI runs."""

import pytest

import chancellor
from chancellor import api_client
from chancellor.cli import main as cli_main


def test_package_version():
    assert chancellor.__version__


def test_all_modules_import():
    from chancellor import escalation, grader, instruments, orchestrator, task_graph  # noqa: F401
    from chancellor.evals import suite_a, suite_b  # noqa: F401


def test_unconfigured_client_refuses_live_call():
    client = api_client.MetaModelClient(base_url="", api_key="")
    assert not client.configured
    with pytest.raises(api_client.NotConfiguredError):
        client.chat(api_client.MUSE_WONDER, [api_client.ChatMessage("user", "hi")])


def test_placeholder_key_is_not_configured():
    client = api_client.MetaModelClient(
        base_url="https://example.invalid", api_key=api_client.PLACEHOLDER_KEY
    )
    assert not client.configured


def test_fake_transport_roundtrip():
    client = api_client.offline_client()
    resp = client.chat(api_client.MUSE_SPARK, [api_client.ChatMessage("user", "ping")])
    assert "fake" in resp.text
    assert resp.usage["cost_usd"] == 0.0


def test_cli_demo_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # The demo is the exhibit now; the smoke test runs it at CI pace
    # with the gate auto-approved. The staged default (full pace, a
    # human at the gate) is the presenter's path, not CI's.
    assert cli_main(["demo", "--fast", "--auto"]) == 0


def test_cli_eval_suites_run(capsys):
    assert cli_main(["eval-a"]) == 0
    assert cli_main(["eval-b"]) == 0
    out = capsys.readouterr().out
    assert "normative" in out and "reliability" in out
