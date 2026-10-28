# AstraPlusCar

English | [简体中文](README_zh.md)


AstraPlusCar is a smart vehicle controlled by an **Orange Pi AI Pro (Ascend platform)**. A unified Python program drives its mecanum chassis, Astra+ camera, and Slamtec lidar, using Ascend offline models for sign recognition, lane following, and target tracking. A HarmonyOS mobile app controls the vehicle over LAN HTTP, displays live video, and saves captures in a private gallery.

| Item | Details |
| --- | --- |
| Device entry point | `python3 main.py --mode manual` (also supports `cmd` / `easy` / `phone` / `voice`) |
| Mobile connection URL | `http://<小车地址>:8080` (`http://192.168.8.204:8080` during physical-vehicle integration on 2026-09-30) |
| Vehicle deployment directory | `/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python` |
| Hardware platform | Orange Pi AI Pro / Ascend CANN / Python 3.9 / Linux |

This document consistently uses `python3 main.py --mode 模式` for main-program commands, with the mode name substituted. **Repository code may differ from the deployed vehicle code; check the directory and `--help` before starting.**

## 1. Project contents

### 1.1 Two-repository structure

The product consists of two independent Git repositories, managed and validated separately:

| Repository | Responsibility |
| --- | --- |
| `AstraPlusCar-device` (this repository) | Device Python runtime, chassis control, camera and lidar acquisition, AI inference, HTTP API, deployment/service configuration, and offline training/annotation tools. |
| [AstraPlusCar-HarmonyOS](../AstraPlusCar-HarmonyOS/README.md) | ArkTS mobile app: displays video and three-direction lidar, sends driving and speed commands, and saves captures to its private gallery. |

The workspace root is not initialized as a Git repository, and the two histories remain separate. Preserve models, captured data, and existing vehicle-side changes during deployment updates.

### 1.2 System architecture

Responsibilities: **the phone provides the interface and high-level commands; the device handles hardware and motion control**. They communicate through one LAN HTTP channel, without cloud dependencies.

```text
┌──────────────────────────────────────────────┐
│              HarmonyOS 手机 App              │
│     视频预览 / 三向雷达 / 控制盘 / 图库      │
└───────────────────┬──────────────────────────┘
                    │ 局域网 HTTP :8080
┌───────────────────┴──────────────────────────┐
│          设备端 main.py 统一主程序           │
│  ┌────────────────────────────────────────┐  │
│  │ 主循环：输入 → 运动仲裁 → 底盘         │  │
│  │ （唯一底盘写者）                       │  │
│  ├────────────────────────────────────────┤  │
│  │ 相机进程：CameraBroadcaster            │  │
│  │ 场景进程：AI 推理 → 动作队列           │  │
│  │ 服务线程：预览 / 手机 / 语音 / 雷达    │  │
│  └────────────────────────────────────────┘  │
└──────┬──────────────┬──────────────┬─────────┘
  Astra+ 相机   Slamtec 雷达  麦轮底盘（I²C）
 彩色流 / 截图  扫描测距 / 扇区  四轮速度与转向
```

### 1.3 Device runtime architecture

The main program combines one process with subprocesses/threads. Key conventions prevent hardware contention:

| Component | File | Responsibility |
| --- | --- | --- |
| Main loop and arguments | `python/main.py` | Parses modes and arguments; uses `/tmp/astrapluscar-main.lock` to ensure **only one main program owns the hardware at a time**; starts the camera, services, and scenes, then processes input in a loop. |
| Motion arbitration | `python/motion_control.py` | `MotionArbiter` is the only chassis writer. It combines keyboard, phone, voice, and AI scene actions into one command stream, managing speed, timed actions (U-turns), priorities, and stopping. |
| Camera broadcast | `python/src/utils/camera_broadcaster.py` | A camera subprocess writes color frames to shared memory. Preview, captures, and AI share the latest frame, avoiding repeated camera opens. |
| Scene processes | `python/src/scenes/` | Each AI scene runs independently, submitting actions to the queue without opening the chassis or camera directly. |
| Hardware services | `python/phone_mode.py`, `camera_preview.py`, `voice_control.py`, `lidar_probe.py` | Phone HTTP, web preview, speech recognition, and lidar acquisition attach to the main loop as threads/subprocesses. |
| Chassis driver | `python/src/utils/controller.py` + `chassis_control_node.py` | The current `Controller` uses an I²C mecanum chassis. An ESP32 serial implementation is also retained; verify wiring and low-level drivers against the actual vehicle. |

On `Ctrl+C`, `SIGTERM`, `SIGHUP`, or input disconnection, the main program **stops the vehicle before shutting down background tasks**. Camera, voice, or lidar service failures stop the vehicle and exit. The running camera, captures, and AI share one broadcaster; the lidar adapter is the serial port's only reader.

### 1.4 Hardware

| Component | Description and known configuration |
| --- | --- |
| Controller | Orange Pi AI Pro, Linux + Python 3.9 (3.9.2 observed); Ascend CANN / ACL performs `.om` model inference. |
| Camera | Astra+ USB camera (Orbbec, USB ID `2bc5:0536/0636`), Orbbec SDK v1 Python binding. Only color is captured; depth-based driving is unavailable. |
| Chassis | Mecanum chassis and encoder motor driver board, I²C bus 7, address `0x34`; wheel directions and driving speeds require on-site calibration. |
| Lidar | Slamtec lidar through a CP2102 serial adapter, read using the SDK's `ultra_simple` executable; standalone scans do not require ROS2. |
| Voice | Microphone accessible through ALSA `arecord` + Vosk Chinese model (optional, not yet accepted on this vehicle). |

