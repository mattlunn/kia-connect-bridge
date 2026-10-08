import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

from hyundai_kia_connect_api import Token, VehicleManager
from hyundai_kia_connect_api.const import ORDER_STATUS
from hyundai_kia_connect_api.exceptions import AuthenticationError

from .settings import Settings

logger = logging.getLogger(__name__)


class Bridge:
    def __init__(self, manager: VehicleManager, token_path: Path):
        self.manager = manager
        self._token_path = token_path
        self._saved_token: str | None = None
        # The library isn't thread-safe, and Kia rejects overlapping commands anyway.
        self._lock = threading.Lock()

    def call[T](self, fn: Callable[[VehicleManager], T]) -> T:
        with self._lock:
            try:
                self._ensure_logged_in()
                return fn(self.manager)
            finally:
                self._save_token()

    def run_command(
        self, vehicle_id: str, send: Callable[[VehicleManager], str], timeout_seconds: int
    ) -> tuple[str, ORDER_STATUS]:
        def run(manager: VehicleManager) -> tuple[str, ORDER_STATUS]:
            action_id = send(manager)
            status = manager.check_action_status(
                vehicle_id, action_id, synchronous=True, timeout=timeout_seconds
            )
            manager.force_refresh_vehicle_state(vehicle_id)
            return action_id, status

        return self.call(run)

    def refresh_periodically(self, interval_minutes: float, stop: threading.Event) -> None:
        while True:
            try:
                self.call(lambda manager: manager.update_all_vehicles_with_cached_state())
            except Exception:
                logger.exception("Refreshing cached vehicle state failed")

            if interval_minutes <= 0 or stop.wait(interval_minutes * 60):
                return

    def _ensure_logged_in(self) -> None:
        try:
            self.manager.check_and_refresh_token()
        except AuthenticationError:
            if self.manager.token is None:
                raise

            logger.warning("Saved token was rejected; logging in with the account password")
            self.manager.token = None
            self.manager.check_and_refresh_token()

    def _save_token(self) -> None:
        if self.manager.token is None:
            return

        data = json.dumps(self.manager.token.to_dict())

        if data == self._saved_token:
            return

        fd = os.open(self._token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)

        with os.fdopen(fd, "w") as file:
            file.write(data)

        self._saved_token = data


def load_token(token_path: Path, username: str) -> Token | None:
    if not token_path.exists():
        return None

    token = Token.from_dict(json.loads(token_path.read_text()))

    return token if token.username == username else None


def create_bridge(settings: Settings) -> Bridge:
    token_path = settings.data_dir / "token.json"
    manager = VehicleManager(
        region=settings.region,
        brand=settings.brand,
        username=settings.username,
        password=settings.password,
        pin=settings.pin,
        language=settings.language,
        token=load_token(token_path, settings.username),
    )

    return Bridge(manager, token_path)
