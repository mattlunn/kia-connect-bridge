import logging
import secrets
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

import requests
from fastapi import APIRouter, Body, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from hyundai_kia_connect_api import (
    ClimateRequestOptions,
    POIInfo,
    ScheduleChargingClimateRequestOptions,
    VehicleManager,
    WindowRequestOptions,
)
from hyundai_kia_connect_api.const import ORDER_STATUS
from hyundai_kia_connect_api.exceptions import (
    DuplicateRequestError,
    HyundaiKiaException,
    RateLimitingError,
)
from starlette.exceptions import HTTPException

from .bridge import Bridge, create_bridge
from .serialize import error_to_json, to_json, vehicle_to_json
from .settings import Settings

COMMANDS_WITHOUT_ARGUMENTS = [
    "start_charge",
    "stop_charge",
    "stop_climate",
    "lock",
    "unlock",
    "open_charge_port",
    "close_charge_port",
    "start_hazard_lights",
    "start_hazard_lights_and_horn",
    "start_valet_mode",
    "stop_valet_mode",
]


class Unauthorized(Exception):
    headers = {"WWW-Authenticate": "Bearer"}


class UnknownVehicle(Exception):
    pass


# The first matching class wins, so subclasses come before their parents. Anything
# else is a 500.
STATUS_CODES: dict[type[Exception], int] = {
    Unauthorized: 401,
    UnknownVehicle: 404,
    DuplicateRequestError: 409,
    RequestValidationError: 422,
    RateLimitingError: 429,
    NotImplementedError: 501,
    HyundaiKiaException: 502,
    requests.RequestException: 502,
}


def status_code_for(error: Exception) -> int:
    # FastAPI's own, e.g. a 404 for an unknown path or a 405 for the wrong method.
    if isinstance(error, HTTPException):
        return error.status_code

    return next((code for cls, code in STATUS_CODES.items() if isinstance(error, cls)), 500)