## 2. Vehicle features

### 2.1 Feature overview

| Feature | Entry point | Operation | Dependencies |
| --- | --- | --- | --- |
| Keyboard driving | `--mode manual` | Single-key SSH input | Chassis |
| Live web preview | `--camera` (manual / cmd / easy) | Browser + SSH tunnel | Camera |
| Sign assistance: Helper | `--mode easy`, or enter `Helper` in `cmd` | AI turns left/right, performs a U-turn, or stops | `weights/yolo.om` (provided) |
| Lane following: LF | Enter `LF` in `cmd` | Automatic AI lane following | `weights/lfnet.om` (provide separately) |
| Target tracking: Tracking | Enter `Tracking` in `cmd` | Automatic AI target tracking | `weights/tracking.om` (provide separately) |
| Mobile remote control | `--mode phone` | HarmonyOS app | Phone on the same WLAN |
| Voice driving | `--mode voice` or `--voice` | Short Chinese phrases | Vosk + microphone + Chinese model |
| Captures | Keyboard `p`, spoken “拍照” (take photo), web, or phone | Save the latest full frame | Camera |
| Lidar distance monitoring | `--lidar` / `--radar`; automatic in `phone` | Read-only web or API display | Slamtec lidar |
| Standalone hardware checks | `camera_probe.py`, `camera_preview.py`, `lidar_probe.py` | Command line | Corresponding hardware |

See section 4 for complete keys, arguments, and limitations; see section 3 for startup steps.

### 2.2 Keyboard driving (manual)

Enter single keys in the SSH terminal without pressing Enter. Initial speed control value is 40 (range 0–100):

| Key | Action |
| --- | --- |
| `w` / `s` | Forward / backward |
| `a` / `d` | Turn left / right |
| `q` / `e` | Rotate counterclockwise / clockwise in place |
| `←` / `→` | Strafe left / right |
| `↑` / `↓` | Increase / decrease speed by 20, bounded to 0–100 |
| `z` | Timed U-turn at fixed rotation speed 80, currently about 3.31 seconds (calibrated from a measured 280–290° rotation; recheck on site) |
| Space | Stop without exiting |
| `Esc` | Stop and exit |
| `p` | Save a capture in the background without changing current motion |

**Releasing a keyboard key does not stop the vehicle; press Space.** Space or another motion key interrupts a timed U-turn. Changing speed during a U-turn stops it first.

### 2.3 Scene commands and AI inference (cmd / easy)

In `cmd` mode, enter a scene name and press Enter; names are case-sensitive:

| Input | Effect | Model |
| --- | --- | --- |
| `Helper` | Recognize signs and turn left/right, perform a U-turn, or stop | `weights/yolo.om` |
| `LF` | Run the lane-following scene | `weights/lfnet.om` |
| `Tracking` | Run the target-tracking scene | `weights/tracking.om` |
| `clear` | Stop the vehicle and current scene, retaining command mode | None |
| `stop` | Stop and exit the main program | None |
| `p` | Save a capture | None |
| `Manual` | Reports that switching is unsupported; exit and restart with `--mode manual` | None |

`easy` automatically enters `Helper` after startup; it does not start `LF`. Keyboard motion keys or Space can take over and end AI control at any time. To resume AI, exit and restart `easy`, or enter the scene name again in `cmd`. Starting a new scene first stops the vehicle and ends the old scene.

Model status: `yolo.om` is provided, with loading and photo inference validated on the vehicle. `lfnet.om` and `tracking.om` must still be provided and accepted separately. They serve different purposes; renaming `yolo.om` cannot replace them. `Helper` does not currently load the auxiliary classification model `cls.om`.

### 2.4 Mobile remote control (phone)

`--mode phone` automatically starts the camera and lidar and listens on `0.0.0.0:8080`. With the phone and vehicle on the same WLAN, connect the app to `http://<小车地址>:8080` to view video, three-direction lidar, and the capture gallery.

Key design points:

- **Camera**: Captures at 1280×720 @ 30 FPS and publishes raw MJPEG into a shared latest-frame slot. Driving preview uses half-size decoding to produce 640×360 JPEG at quality 75, reducing wireless bandwidth; captures still decode full 720p.
- **Control safety**: Motion commands carry a session (`sessionId`), increasing sequence (`seq`), and unique command ID. While an action is held, the app renews about every 150 ms. **After more than 600 ms without renewal, the vehicle stops and invalidates the session.** An old session cannot resume motion after stopping, and duplicate commands do not execute twice.
- **Watchdog**: If the app receives no new video frame for over 2 seconds, it stops control and disconnects. In the foreground, it reconnects automatically with backoff and never replays old actions.

See [docs/PHONE_API.md](docs/PHONE_API.md) for the full API contract and section 4.9 for arguments and troubleshooting.

### 2.5 Camera preview and captures

Preview and driving share one camera broadcaster. Adding `--camera` in a driving mode opens a web preview on the vehicle's `127.0.0.1:8765`. After establishing an SSH tunnel, a computer browser can view MJPEG, inspect status, or save the current image. Main-program preview defaults to 10 fps, adjustable per client through `?fps=1..30`; AI and captures continue reading full acquisition frames.

