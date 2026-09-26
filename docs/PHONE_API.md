# Phone mode API v1

`main.py --phone` starts the existing manual control loop with camera, lidar and HTTP enabled. The HTTP listener binds port 8080 on all interfaces by default. Phone and SSH manual are mutually exclusive; only one `main.py` instance may hold the chassis. `start_phone.sh` contains the device's Python/CANN/Orbbec environment.

The phone and device must share the car WLAN. The currently documented hotspot address is `192.168.149.1`, so the default App URL is `http://192.168.149.1:8080`. Confirm the actual address on the vehicle before use. No internet connection is needed. Keep this unauthenticated API on the private vehicle WLAN; do not forward port 8080 to other networks.

## Control

All JSON responses use `ok: true` on success. Errors return `ok: false`, `code`, and `message` with HTTP 400/404/409/503. Control commands are confirmed after the single main loop executes them. A phone operation is rejected if it waited in the queue more than 500 ms.

1. `POST /api/v1/control/session` with `{}` returns `sessionId`, `bootId`, `leaseMs` (`600`). Obtaining a session never moves the car. A second phone cannot take over active movement.
2. `POST /api/v1/control/command` with `{"sessionId":"...","seq":1,"commandId":"unique","key":"w"}`. Accepted keys: `q w e a s d z up down left right`. The first eight and `left/right` start motion. `up/down` change speed by 20 within 0–100. `z` is the existing timed turn. Response contains `accepted`, `speed`, `commandId`.
3. `POST /api/v1/control/renew` with `{"sessionId":"...","commandId":"current motion ID"}`. Repeat around every 150 ms while movement is intended. Renewal never reissues the motion command or restarts the timed turn. No renewal for 600 ms stops the car and invalidates the session.
4. `POST /api/v1/control/speed` with `{"sessionId":"...","seq":2,"commandId":"unique","speed":40}` sets absolute speed (integer 0–100). During ordinary movement it applies immediately. During `z` it stops the turn, preserving the old timing behavior. The response includes confirmed speed.
5. `POST /api/v1/control/stop` with `{"sessionId":"..."}` stops and invalidates the session. Start a new session for the next gesture. A stale session/command cannot override a stop. Stop requests have priority over ordinary queued operations.

`seq` must increase within a session. Repeating a `commandId` returns its previous response without executing twice. A fresh session after a stop, timeout or restart cannot resume an old gesture.

## Camera, lidar and status

- `GET /api/v1/status`: `bootId`, `mode: "phone"`, `speed`, `moving`, `controlBusy`, `camera`, `lidar`, `server_time`. `camera.status` is `live/waiting/stale/unavailable`. `lidar` is the existing scan JSON; `nearest_mm` and `front_nearest_mm` are millimeters and `null` if no valid/current scan.
- `GET /api/v1/camera/frame.jpg`: most recent encoded preview frame, no disk write; stale frames return 503.
- `GET /api/v1/camera/stream.mjpg`: continuous MJPEG backed by the same camera and encoder.
- `POST /api/v1/camera/captures` with `{}`: saves the full current frame in the car's `capture/`, returning `captureId` and `url` after the file exists.
- `GET /api/v1/camera/captures/{captureId}`: downloads that saved JPEG for the phone gallery.

The old loopback-only preview routes remain available for local diagnostics. Camera preview, screenshots and AI all read the same CameraBroadcaster. The lidar adapter is a single reader of its serial device.

## SSH start and stop

After deploying `python/` to the documented car path, copy `deploy/astra-phone.service` to `/etc/systemd/system/astra-phone.service`, run `systemctl daemon-reload`, then use `systemctl start astra-phone`. The service is intentionally **not** enabled at boot. Once started, the SSH terminal may exit. Use `systemctl status astra-phone`, `journalctl -u astra-phone -f`, and `systemctl stop astra-phone` for maintenance. Stop phone before starting SSH manual. Do not run the standalone camera preview or lidar probe while phone is running.

Hardware movement, WLAN reachability, camera and lidar must be verified on the physical car. Offline tests and an App build cannot establish those facts.