def create_app(settings: Settings, bridge: Bridge) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop = threading.Event()
        refresher = threading.Thread(
            target=bridge.refresh_periodically,
            args=(settings.refresh_interval_minutes, stop),
            daemon=True,
        )
        refresher.start()
        yield
        stop.set()

    app = FastAPI(title="Kia Connect Bridge", lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    def respond(
        data: Any = None,
        error: Exception | None = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> JSONResponse:
        refresh = bridge.refresh_status

        return JSONResponse(
            {
                "data": data,
                "error": None if error is None else error_to_json(error),
                "last_success_at": to_json(refresh.last_success_at),
                "last_error_at": to_json(refresh.last_error_at),
                "last_error": None
                if refresh.last_error is None
                else error_to_json(refresh.last_error),
            },
            status_code=status_code,
            headers=headers,
        )

    def authorise(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        if settings.api_token is None:
            return

        if credentials is None or not secrets.compare_digest(
            credentials.credentials, settings.api_token
        ):
            raise Unauthorized("Missing or invalid API token")

    def known_vehicle_id(vehicle_id: str) -> str:
        if vehicle_id not in bridge.manager.vehicles:
            raise UnknownVehicle(f"Unknown vehicle {vehicle_id}")

        return vehicle_id

    VehicleId = Annotated[str, Depends(known_vehicle_id)]
    api = APIRouter(dependencies=[Depends(authorise)])

    def vehicle_json(vehicle_id: str) -> dict[str, Any]:
        return vehicle_to_json(bridge.manager.get_vehicle(vehicle_id))

    def respond_with_vehicle(vehicle_id: str) -> JSONResponse:
        return respond(vehicle_json(vehicle_id))

    def run_command(vehicle_id: str, send: Callable[[VehicleManager], str]) -> JSONResponse:
        action_id, status = bridge.run_command(vehicle_id, send, settings.action_timeout_seconds)

        return respond(
            {
                "action_id": action_id,
                "action_status": status.value,
                "vehicle": vehicle_json(vehicle_id),
            },
            status_code=502 if status == ORDER_STATUS.FAILED else 200,
        )

    @api.get("/vehicles")
    def list_vehicles() -> JSONResponse:
        return respond([vehicle_to_json(vehicle) for vehicle in bridge.manager.vehicles.values()])

    @api.get("/vehicles/{vehicle_id}")
    def get_vehicle(vehicle_id: VehicleId) -> JSONResponse:
        return respond_with_vehicle(vehicle_id)

    @api.post("/vehicles/{vehicle_id}/update_vehicle_with_cached_state")
    def update_vehicle_with_cached_state(vehicle_id: VehicleId) -> JSONResponse:
        bridge.call(lambda manager: manager.update_vehicle_with_cached_state(vehicle_id))
        return respond_with_vehicle(vehicle_id)

    @api.post("/vehicles/{vehicle_id}/force_refresh_vehicle_state")
    def force_refresh_vehicle_state(vehicle_id: VehicleId) -> JSONResponse:
        bridge.call(lambda manager: manager.force_refresh_vehicle_state(vehicle_id))
        return respond_with_vehicle(vehicle_id)

    @api.post("/vehicles/{vehicle_id}/update_day_trip_info")
    def update_day_trip_info(
        vehicle_id: VehicleId, yyyymmdd_string: Annotated[str, Body(embed=True)]
    ) -> JSONResponse:
        bridge.call(lambda manager: manager.update_day_trip_info(vehicle_id, yyyymmdd_string))
        return respond_with_vehicle(vehicle_id)

    @api.post("/vehicles/{vehicle_id}/update_month_trip_info")
    def update_month_trip_info(
        vehicle_id: VehicleId, yyyymm_string: Annotated[str, Body(embed=True)]
    ) -> JSONResponse:
        bridge.call(lambda manager: manager.update_month_trip_info(vehicle_id, yyyymm_string))
        return respond_with_vehicle(vehicle_id)

    @api.get("/vehicles/{vehicle_id}/actions/{action_id}")
    def check_action_status(
        vehicle_id: VehicleId, action_id: str, synchronous: bool = False, timeout: int = 120
    ) -> JSONResponse:
        status = bridge.call(
            lambda manager: manager.check_action_status(vehicle_id, action_id, synchronous, timeout)
        )
        return respond({"action_status": status.value})

    def add_command_without_arguments(name: str) -> None:
        def handler(vehicle_id: VehicleId) -> JSONResponse:
            return run_command(vehicle_id, lambda manager: getattr(manager, name)(vehicle_id))

        api.add_api_route(f"/vehicles/{{vehicle_id}}/{name}", handler, methods=["POST"], name=name)

    for name in COMMANDS_WITHOUT_ARGUMENTS:
        add_command_without_arguments(name)

    @api.post("/vehicles/{vehicle_id}/start_climate")
    def start_climate(vehicle_id: VehicleId, options: ClimateRequestOptions) -> JSONResponse:
        return run_command(vehicle_id, lambda manager: manager.start_climate(vehicle_id, options))

    @api.post("/vehicles/{vehicle_id}/set_charge_limits")
    def set_charge_limits(
        vehicle_id: VehicleId, ac: Annotated[int, Body()], dc: Annotated[int, Body()]
    ) -> JSONResponse:
        return run_command(
            vehicle_id, lambda manager: manager.set_charge_limits(vehicle_id, ac, dc)
        )

    @api.post("/vehicles/{vehicle_id}/set_charging_current")
    def set_charging_current(
        vehicle_id: VehicleId, level: Annotated[int, Body(embed=True)]
    ) -> JSONResponse:
        return run_command(
            vehicle_id, lambda manager: manager.set_charging_current(vehicle_id, level)
        )

    @api.post("/vehicles/{vehicle_id}/set_windows_state")
    def set_windows_state(vehicle_id: VehicleId, options: WindowRequestOptions) -> JSONResponse:
        return run_command(
            vehicle_id, lambda manager: manager.set_windows_state(vehicle_id, options)
        )

    @api.post("/vehicles/{vehicle_id}/set_vehicle_to_load_discharge_limit")
    def set_vehicle_to_load_discharge_limit(
        vehicle_id: VehicleId, limit: Annotated[int, Body(embed=True)]
    ) -> JSONResponse:
        return run_command(
            vehicle_id,
            lambda manager: manager.set_vehicle_to_load_discharge_limit(vehicle_id, limit),
        )

    @api.post("/vehicles/{vehicle_id}/schedule_charging_and_climate")
    def schedule_charging_and_climate(
        vehicle_id: VehicleId, options: ScheduleChargingClimateRequestOptions
    ) -> JSONResponse:
        return run_command(
            vehicle_id,
            lambda manager: manager.schedule_charging_and_climate(vehicle_id, options),
        )

    @api.post("/vehicles/{vehicle_id}/set_navigation")
    def set_navigation(vehicle_id: VehicleId, poi_list: list[POIInfo]) -> JSONResponse:
        return run_command(vehicle_id, lambda manager: manager.set_navigation(vehicle_id, poi_list))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api)

    def error_response(_: Request, error: Exception) -> JSONResponse:
        return respond(
            error=error,
            status_code=status_code_for(error),
            headers=getattr(error, "headers", None),
        )

    # Starlette runs the Exception handler as a server error, re-raising so it's logged with
    # a traceback. Expected errors are registered by class so they aren't.
    for cls in [*STATUS_CODES, HTTPException, Exception]:
        app.add_exception_handler(cls, error_response)

    return app


def main() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()

    return create_app(settings, create_bridge(settings))