Four capture entry points share the latest full frame: keyboard `p`, spoken “拍照” (take photo), web `/snapshot.jpg`, and mobile `POST /api/v1/camera/captures`. Files default to `capture/`, named with nanosecond timestamps and random strings.

### 2.6 Lidar distance monitoring

Lidar updates its scan summary once per second, reporting the closest distance over the full scan and within four directional ±30° sectors:

| Field | Direction |
| --- | --- |
| `front_nearest_mm` | 0° (front) |
| `sector_90_mm` | 90° (right) |
| `sector_180_mm` | 180° (rear) |
| `sector_270_mm` | 270° (left) |

All distances are in millimeters. Data is marked `stale` after 2.5 seconds without updates, and distances are `null` without valid, fresh data. **Lidar only monitors distance; automatic obstacle avoidance is unavailable.** The mobile interface shows left/front/right.

### 2.7 Voice control (optional)

Vosk's offline Chinese model recognizes short phrases and maps them to keys: forward/backward/turn left/turn right/rotate left/rotate right/strafe left/strafe right/speed up/slow down/U-turn/take photo/stop/exit. Voice motion stops automatically after 1 second by default; adjust with `--voice-move-seconds` (greater than 0, at most 5 seconds). Keyboard motion cancels a previous voice action.

Earlier checks found no system-recognized microphone/sound card or usable Chinese model. **Voice driving still requires dependencies and acceptance testing.** Without hardware, `python3 voice_control.py 前进` checks text mapping only.

## 3. Getting started

### 3.1 Step 1: Connect to the vehicle over SSH

```bash
ssh root@192.168.8.204
```

The phone, computer, and vehicle must share a network. The vehicle's `192.168.8.204` address is actually on `eth0`; `wlan0` retains `192.168.149.1`. After changing networks, use the vehicle's actual address.

### 3.2 Step 2: Initialize the environment

Repeat this for every new SSH session; these variables do not persist automatically:

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
source /home/HwHiAiUser/pyorbbecsdk/env.sh
export PYTHONPATH="/home/HwHiAiUser/pyorbbecsdk/install/lib${PYTHONPATH:+:$PYTHONPATH}"
export PATH="/usr/local/miniconda3/bin:$PATH"
cd /home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python
CAMERA_PY=/home/HwHiAiUser/pyorbbecsdk/venv/bin/python
```

`CAMERA_PY` is the dedicated camera interpreter, used by standalone camera tools. The main program uses `python3` or `/usr/local/miniconda3/bin/python`.

### 3.3 Step 3: Choose and start a feature

Choose one startup command below. **Before driving, lift the wheels safely off the ground or confirm a safe area.** Exit other programs using the same hardware first; if the phone service is running, stop it with `systemctl stop astra-phone`.

| Feature | Startup command | Operation / conditions |
| --- | --- | --- |
| Keyboard driving | `python3 main.py --mode manual` | Single-key input; Space stops; `Esc` exits |
| Scene scheduling | `python3 main.py --mode cmd` | Enter a scene name or management command, then press Enter |
| Sign assistance | `python3 main.py --mode easy` | Automatically starts `Helper`; requires `weights/yolo.om` |
| Lane following | `python3 main.py --mode cmd` | Enter `LF`; requires `weights/lfnet.om` |
| Target tracking | `python3 main.py --mode cmd` | Enter `Tracking`; requires `weights/tracking.om` |
| Mobile control | `python3 main.py --mode phone` | Connect the app to `http://192.168.8.204:8080`; runs in foreground; `Ctrl+C` exits |
| Voice driving | `python3 main.py --mode voice --voice-model /path/to/vosk-model` | Manual mode plus background voice; requires a microphone, Vosk, and Chinese model |
| Web video while driving | `python3 main.py --mode manual --camera` | Open browser preview through an SSH tunnel |
| Lidar while driving | `python3 main.py --mode manual --camera --lidar` | Preview also shows lidar status; no automatic avoidance |
| Standalone capture / frame check | `$CAMERA_PY camera_probe.py --seconds 10 --output capture/astra_check.jpg` | Check color frames and save a photo without opening the chassis |
| Standalone web preview | `$CAMERA_PY camera_preview.py` | Access through an SSH tunnel without opening the chassis |
| Standalone lidar check | `python3 lidar_probe.py --seconds 12` | Outputs summary JSON after finishing, without opening the chassis |
| Continuous lidar check | `python3 lidar_probe.py --follow` | Outputs JSON once per second; `Ctrl+C` stops |
| Voice text-mapping check | `python3 voice_control.py 前进` | Outputs `w` only, without recording or driving |

Running `python3 main.py` without arguments is equivalent to `--mode manual`. The unified main program was deployed to the vehicle directory above on 2026-09-30; all modes share this entry point.

### 3.4 Step 4: Verify operation

Check these in sequence after startup to catch most problems early:

