# Phone mode API v1

`main.py --mode phone` starts the unified control loop with camera, lidar and HTTP enabled. On 2026-09-30 the unified program was deployed to `/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python`, alongside the other `--mode` choices. The HTTP listener binds port 8080 on all interfaces by default. Phone and SSH manual are mutually exclusive; only one program may hold the chassis. `start_phone.sh` loads the device environment and starts this same entry point.

The phone and device must share a WLAN. The 2026-09-30 integration used `http://192.168.8.204:8080` on the same WLAN as the phone and computer; this is the App default. The older vehicle hotspot address was `192.168.149.1`. Confirm the actual address on the vehicle before use. Keep this unauthenticated API on a trusted LAN; do not forward port 8080 to other networks.

## Control

All JSON responses use `ok: true` on success. Errors return `ok: false`, `code`, and `message` with HTTP 400/404/409/503. Control commands are confirmed after the single main loop executes them. A phone operation is rejected if it waited in the queue more than 500 ms.

1. `POST /api/v1/control/session` with `{}` returns `sessionId`, `bootId`, `leaseMs` (`600`). Obtaining a session never moves the car. A second phone cannot take over active movement.
2. `POST /api/v1/control/command` with `{"sessionId":"...","seq":1,"commandId":"unique","key":"w"}`. Accepted keys: `q w e a s d z up down left right`. The first eight and `left/right` start motion. `up/down` change speed by 20 within 0–100. `z` is the existing timed turn. Response contains `accepted`, `speed`, `commandId`.
3. `POST /api/v1/control/renew` with `{"sessionId":"...","commandId":"current motion ID"}`. Repeat around every 150 ms while movement is intended. Renewal never reissues the motion command or restarts the timed turn. No renewal for 600 ms stops the car and invalidates the session.
4. `POST /api/v1/control/speed` with `{"sessionId":"...","seq":2,"commandId":"unique","speed":40}` sets absolute speed (integer 0–100). During ordinary movement it applies immediately. During `z` it stops the turn, preserving the old timing behavior. The response includes confirmed speed.
5. `POST /api/v1/control/stop` with `{"sessionId":"..."}` stops and invalidates the session. Start a new session for the next gesture. A stale session/command cannot override a stop. Stop requests have priority over ordinary queued operations.

`seq` must increase within a session. Repeating a `commandId` returns its previous response without executing twice. A fresh session after a stop, timeout or restart cannot resume an old gesture.

## Camera, lidar and status

- `GET /api/v1/status`: `bootId`, `mode: "phone"`, `speed`, `moving`, `controlBusy`, `camera`, `lidar`, `server_time`. `camera.status` is `live/waiting/stale/unavailable`. `lidar.nearest_mm` is the nearest valid point in the full scan. `front_nearest_mm`, `sector_90_mm`, `sector_180_mm`, and `sector_270_mm` are the nearest valid points within ±30° of the respective sensor bearing. All distances are millimeters and become `null` when no valid/current scan exists. A spinning radar therefore reports much more than the front sector. The App displays only left (`270°`), front (`0°`) and right (`90°`), following the observed sensor mounting; it does not display the rear (`180°`). UI values omit the unit label, but remain millimeters.
- `GET /api/v1/camera/frame.jpg`: most recent encoded preview frame, no disk write; stale frames return 503.
- `GET /api/v1/camera/stream.mjpg`: continuous MJPEG, with Content-Length and X-Frame-Sequence on each part. Phone capture requests 1280×720 @ 30 FPS; camera MJPG is published in the shared latest-frame slot. The driving preview uses reduced JPEG decoding to produce 640×360 JPEGs at quality 75, keeping wireless traffic small enough for 30 FPS. Captures decode the full 720p source. Other sensor formats have a JPEG encoding fallback. Slow receivers skip intermediate frames; TCP buffering is bounded. The App uses a single streaming request and keeps only the newest pending JPEG while decoding. UI FPS is the measured decode rate, not the requested sensor rate.
- `POST /api/v1/camera/captures` with `{}`: saves the full current frame in the car's `capture/`, returning `captureId` and `url` after the file exists.
- `GET /api/v1/camera/captures/{captureId}`: downloads that saved JPEG for the phone gallery.

Phone mode disables color auto-exposure priority when the SDK supports it, keeping automatic exposure but preventing exposure-driven frame-rate reduction; the prior value is restored on capture shutdown. Source updates measured 19.4 FPS before this change and 29.99 FPS afterward. Dark scenes may become less bright.

A sustained LAN test caught simultaneous TCP send timeouts to the phone and computer while the camera remained live. Video send timeout is now 1.5 seconds, with bounded buffering; the App pins LAN routing and keeps the preview window awake. Later tests still encountered network stalls longer than 2 seconds, so sustained wireless stability has not passed. A 60-second vehicle-loopback test passed at 29.88 FPS (1795 frames, zero skipped sequences), including status and capture/download checks. This is a transport stall, not proof of a specific router or Wi-Fi fault. The App retains its 2-second frame watchdog and the device retains its independent 600 ms movement lease. Reconnecting must not resume a previous gesture. Server logs record `MJPEG stream closed`; App diagnostics record received bytes, data age and decoder activity.

The old loopback-only preview routes remain available for local diagnostics. Camera preview, screenshots and AI all read the same CameraBroadcaster. The lidar adapter is a single reader of its serial device.

## SSH start and stop

The permanent `astra-phone.service` is installed and runs the unified directory through `start_phone.sh` (`main.py --mode phone`). It is intentionally **not** enabled at boot. Use `systemctl start astra-phone`, `systemctl status astra-phone`, and `systemctl stop astra-phone`; application logs are in the unified directory's `logs/`. The earlier transient `astra-phone-integration.service` is stopped, and its directory is retained as historical reference. Original changed files are backed up at `/home/HwHiAiUser/astra-backups/phone-20260930`; model weights and saved captures were preserved. Stop phone before starting SSH manual, standalone camera preview or lidar probe.

After this upgrade, 49 offline device tests passed, including JPEG passthrough/shared-memory/snapshot checks and movement-speed/lease/stop regression checks with simulated hardware. Live status, camera, MJPEG and capture checks are read-only with respect to vehicle motion. The HarmonyOS HAP build and parser/control-timing offline regressions passed, and the updated HAP was installed on the connected phone. No new physical movement test was performed for this change. An earlier short same-WLAN preview measurement received 300 frames at 29.91 FPS with zero skipped frame sequences, about 28 KB per preview JPEG. The phone decoder also reported approximately 29–31 FPS while showing live video and scanning lidar.

The earlier same-WLAN hardware test confirmed status, live frame, MJPEG stream, capture and download, scanning lidar, all control keys, speed, renew, stop, stale-session rejection and the 600 ms control-loss watchdog. The HarmonyOS phone connected and showed live video and lidar; its private gallery received a capture. Motion was limited to short commands with the wheels suspended. Actual wheel direction and travel behavior and app background stop still require separate observation before ground driving.

The car clock was manually corrected from 2024 to 2026-09-30 during the earlier integration, but was observed back at 2024-12-26 after the current restart. NTP was enabled but DNS resolution for its configured server failed, so automatic time sync is unverified. Check `timedatectl status` after a reboot if car-side capture timestamps matter.
