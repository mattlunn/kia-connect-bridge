from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hyundai_kia_connect_api import Token, Vehicle
from hyundai_kia_connect_api.const import ORDER_STATUS

from kia_connect_bridge.app import create_app
from kia_connect_bridge.bridge import Bridge
from kia_connect_bridge.settings import Settings

VEHICLE_ID = "vehicle-1"


class FakeManager:
    def __init__(self) -> None:
        self.vehicles: dict[str, Vehicle] = {}
        self.token: Token | None = None
        self.calls: list[tuple] = []
        self.action_status = ORDER_STATUS.SUCCESS
        self.error: Exception | None = None
        self.login_error: Exception | None = None

    def check_and_refresh_token(self) -> bool:
        if self.login_error is not None:
            error, self.login_error = self.login_error, None
            raise error

        if self.token is None:
            self.calls.append(("login",))
            self.token = Token(username="user@example.com", refresh_token="refresh-1")

        if not self.vehicles:
            self.vehicles[VEHICLE_ID] = Vehicle(id=VEHICLE_ID, name="EV6", VIN="VIN123")

        return True

    def get_vehicle(self, vehicle_id: str) -> Vehicle:
        return self.vehicles[vehicle_id]

    def update_all_vehicles_with_cached_state(self) -> None:
        self.calls.append(("update_all_vehicles_with_cached_state",))

    def force_refresh_vehicle_state(self, vehicle_id: str) -> None:
        self.calls.append(("force_refresh_vehicle_state", vehicle_id))
        self.vehicles[vehicle_id].ev_battery_percentage = 80

    def check_action_status(self, vehicle_id, action_id, synchronous=False, timeout=120):
        self.calls.append(("check_action_status", vehicle_id, action_id, synchronous, timeout))
        return self.action_status

    def __getattr__(self, name: str):
        def command(*args):
            if self.error is not None:
                raise self.error

            self.calls.append((name, *args))
            return f"action-{name}"

        return command


@pytest.fixture
def manager() -> FakeManager:
    manager = FakeManager()
    manager.check_and_refresh_token()
    manager.calls.clear()
    return manager


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        username="user@example.com",
        password="password",
        pin="1234",
        region=1,
        brand=1,
        language="en",
        api_token=None,
        refresh_interval_minutes=10,
        action_timeout_seconds=30,
        data_dir=tmp_path,
    )


@pytest.fixture
def bridge(manager: FakeManager, settings: Settings) -> Bridge:
    return Bridge(manager, settings.data_dir / "token.json")


@pytest.fixture
def client(settings: Settings, bridge: Bridge) -> TestClient:
    return TestClient(create_app(settings, bridge))