| Check | Method | Expected result |
| --- | --- | --- |
| Program ready | Read startup logs | `Ready: mode=...` appears without `Startup checks failed` |
| Video working | Add `--camera`, establish `ssh -N -L 8765:127.0.0.1:8765 root@192.168.8.204`, and visit `http://127.0.0.1:8765/` | Live updates; `camera.status` in `/status.json` is `live` |
| Standalone camera verification | `$CAMERA_PY camera_probe.py --seconds 10 --output capture/astra_check.jpg` | Reports frame count, resolution, and brightness, and saves a non-black color photo |
| Capture saved | Press `p`, then run `ls -lt capture/*.jpg` (newest first) | `Screenshot saved: ...` appears and the file exists |
| Lidar working | `python3 lidar_probe.py --seconds 12` | JSON `points` exceeds 0, with numeric directional distances |
| Mobile connectivity | `curl -fsS http://192.168.8.204:8080/api/v1/status` | Returns `ok`, camera status, and lidar distances |

Download files from the vehicle to the computer:

```bash
scp root@192.168.8.204:/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python/capture/astra_check.jpg .
```

Capture timestamps depend on the vehicle clock. Its calendar clock was previously incorrect (observed reverting to 2024-12-26); automatic NTP synchronization is unverified. Check `timedatectl status` after reboot.

### 3.5 Step 5: Exit and troubleshoot

Normal exit: press `Esc` in driving mode, enter `stop` in `cmd`, or press `Ctrl+C` in foreground `phone` mode. The program stops the vehicle before releasing hardware. Stop the background service with `systemctl stop astra-phone`.

| Symptom | Action |
| --- | --- |
| `invalid choice: 'phone'` | Check `pwd` and `python3 main.py --help`; enter the official directory and run the newer unified main program |
| `Another AstraPlusCar main program owns the hardware` | Exit the current hardware owner or stop its service first |
| Missing `pyorbbecsdk` / `acl` | Reload the environment and check Python version and SDK binding paths; successful imports alone do not prove all hardware is ready |
| Missing `.om` model | Check the startup directory and `weights/`; provide the model required by the scene |
| `Voice` / `Lidar` startup check fails | Follow the error to inspect models, microphone, SDK, serial paths, and permissions |
| No fresh camera frames / HTTP 503 | Exit other camera programs and use the camera probe to check USB and frame acquisition |
| Mobile video stutters or disconnects | Follow section 4.9; vehicle `logs/` records send failures as `MJPEG stream closed` |

## 4. Modes and arguments

This section follows the actual code in `python/main.py` and the standalone tools. Startup arguments follow the command; keys, scene names, and HTTP fields are inputs used after startup.

### 4.1 Main modes and common arguments

```bash
python3 main.py --mode manual
python3 main.py --mode manual --camera --lidar
python3 main.py --help
```

| Argument | Default | Usage |
| --- | --- | --- |
| `--mode` | `manual` | Select `manual`, `cmd`, `easy`, `phone`, or `voice` |
| `--manual` / `--cmd` / `--easy` / `--phone` | None | Compatibility aliases for the corresponding mode; cannot combine with another main-mode argument. Examples here use `--mode` consistently |
| `--camera` | Web preview off | Enables local preview outside `phone`; the camera still captures for screenshots and AI when this is off |
| `--camera-port` | `8765` | Non-`phone` preview port, integer 1–65535 |
| `--phone-port` | `8080` | `phone` HTTP port, integer 1–65535 |
| `--capture-dir` | `capture` | Main-program capture directory; relative paths resolve from the startup directory |
| `--voice` | Off | Adds background voice; this is a feature switch, while `--mode voice` maps to `manual + --voice` |
| `--voice-model` | Automatic discovery | Vosk model directory; see section 4.8 |
| `--voice-device` | ALSA default device | Microphone device, such as `plughw:1,0`; check `arecord -l` |
| `--voice-move-seconds` | `1.0` | Automatic stop time for voice motion; greater than 0 and at most 5 seconds |
| `--lidar` / `--radar` | Off | Equivalent switches enabling lidar; automatic in `phone` |
| `--lidar-sdk` | `/home/HwHiAiUser/rplidar_sdk/output/Linux/Release/ultra_simple` | Lidar SDK executable path |
| `--lidar-port` | `/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0` | Lidar serial port path |
| `--lidar-baudrate` | `115200` | Lidar baud rate, positive integer |
| `-h` / `--help` | None | Show arguments supported by the current file, then exit without starting hardware |

The main program has no `--speed`, `--model`, or `--mode LF` argument. Adjust speed using keyboard or phone commands after startup; each scene determines its own AI model path.

### 4.2 manual: Keyboard driving and speed

See section 2.2 for keys and behavior. Additional notes:

- After issuing keyboard motion, **releasing the key does not stop the vehicle**; press Space.
- Motion commands remain valid for 1 second; stop and exit commands clear queued actions.
- Speed keys immediately update the current action while moving, or set the next action's speed while stationary. Changing speed during a timed U-turn stops it first.

### 4.3 cmd: Scene commands and AI models

See section 2.3 for scene names, management commands, and model dependencies. Note that `w/a/s/d` in `cmd` are not keyboard driving commands; unknown commands only print errors.

### 4.4 easy: Automatic sign assistance

```bash
python3 main.py --mode easy
```

`easy` automatically starts `Helper`, not `LF`. It acts on sign detections and is not lane following. Keyboard motion keys or Space take over and end AI control; to resume `Helper`, exit and restart `easy`, or use `cmd` to start the scene explicitly. `Esc` stops and exits; if the `Helper` scene exits abnormally, the main program stops the vehicle and reports an error.

