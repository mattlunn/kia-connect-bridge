import dataclasses

from fastapi.testclient import TestClient
from hyundai_kia_connect_api import ClimateRequestOptions, WindowRequestOptions
from hyundai_kia_connect_api.const import ORDER_STATUS, WINDOW_STATE
from hyundai_kia_connect_api.exceptions import (
    APIError,
    DuplicateRequestError,
    RateLimitingError,
)

from kia_connect_bridge.app import create_app

from .conftest import VEHICLE_ID


def test_lists_vehicles_with_library_names(client, manager):
    manager.vehicles[VEHICLE_ID].ev_battery_percentage = 34

    response = client.get("/vehicles")

    assert response.status_code == 200
    [vehicle] = response.json()
    assert vehicle["id"] == VEHICLE_ID
    assert vehicle["VIN"] == "VIN123"
    assert vehicle["ev_battery_percentage"] == 34
    assert "odometer" in vehicle
    assert "data" not in vehicle
    assert not any(name.startswith("_") for name in vehicle)


def test_unknown_vehicle_is_404(client):
    assert client.get("/vehicles/nope").status_code == 404
    assert client.post("/vehicles/nope/start_charge").status_code == 404


def test_command_waits_for_the_action_then_refreshes(client, manager):
    response = client.post(f"/vehicles/{VEHICLE_ID}/start_charge")

    assert response.status_code == 200
    body = response.json()
    assert body["action_id"] == "action-start_charge"
    assert body["action_status"] == "SUCCESS"
    assert body["vehicle"]["ev_battery_percentage"] == 80
    assert manager.calls == [
        ("start_charge", VEHICLE_ID),
        ("check_action_status", VEHICLE_ID, "action-start_charge", True, 30),
        ("force_refresh_vehicle_state", VEHICLE_ID),
    ]


def test_unknown_action_status_still_succeeds(client, manager):
    manager.action_status = ORDER_STATUS.UNKNOWN

    response = client.post(f"/vehicles/{VEHICLE_ID}/stop_charge")

    assert response.status_code == 200
    assert response.json()["action_status"] == "UNKNOWN"


def test_failed_action_is_502_with_refreshed_vehicle(client, manager):
    manager.action_status = ORDER_STATUS.FAILED

    response = client.post(f"/vehicles/{VEHICLE_ID}/lock")

    assert response.status_code == 502
    assert response.json()["vehicle"]["ev_battery_percentage"] == 80


def test_start_climate_passes_library_options(client, manager):
    response = client.post(
        f"/vehicles/{VEHICLE_ID}/start_climate",
        json={"set_temp": 21, "duration": 10, "climate": True},
    )

    assert response.status_code == 200
    name, vehicle_id, options = manager.calls[0]
    assert (name, vehicle_id) == ("start_climate", VEHICLE_ID)
    assert options == ClimateRequestOptions(set_temp=21, duration=10, climate=True)


def test_set_windows_state_accepts_enum_values(client, manager):
    response = client.post(
        f"/vehicles/{VEHICLE_ID}/set_windows_state",
        json={"front_left": 1, "front_right": 0, "back_left": 0, "back_right": 0},
    )

    assert response.status_code == 200
    options = manager.calls[0][2]
    assert isinstance(options, WindowRequestOptions)
    assert options.front_left == WINDOW_STATE.OPEN


def test_set_charge_limits_passes_ac_and_dc(client, manager):
    response = client.post(f"/vehicles/{VEHICLE_ID}/set_charge_limits", json={"ac": 80, "dc": 90})

    assert response.status_code == 200
    assert manager.calls[0] == ("set_charge_limits", VEHICLE_ID, 80, 90)


def test_invalid_body_is_422(client):
    response = client.post(f"/vehicles/{VEHICLE_ID}/start_climate", json={"set_temp": "hot"})

    assert response.status_code == 422


def test_check_action_status(client, manager):
    response = client.get(f"/vehicles/{VEHICLE_ID}/actions/abc?synchronous=true&timeout=5")

    assert response.json() == {"action_status": "SUCCESS"}
    assert manager.calls == [("check_action_status", VEHICLE_ID, "abc", True, 5)]


def test_library_errors_map_to_http_statuses(client, manager):
    for error, status_code in [
        (RateLimitingError("Exceeds number of requests"), 429),
        (DuplicateRequestError("Duplicate request"), 409),
        (APIError("Something else"), 502),
        (NotImplementedError("Not supported in this region"), 501),
    ]:
        manager.error = error

        response = client.post(f"/vehicles/{VEHICLE_ID}/start_charge")

        assert response.status_code == status_code
        assert response.json() == {"error": type(error).__name__, "detail": str(error)}


def test_api_token_is_required_when_set(settings, bridge):
    client = TestClient(create_app(dataclasses.replace(settings, api_token="secret"), bridge))

    assert client.get("/vehicles").status_code == 401
    assert client.get("/vehicles", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/vehicles", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert client.get("/health").status_code == 200
