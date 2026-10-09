# Kia Connect Bridge

A small HTTP API around [hyundai_kia_connect_api](https://github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api), the Python library behind the [Kia UVO / Hyundai Bluelink Home Assistant integration](https://github.com/Hyundai-Kia-Connect/kia_uvo). Run it as a container and talk to your Kia, Hyundai or Genesis over HTTP from any language: read battery level, location, climate and lock state, and start/stop charging, climate, locks and more.

It's deliberately a thin wrapper. Field names, units and command options are the library's own, so the library's docs and source are the reference for what each field means. The bridge adds:

- **Login handling.** It logs in once, keeps the (rotating) token in `/data`, and only falls back to a password login when Kia rejects the saved token.
- **Background refresh.** Kia's cached vehicle state is fetched every `REFRESH_INTERVAL_MINUTES`, so `GET` requests are served from memory and never hit Kia.
- **Commands that report what actually happened.** Each command waits for Kia to process it, then asks the car for fresh state, and returns that state.

Not affiliated with Kia, Hyundai or Genesis. The underlying API is unofficial and can change or break at any time.

## Running

```yaml
services:
  kia-connect-bridge:
    image: mattlunn/kia-connect-bridge:latest
    restart: unless-stopped
    environment:
      ACCOUNT_USERNAME: you@example.com
      ACCOUNT_PASSWORD: your-password
      ACCOUNT_PIN: "1234"
      REGION: 1
      BRAND: 1
      API_TOKEN: a-long-random-string
    volumes:
      - kia-connect-bridge:/data
    ports:
      - 8000:8000

volumes:
  kia-connect-bridge:
```

The container runs as uid 1000; if you bind-mount `/data` instead of using a named volume, make sure that user can write to it.

Interactive API docs are served at `/docs`.

### Configuration

| Variable | Required | Default | |
|---|---|---|---|
| `ACCOUNT_USERNAME` | ✔ | | The email you log in to the Kia / Hyundai / Genesis app with. |
| `ACCOUNT_PASSWORD` | ✔ | | |
| `ACCOUNT_PIN` | | | The app's 4-digit PIN. Needed for commands in most regions. |
| `REGION` | ✔ | | `1` Europe, `2` Canada, `3` USA, `4` China, `5` Australia, `6` India, `7` New Zealand, `8` Brazil, `9` Europe (CCI/GSPA) |
| `BRAND` | ✔ | | `1` Kia, `2` Hyundai, `3` Genesis |
| `LANGUAGE` | | `en` | |
| `API_TOKEN` | | | When set, every endpoint except `/health` requires `Authorization: Bearer <API_TOKEN>`. Leave unset only on a network you trust: the API exposes your car's location and can unlock it. |
| `REFRESH_INTERVAL_MINUTES` | | `10` | How often to fetch Kia's cached state. `0` fetches once at startup only. |
| `ACTION_TIMEOUT_SECONDS` | | `60` | How long a command waits for Kia to report its outcome before refreshing anyway. |
| `DATA_DIR` | | `/data` | Where the login token is kept. |

Regions other than Kia Europe haven't been tested with the bridge. They use the same library calls, so they should work wherever the library supports them.

### Rate limits

Kia and Hyundai limit how many requests an account can make per day, and don't publish the limit. Reads of cached state (`GET`, the background refresh, `update_vehicle_with_cached_state`) are cheap. `force_refresh_vehicle_state` and every command wake the car, which costs 12V battery as well as quota, so use them sparingly. When the limit is hit, the bridge returns `429`.

## API

`vehicle_id` is the library's `Vehicle.id`, listed by `GET /vehicles`.

### Reading state

| Endpoint | Library call | |
|---|---|---|
| `GET /vehicles` | `VehicleManager.vehicles` | Every vehicle on the account. |
| `GET /vehicles/{vehicle_id}` | `get_vehicle` | Served from memory. |
| `POST /vehicles/{vehicle_id}/update_vehicle_with_cached_state` | same | Fetch Kia's cached state now. Doesn't wake the car. |
| `POST /vehicles/{vehicle_id}/force_refresh_vehicle_state` | same | Wake the car for fresh state. |
| `POST /vehicles/{vehicle_id}/update_day_trip_info` `{"yyyymmdd_string": "20261008"}` | same | Populates `day_trip_info`. |
| `POST /vehicles/{vehicle_id}/update_month_trip_info` `{"yyyymm_string": "202610"}` | same | Populates `month_trip_info`. |
| `GET /vehicles/{vehicle_id}/actions/{action_id}?synchronous=false&timeout=120` | `check_action_status` | |

Each returns the vehicle as JSON: every public field and property of the library's [`Vehicle`](https://github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api/blob/master/hyundai_kia_connect_api/Vehicle.py), e.g. `ev_battery_percentage`, `ev_battery_is_charging`, `odometer` + `odometer_unit`, `air_control_is_on`, `is_locked`. Datetimes are ISO 8601 and enums are their values. Two library quirks to be aware of: `location` is `[longitude, latitude]` (use `location_latitude` / `location_longitude` to avoid the ambiguity), and some flags documented as booleans are integers (`air_control_is_on` can be e.g. `10` while running).

### Commands

`POST /vehicles/{vehicle_id}/<command>`, where `<command>` is the `VehicleManager` method:

| Command | Body |
|---|---|
| `start_charge`, `stop_charge` | |
| `set_charge_limits` | `{"ac": 80, "dc": 80}` |
| `set_charging_current` | `{"level": 1}` |
| `start_climate` | [`ClimateRequestOptions`](https://github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api/blob/master/hyundai_kia_connect_api/ApiImpl.py), e.g. `{"set_temp": 21, "duration": 10, "climate": true, "defrost": false}` |
| `stop_climate` | |
| `lock`, `unlock` | |
| `open_charge_port`, `close_charge_port` | |
| `set_windows_state` | `WindowRequestOptions`, e.g. `{"front_left": 1, "front_right": 0, "back_left": 0, "back_right": 0}` (`0` closed, `1` open, `2` ventilation) |
| `start_hazard_lights`, `start_hazard_lights_and_horn` | |
| `start_valet_mode`, `stop_valet_mode` | |
| `set_vehicle_to_load_discharge_limit` | `{"limit": 20}` |
| `schedule_charging_and_climate` | `ScheduleChargingClimateRequestOptions`, times as `"HH:MM"` |
| `set_navigation` | a list of `POIInfo` |

Which commands a car accepts depends on the region and model. Commands the library doesn't implement for your region return `501`; ones Kia or the car reject return `502`.

A command takes as long as Kia and the car take to respond: typically 30–90 seconds. Set your HTTP client's timeout to at least two minutes. The response is:

```json
{
  "action_id": "6fd5a2d0-c35e-11f1-a33d-fcc3184deae2",
  "action_status": "UNKNOWN",
  "vehicle": { "ev_battery_is_charging": true, "...": "..." }
}
```

**Trust `vehicle`, not `action_status`.** `action_status` is Kia's own report of the command (`SUCCESS`, `FAILED`, `TIMEOUT` or `UNKNOWN`), but at least in Europe it's usually `UNKNOWN` even when the command worked: Kia keys its command history to a push-notification device registration, which it invalidates when the bridge (not being a phone) doesn't receive the push. `vehicle` is the car's state fetched after the command, so it shows what actually happened. A definite `FAILED` returns `502`, still with the refreshed `vehicle`.

### Errors

| Status | When |
|---|---|
| `401` | `API_TOKEN` is set and the request doesn't carry it. |
| `404` | Unknown `vehicle_id`. |
| `409` | Kia rejected the command as a duplicate of one still in progress. |
| `422` | The request body doesn't match the library's options. |
| `429` | Kia's rate limit. |
| `501` | The library doesn't implement that command for your region. |
| `502` | Kia or the library reported an error, or the command `FAILED`. |

Errors from Kia or the library have the body `{"error": "<exception class>", "detail": "<message>"}`.

## Development

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
ACCOUNT_USERNAME=... ACCOUNT_PASSWORD=... ACCOUNT_PIN=... REGION=1 BRAND=1 DATA_DIR=./data \
  uv run uvicorn kia_connect_bridge.app:main --factory --reload
```

The library version is pinned in `pyproject.toml`; Dependabot proposes upgrades as the library ships fixes for Kia's and Hyundai's API changes.