### 4.5 Camera preview, captures, and save paths

Driving and web preview share one camera broadcaster:

```bash
python3 main.py --mode manual --camera --camera-port 8765 --capture-dir capture
```

Open another terminal on the computer, establish the tunnel, and leave it running:

```bash
ssh -N -L 8765:127.0.0.1:8765 root@192.168.8.204
```

Visit `http://127.0.0.1:8765/` in the browser. Non-`phone` preview listens only on the vehicle's `127.0.0.1`; if changing `--camera-port`, update the tunnel's right-hand port as well. The page provides MJPEG, a capture-saving entry point, and `/status.json` with server and frame timestamps. `/stream.mjpg?fps=1..30` limits each client's frame rate; out-of-range values return 400.

Keyboard `p`, spoken “拍照” (take photo), web captures, and mobile captures share the latest full frame. The main program saves to `capture/` by default; change it with:

```bash
python3 main.py --mode manual --capture-dir /home/HwHiAiUser/astra-captures
```

Only `Screenshot saved` or a successful HTTP capture response confirms that the file was written. Stale frames, full queues, and write failures report explicit errors. Capture writes run in the background without blocking driving.

### 4.6 Standalone camera tools

Standalone tools do not initialize the chassis and use the dedicated camera Python environment. Exit other camera programs first.

```bash
$CAMERA_PY camera_probe.py --seconds 10 --output capture/astra_check.jpg
$CAMERA_PY camera_preview.py --port 8765 --width 640 --height 480 --fps 15 --quality 70
```

| Tool | Argument | Default and purpose |
| --- | --- | --- |
| `camera_probe.py` | `--seconds` | 10, positive integer; frame-check duration. Use 600 to check continuous acquisition for 10 minutes |
| `camera_probe.py` | `--output` | `capture/astra_probe_时间戳.jpg`; saves and validates the last fresh color frame |
| `camera_preview.py` | `--port` | 8765, range 1–65535; also accessed through an SSH tunnel |
| `camera_preview.py` | `--width` / `--height` | 1280 / 720, positive integers; requested color stream size, subject to supported camera profiles |
| `camera_preview.py` | `--fps` | 15, positive integer; requested acquisition and preview encoding frame rate |
| `camera_preview.py` | `--quality` | 70, range 1–100; JPEG quality |

The capture probe reports frame count, resolution, brightness, and save results, failing if no color frame arrives within 5 seconds. Preview provides `/snapshot.jpg` to obtain and save a capture and `/status.json` for status. Standalone preview has no lidar acquisition; stop it with `Ctrl+C` before starting another camera program.

### 4.7 Lidar acquisition and arguments

Add lidar to the driving main program:

```bash
python3 main.py --mode manual --camera --lidar \
  --lidar-port /dev/ttyUSB0 --lidar-baudrate 115200
```

Adjust example serial paths to the actual device, preferably using stable `/dev/serial/by-id/` paths. `--lidar-sdk` can select another compatible `ultra_simple` executable. Scan summaries update once per second and are available in the preview page and `/status.json`.

Use the standalone tool to check lidar only:

```bash
python3 lidar_probe.py --seconds 12
python3 lidar_probe.py --follow
python3 lidar_probe.py --port /dev/ttyUSB0 --baudrate 115200 --seconds 12
```

| Standalone argument | Default and purpose |
| --- | --- |
| `--sdk` | Same default path as the main program's `--lidar-sdk` |
| `--port` | Same default serial port as the main program's `--lidar-port` |
| `--baudrate` | 115200, positive integer |
| `--seconds` | 8, positive number; single acquisition duration, followed by one summary JSON output |
| `--follow` / `--continuous` | Continuous mode, one JSON line per second; `--seconds` does not limit total duration here; `Ctrl+C` stops |

See section 2.6 for JSON field meanings. Continuous main-program acquisition uses a rolling one-second window. Do not run the standalone probe on the same serial port while main-program lidar is active. The continuous probe tells the SDK to stop the lidar motor on exit.

### 4.8 Voice control and model configuration

First check the ALSA microphone and install optional dependencies:

```bash
arecord -l
python3 -m pip install -r requirements-voice.txt
python3 main.py --mode voice --voice-model /path/to/vosk-model \
  --voice-device plughw:1,0 --voice-move-seconds 1.5
```

Replace example paths and device names with actual values. The model must be an extracted directory containing at least `am/final.mdl` and `conf/mfcc.conf`. Discovery order is explicit `--voice-model`, environment variable `VOSK_MODEL_PATH`, then `weights/vosk-model/` beside the main entry point when the environment variable is unset.

You can also add `--voice` to `cmd` or `easy`:

```bash
export VOSK_MODEL_PATH=/home/HwHiAiUser/models/vosk-chinese
python3 main.py --mode manual --voice
```

Voice motion takes over AI control, requiring explicit scene restart afterward; keyboard motion cancels earlier voice actions. See section 2.7 for phrase mappings. Without hardware, test text mapping only:

```bash
python3 voice_control.py 前进
python3 voice_control.py 左平移
```

This accepts one text string and outputs a key, without listening to the microphone or controlling the vehicle.

### 4.9 phone: Mobile control and HTTP arguments

Stop the background phone service before starting foreground phone mode:

