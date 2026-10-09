import json
import threading

from hyundai_kia_connect_api import Token
from hyundai_kia_connect_api.exceptions import AuthenticationError

from kia_connect_bridge.bridge import load_token


def test_saves_the_token_readable_only_by_owner(bridge, manager, settings):
    bridge.call(lambda _: None)

    token_path = settings.data_dir / "token.json"
    assert json.loads(token_path.read_text())["refresh_token"] == "refresh-1"
    assert token_path.stat().st_mode & 0o777 == 0o600


def test_resaves_the_token_when_it_rotates(bridge, manager, settings):
    bridge.call(lambda _: None)
    manager.token.refresh_token = "refresh-2"
    bridge.call(lambda _: None)

    assert (
        json.loads((settings.data_dir / "token.json").read_text())["refresh_token"] == "refresh-2"
    )


def test_ignores_a_saved_token_for_another_account(tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps(Token(username="someone@else.com").to_dict()))

    assert load_token(token_path, "user@example.com") is None
    assert load_token(token_path, "someone@else.com").username == "someone@else.com"


def test_logs_in_again_when_the_saved_token_is_rejected(bridge, manager):
    manager.login_error = AuthenticationError("Token expired")

    bridge.call(lambda _: None)

    assert manager.calls == [("login",)]


def test_refreshes_once_when_interval_is_zero(bridge, manager):
    bridge.refresh_periodically(0, threading.Event())

    assert manager.calls == [("update_all_vehicles_with_cached_state",)]


def test_periodic_refresh_survives_errors(bridge, manager):
    manager.login_error = AuthenticationError("Kia is down")
    manager.token = None

    bridge.refresh_periodically(0, threading.Event())