```bash
systemctl stop astra-phone
python3 main.py --mode phone --phone-port 8080 --capture-dir capture
```

`phone` automatically enables camera and lidar, configures the camera at 1280×720 @ 30 FPS, and publishes JPEG only. HTTP listens on `0.0.0.0:8080`, without requiring `--camera`. `--camera-port` does not change the phone service port; after changing `--phone-port`, update the app address too. `Ctrl+C` stops and exits foreground mode. Mobile driving does not use single-key SSH input.

On supported cameras, phone mode disables exposure priority, retaining automatic exposure while prioritizing frame rate. The original value is restored on exit to avoid affecting other modes. Images may be darker in low light. Measured source frame rate improved from about 19.4 FPS to 29.99 FPS.

| API | Parameters / purpose |
| --- | --- |
| `GET /api/v1/status` | Read mode, speed, motion state, camera, lidar, and server time |
| `GET /api/v1/camera/frame.jpg` | Get the current JPEG without saving |
| `GET /api/v1/camera/stream.mjpg` | Get continuous MJPEG; supports per-client `?fps=1..30` limits |
| `POST /api/v1/camera/captures` | Body `{}`; saves a capture and returns `captureId` and download `url` |
| `GET /api/v1/camera/captures/{captureId}` | Download a saved JPEG |
| `POST /api/v1/control/session` | Body `{}`; obtains `sessionId`, `bootId`, and `leaseMs=600` without moving |
| `POST /api/v1/control/command` | `sessionId`, increasing integer `seq`, unique `commandId`, and `key`; supports `q/w/e/a/s/d/z/up/down/left/right` |
| `POST /api/v1/control/speed` | Also carries session, sequence, and command ID; `speed` is an integer 0–100 |
| `POST /api/v1/control/renew` | `sessionId` and current motion `commandId`; renew about every 150 ms while moving |
| `POST /api/v1/control/stop` | `sessionId`; stops and invalidates the session; create a new session for the next motion |

Initial speed is 40, with `up/down` adjusting by 20. Old sessions cannot resume motion after a stop; over 600 ms without renewal stops the vehicle automatically. `seq` increases within each session, and duplicate requests with the same `commandId` do not execute twice. Renewals neither resend motion commands nor restart U-turn timing.

Read status and save a capture from the computer or vehicle:

```bash
curl -fsS http://192.168.8.204:8080/api/v1/status
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{}' http://192.168.8.204:8080/api/v1/camera/captures
```

The second command creates a capture on the vehicle. Successful responses contain `ok: true`; errors contain `ok: false`, `code`, and `message`. Common status codes are 400 (invalid arguments), 404 (not found), 409 (invalid session or sequence), and 503 (temporarily unavailable). See [docs/PHONE_API.md](docs/PHONE_API.md) for complete requests and responses. **The API currently has no authentication; use it on a trusted LAN and do not forward port 8080 to other networks.**

#### Troubleshoot video stuttering and disconnections

The previous 180 ms single-image polling limited display frame rate. It has been replaced by continuous MJPEG and 640×360 driving preview to reduce bandwidth. Video send timeout increased from 1 second to 1.5 seconds, retaining a bounded send buffer and latest-frame strategy.

Read-only diagnostics on 2026-10-02 ([docs/STREAM_DIAGNOSIS_2026-10-02.md](docs/STREAM_DIAGNOSIS_2026-10-02.md)) compared two paths:

| Test path | Duration | Frames / FPS | Video disconnections | Maximum frame interval | Status failures / maximum time |
| --- | --- | --- | --- | --- | --- |
| Computer → LAN → vehicle | 180 s | 4674 / 25.96 | 6, over 7 connections | 4531 ms | 0 / 2042 ms |
| Vehicle 127.0.0.1 loopback | 180 s | 5379 / 29.88 | 0, one connection | 110 ms | 0 / 50 ms |

Evidence points to LAN transport stalls rather than the camera ceasing frame production. The specific cause (router, wireless congestion, or endpoint) is unresolved, so **wireless disconnections cannot be claimed fully eliminated**. The app implements foreground reconnection with backoff, retaining its 2-second video watchdog and the device's independent 600 ms motion lease. Disconnection clears keys, sessions, and renewals; reconnecting never replays old actions. Retest command:

```bash
python3 python/test/diagnose_phone_stream.py --base-url http://192.168.8.204:8080 --seconds 180
```

This script issues only GET requests, reading video and status once per second without saving captures by default. For loopback testing, run it on the vehicle with `http://127.0.0.1:8080`. A configured 30 FPS does not prove an actual 30 FPS; inspect both UI FPS and camera acquisition.

#### Manage the official phone service

The official directory is `/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python`. `astra-phone.service` is installed; `python/start_phone.sh` loads the Ascend and Orbbec environments before running `/usr/local/miniconda3/bin/python main.py --mode phone`. **The service is not enabled at boot**; start it manually after reboot.

```bash
systemctl start astra-phone
systemctl status astra-phone
systemctl stop astra-phone
```

The program writes runtime logs to `logs/` in the official directory; use `journalctl -u astra-phone -f` for service logs. Replaced deployment files are backed up in `/home/HwHiAiUser/astra-backups/phone-20260930`; model weights and existing captures were not overwritten. Run `systemctl stop astra-phone` before switching modes.

### 4.10 Exit and runtime protection

The program stops the vehicle before releasing resources on `Ctrl+C`, `SIGTERM`, `SIGHUP`, SSH input disconnection, or abnormal exit of an active camera/voice/lidar service. A single capture save failure reports an error and usually does not end driving.

| Mode | How to stop |
| --- | --- |
| `manual` / `easy` | Press Space explicitly; `Esc` stops and exits |
| `cmd` | Enter `clear` to stop the scene, or `stop` to stop and exit |
| `voice` | Say “停车” (stop) or press Space; voice actions also stop automatically after their configured duration |
| `phone` | Releasing a control stops; disconnection, backgrounding, or video watchdog also stop; the device's 600 ms lease provides independent protection |

Keyboard modes require an explicit stop; phone mode relies on action release and lease renewal. Each path still requires separate acceptance testing on the actual device.

## 5. Dependencies

### 5.1 Device and system environment

| Dependency | Purpose and known configuration |
| --- | --- |
| Orange Pi AI Pro, Linux, Python 3.9 | Current vehicle platform; Python 3.9.2 observed. The main program uses POSIX terminals, processes, and file locks |
| Ascend CANN / ACL | `.om` inference; environment script `/usr/local/Ascend/ascend-toolkit/set_env.sh` |
| Orbbec SDK v1 Python binding | Astra+ color stream; vehicle binding at `/home/HwHiAiUser/pyorbbecsdk/install/lib`, dedicated camera Python in `pyorbbecsdk/venv/` |
| Astra+ USB camera | Required in every main-program mode; color acquisition only, without depth-based driving |
| Mecanum chassis / motor driver board | Current code uses I²C bus 7, address `0x34`; confirm actual hardware and wheel direction on site |
| Slamtec lidar and SDK, `stdbuf` | Required for `--lidar` and `phone`; the adapter reads SDK output through `stdbuf`; standalone scanning does not require ROS2 |
| ALSA `arecord`, microphone | Optional voice dependencies; mono 16 kHz recording |
| HarmonyOS phone, DevEco Studio / SDK | Mobile app and build environment; see [HarmonyOS README](../AstraPlusCar-HarmonyOS/README.md) |

### 5.2 Python packages and models

`python/requirements.txt` lists `pyserial`, `filelock`, `numpy`, `opencv-python`, and `torch`; it does not cover every system SDK or runtime dependency.

| Feature | Main additional dependencies |
| --- | --- |
| Camera and captures | `pyorbbecsdk`, OpenCV, NumPy; binding must match Python and the board SDK |
| Current chassis control | `smbus2`; controller modules also reference serial and file-lock packages |
| AI scenes | `acl`, `ais_bench`, `torch`, `torchvision`, and corresponding `.om` models |
| YAML tools | `PyYAML` |
| Background voice | `vosk` from `requirements-voice.txt`, a Chinese model, and a usable recording device |

Example Python package installation in a separately prepared development environment; inspect existing packages before changing the vehicle environment:

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install smbus2 PyYAML
# 需要语音时再安装
python3 -m pip install -r requirements-voice.txt
```

Configure CANN, ACL, Orbbec binding, `ais_bench`, and the board's `torch` / `torchvision` according to existing SDK and platform versions; the generic package list above cannot supply everything. Inspect a working device environment first to avoid incompatible replacements. Complete import check:

```bash
python3 -c 'import cv2, numpy, pyorbbecsdk, acl, ais_bench, yaml, serial, filelock, torch, torchvision, smbus2; print("dependencies ready")'
```

If the current `python3` lacks main-program dependencies, inspect the installed `/usr/local/miniconda3/bin/python` environment, then substitute that absolute interpreter path in startup commands. The dedicated camera environment and main-program environment have different package sets.

## 6. File structure

```text
AstraPlusCar/                         # 工作区根目录，不是 Git 仓库
├── AstraPlusCar-device/              # 本仓库
│   ├── README.md
│   ├── docs/
│   │   ├── PHONE_API.md              # 手机 HTTP 协议
│   │   └── STREAM_DIAGNOSIS_2026-10-02.md  # 断流诊断记录
│   ├── deploy/astra-phone.service    # 正式服务配置模板
│   ├── python/
│   │   ├── main.py                   # 统一主入口
│   │   ├── start_phone.sh            # 正式 phone 服务启动脚本
│   │   ├── motion_control.py         # 指令仲裁、速度、定时动作、停车
│   │   ├── phone_mode.py             # HTTP 会话、续期与 API
│   │   ├── astra_camera.py           # Astra+ 取流与图像转换
│   │   ├── camera_tasks.py           # 后台截图任务
│   │   ├── camera_probe.py           # 独立取帧 / 拍照检查
│   │   ├── camera_preview.py         # 共享预览服务与独立预览入口
│   │   ├── lidar_probe.py            # 雷达扫描工具与后台服务
│   │   ├── voice_control.py          # Vosk 服务与文字映射工具
│   │   ├── requirements*.txt
│   │   ├── src/
│   │   │   ├── actions/              # 基础动作与组合动作
│   │   │   ├── scenes/               # Manual、Helper、LF、Tracking 场景
│   │   │   ├── models/               # Ascend 模型封装与后处理
│   │   │   └── utils/                # 底盘、相机广播、日志与 ACL 工具
│   │   ├── weights/                  # yolo.om；其他模型另行配置
│   │   ├── capture/                  # 默认截图输出
│   │   ├── logs/                     # 运行日志
│   │   └── test/
│   │       ├── offline/              # 离线回归用例
│   │       ├── live_phone_api.py     # 实车 Phone API 检查
│   │       └── diagnose_phone_stream.py  # 只读视频/状态诊断
│   ├── ESP32/                        # ESP32 电机 / 舵机固件
│   ├── 基于ESP32的智能小车控制/      # 接线与控制方案资料
│   ├── Lane-Follow-Train/            # 巡线模型训练
│   ├── auto_label_tool/              # 车道线 HSV 标注工具
│   ├── det_label_split/              # 检测数据转分类数据与训练工具
│   ├── lidar_test/                   # 雷达 SDK、ROS2 示例与配置
│   └── notebook/                     # 历史交互控制示例
└── AstraPlusCar-HarmonyOS/           # 独立的 ArkTS 应用仓库
    ├── entry/src/main/ets/           # 页面、组件、API、图库与模型
    └── README.md
```

`python/src/utils/main.py` is a legacy entry point, not the main program described here; start the vehicle through `python/main.py`. Temporary integration directories and scripts exist on the vehicle but are not official deployment files in this tree.

## 7. Extension and validation

### 7.1 Add scenes and hardware capabilities

For a new AI scene, follow `src/scenes/base_scene.py`, register its name in `src/scenes/__init__.py`, and start it through `cmd`. Scenes read shared main-program frames and submit actions to the unified motion interface. Camera preview, captures, and AI reuse one broadcaster, avoiding repeated camera opens and multiple processes writing directly to the chassis.

When adding mobile features, check both device APIs and the HarmonyOS client. Motion, renewal, emergency stop, error responses, and units must agree. Motor control, ESP32 pins, and low-level serial behavior stay on the device; the client sends high-level commands only.

Servo actions and ESP32 code remain in the repository, but the current main program has no standalone servo argument or mobile servo API. Do not treat historical firmware features as current remote-control entry points. Recheck stop behavior and wheel directions after changing chassis drivers.

### 7.2 Data collection, annotation, and training

| Extension tool | Entry point and description |
| --- | --- |
| Lane annotation | [auto_label_tool](auto_label_tool/README.md): Configure image paths in `config/` within that directory, extract color ranges with `python3 check_hsv.py`, then annotate using `python3 main.py`. This `main.py` is the annotation tool |
| Lane-following training | [Lane-Follow-Train](Lane-Follow-Train/README.md): Prepare data and `config.yaml` in that directory, run `python3 train.py`, then convert the model to `.om` for the target Ascend platform |
| Auxiliary detection classification | [det_label_split](det_label_split/README.md): Data conversion, classification training, and model conversion tools; the current `Helper` does not enable auxiliary classification |
| ESP32 control | [Control design](基于ESP32的智能小车控制/基于ESP32的智能小车控制.md) and `ESP32/` firmware |
| ROS2 lidar / mapping | Examples in `lidar_test/`; ROS2 was not previously installed on the vehicle and requires separate setup and acceptance |

ATC chip targets and input formats in training documents are example configurations. Verify them against the actual board, model, and CANN version during conversion. Run training and annotation in their own directories and dependency environments; they are not vehicle driving modes.

### 7.3 Official deployment and service

On 2026-09-30, deployment to the original vehicle directory and installation of the official `astra-phone.service` were completed; the temporary `astra-phone-integration` service was stopped. `python/start_phone.sh` enters the official directory, loads CANN and Orbbec binding, then runs `/usr/local/miniconda3/bin/python main.py --mode phone`; `deploy/astra-phone.service` uses this script.

For subsequent deployments, back up and compare the original directory first, ensuring Python code, SDK dependencies, and models match. Run `systemctl daemon-reload` after updating service templates. Files replaced during this deployment are backed up at `/home/HwHiAiUser/astra-backups/phone-20260930`.

### 7.4 Offline and physical-vehicle validation

Run device-side offline tests from this repository's root; the development environment requires NumPy and OpenCV:

```bash
PYTHONPATH=python python3 -m unittest discover -s python/test/offline -v
PYTHONPATH=python python3 -m unittest discover -s python/test/utils -p test_camera_broadcaster.py -v
```

Coverage includes mode arguments, shared frames, captures, HTTP, voice/keyboard takeover, timing, stopping, and resource cleanup. Tests may skip when a sandbox lacks loopback ports or POSIX shared memory. Other historical cases in `python/test/` use old interfaces and hardware dependencies and are separate from these offline checks.

HTTP physical-vehicle check entry point (run from the repository root):

```bash
python3 python/test/live_phone_api.py --base-url http://192.168.8.204:8080
```

By default, it checks status, video, capture creation, and downloads without motion commands, creating one capture on the vehicle. Add `--motion` **only with the wheels safely lifted** to check short motion, speed, renewal, stopping, and connection-loss protection.

Prior physical-vehicle records confirm Astra+ color acquisition, non-black captures, 10-minute continuous acquisition, and same-WLAN mobile video, lidar, captures, and gallery. Phone API motion checks were brief and performed only with wheels lifted, confirming command acceptance, stopping, and 600 ms connection-loss protection. **Actual wheel directions, ground driving, each AI scene, voice driving, and app-background stopping still require separate on-site validation; offline tests cannot replace this acceptance.**
