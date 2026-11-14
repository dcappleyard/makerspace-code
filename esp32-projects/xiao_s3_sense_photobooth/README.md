# xiao_s3_sense_photobooth

A battery-friendly photo booth on the **XIAO ESP32-S3 Sense** with the **1.28" round touch display**. It's the same hardware as `../xiao_s3_sense_webcam`, and the camera, display and SD code started as a copy of it.
- **No web server.** WiFi is only brought up briefly: at boot to set the clock, and when going to sleep to upload photos to the `../../python-projects/eink_photo_server` on a Raspberry Pi. See [WiFi upload](#wifi-upload).
- **Hardware:** see `../hardware_info.md`.

## How it works

| Step | What happens |
|---|---|
| **Asleep** | Screen off, camera off, WiFi off, CPU in light sleep. **Tap the screen** to wake. |
| **Live view** | The camera feed on the round screen. After **30 s** with no touch, it goes back to sleep. |
| **Tap** | Asks **"Capture?"**: **Yes** on the left half, **No** on the right, and a **Setup** button set well below them (see [Setup screen](#setup-screen)). |
| **No, or no answer in 3 s** | Back to the live view. |
| **Yes** | One shot (`SHOTS_PER_SEQUENCE`; set it higher for A/B/C):<br>- a **3..2..1** countdown over the live view, 1 s per number<br>- a white **flash** at capture<br>- the photo is shown for **3 s** |
| **After the shot** | Back to the live view. |

All of these timings are constants in `src/booth_config.h`: `LIVE_IDLE_SLEEP_MS`, `CONFIRM_TIMEOUT_MS`, `COUNTDOWN_FROM`, `COUNTDOWN_STEP_MS`, `FLASH_MS`, `REVIEW_MS` and `SHOTS_PER_SEQUENCE`.

**Touch rules:**
- A held finger counts as one tap.
- After every screen change, touches are ignored for 1 s (`TOUCH_LOCKOUT_MS`), the same lockout as the webcam. Otherwise lifting off "No" would re-open the prompt.
- Touches during a sequence are ignored.

### Photos

- **Full size, best quality:**
  - The live view runs at VGA, so decoding keeps up.
  - Each shot switches the camera to the sensor's largest size (1600×1200 on an OV2640, 2048×1536 on an OV3660) at JPEG quality 8, then switches back.
  - Below ~8, a full-size JPEG can overflow the camera's frame buffers.
- **Names:** `/photos/2026-10-23_14-03-22_A.jpg`, `_B`, `_C`. The timestamp is taken when you press Yes and shared by all three. If the clock was never set, names start `nodate_<uptime>`.
- **No SD card:** photos are kept in RAM, at most the last 6 or 4 MB, and lost on reboot. The review screen says "no SD card".
- **Late card:** if a card is inserted later, the booth picks it up at the next wake and moves the RAM photos onto it.
- **Card format:** FAT32. exFAT isn't supported by this build's SD library.
- **Either SD slot works:** the Sense board's (CS GPIO21) or the round display's own (CS D2 / GPIO3, the one Seeed's wiki points to when the round display is fitted).
  - At boot both are tried, each at 20 MHz and then 4 MHz. Every attempt is logged, for example `SD: round display slot (CS 3) at 20 MHz: OK (133 ms)`.
  - The slot that worked last is remembered in NVS and tried first, because an empty slot takes ~600 ms to give up on. It defaults to the round display's slot, which is where our card turned out to be.
  - At wake, each slot gets one quick 4 MHz attempt, so a missing card barely delays the live view.

**The flash is kept short by ordering.**
- **Before the flash:** at the end of the "1", the screen freezes while the camera switches to full size and drops `CAPTURE_DISCARD_FRAMES` settling frames.
- **During the flash:** it only covers one fresh full-size frame, plus `FLASH_DISCARD_FRAMES` dropped so the saved frame was exposed with the screen white. It lasts at least `FLASH_MS` (0.25 s).
- **After the flash:** the screen goes black. Then the photo is decoded for review, shown, and saved to SD while it's on screen.
- **Timings in the log:** each shot logs how long the size switch, flash, review decode and save took. If captures come out badly exposed, raise `CAPTURE_DISCARD_FRAMES`; that only lengthens the frozen "1", not the flash.

### Clock

Photo names need the time. The round display has a **PCF8563 RTC** with a coin cell, which keeps time with the board off.
- **At boot,** the booth reads the RTC.
- **If `include/secrets.h` has WiFi credentials,** it also connects once, sets the clock, writes the time back to the RTC, and **switches WiFi off**. The clock comes from the photo server's HTTP `Date` header when `SERVER_URL` is set: it's on the LAN and needs no NTP or outside access. NTP is the fallback. Photos taken before the clock has ever been set are named `nodate_<uptime>`; the server dates those by arrival and tags them `nodate`.
- **Without credentials,** it runs on the RTC alone. On a brand-new RTC (or a dead coin cell), photos get `nodate_` names until one boot with WiFi sets it.

### Sleep and power

- **Asleep:** the booth uses ESP32-S3 **light sleep**, woken by the touch controller's interrupt (GPIO44).
  - Before sleeping, it shuts the camera down (no clock, no DMA), puts the display panel to sleep, and turns the backlight off.
  - Deep sleep isn't used: GPIO44 can't wake it, because only GPIO0–21 can.
- **The camera sensor itself stays powered.** The Sense board has no power-down line, so the sensor is unclocked but not off. SD cards also keep some idle current. Measure before counting on a number.
- **With a computer on USB** (`STAY_AWAKE_ON_USB_HOST`), "asleep" means screen and camera off but the CPU awake. Light sleep would drop the USB serial port, which breaks uploads and the serial monitor. On battery or a power-only charger it really light-sleeps.
- **For the first 60 s after any boot** (`BOOT_STAY_AWAKE_MS`), it also stays awake, so an upload can start even if the USB cable goes in just after a reboot.

## Setup

1. **Optional: copy `include/secrets.h.example` to `include/secrets.h`** and set `WIFI_SSID` / `WIFI_PASSWORD`, so the clock gets set from NTP at boot. To also upload photos, set `SERVER_URL` (use an IP, e.g. `http://192.168.30.10:8080`) and `UPLOAD_TOKEN` (the server's `sources:` `photobooth` `upload_token`). It's gitignored, and the build works without it.
2. **Insert a FAT32 microSD card** in either slot: the Sense board's, or the round display's. The firmware creates `/photos/` itself.
3. **Set the display's KE switches** to Seeed's ON position, so the firmware controls the backlight and A0 reads the battery for the log; see `../hardware_info.md`.
4. **Flash** from this folder:
   ```
   pio run -t upload && pio device monitor
   ```
5. **Tap the screen.** The serial log shows the clock source, the sensor, SD state, and a line per shot.

## Source layout

```
src/booth_config.h   pins, booth timings, camera modes, sleep and clock constants (MUST be the first include -- FS.h order)
src/booth.{h,cpp}    the state machine: sleep / live / Capture? / countdown, flash, review x3
src/screen.{h,cpp}   round display: panel power, touch, light sleep, sprite-composed frames and overlays
src/camera.{h,cpp}   esp32-camera init/off, live vs full-size capture modes
src/storage.{h,cpp}  SD on the display's SPI bus, /photos, RAM fallback, names
src/rtc_clock.{h,cpp} PCF8563 RTC read/write, clock sync (photo server Date header, then NTP), wifiUp()/wifiDown()
src/upload.{h,cpp}   uploads pending photos to the eink_photo_server at sleep
src/main.cpp         setup order and loop
lib/driver/driver.h  Seeed_GFX screen selection (BOARD_SCREEN_COMBO 501 = round display)
```

**Camera settings:** image settings (exposure, white balance, mirror/flip, and so on) come from NVS, using the same keys `../xiao_s3_sense_webcam` saves from its web page. To tune them, flash the webcam, adjust in the browser, then flash the booth back; the settings carry over.

**Camera facing you:** if the camera faces the subject, like a selfie, you may want the live view mirrored. There's no setting for that yet.

### Setup screen

Tap **Setup** on the Capture? prompt. The controls are drawn over the live view, so you can see changes as you make them. With no touch for 20 s (`SETUP_TIMEOUT_MS`), it returns to the live view.
- **Exposure − / +:** exposure compensation from −2 to +2, the sensor's auto-exposure target (`ae_level`).
  - It defaults to **−1** (`EXPOSURE_COMP_DEFAULT`), to tame blown-out highlights.
  - It's saved in NVS and applies to the live view and the photos. It only acts while auto exposure is on, which is the default.
- **Done:** back to the live view.
- **Reboot:** asks "Reboot?" first, then restarts the chip in software, the same as pressing RST.

**To flash new firmware without unplugging the battery:**
1. Plug in USB-C.
2. Open **Setup → Reboot → Yes**.
3. Run `pio run -t upload` within a minute.

Light sleep makes the USB port disappear. After a reboot, the booth stays awake for 60 s, and indefinitely while a computer is attached, so the port stays up for the upload.

### Screen orientation

- **Camera:** the camera sits upside down in the case, so `CAMERA_ROTATE_180 = true` turns everything it delivers by 180° at the sensor (mirror + flip, on top of any saved settings). Saved and uploaded photos come out upright.
- **Rotation:** `DISPLAY_ROTATION = 3` makes the GUI upright in the 3D-printed case.
- **Live view:** `LIVE_FLIP_H = true` mirrors it left-right in software, like a mirror. That only affects the screen.
- **Review:** the photo shown after the shot is the upright photo itself, so `REVIEW_FLIP_H` / `REVIEW_FLIP_V` are off. Turn one on if it comes out wrong in the case.

## Battery log

The booth keeps a CSV log of the LiPo's voltage. A0 is read through the round display's divider, so the KE switch must route it, and the battery voltage is assumed to be 2 × A0.
- **When a row is written:** at boot, wake, sleep and each upload, and every **5 minutes** while asleep (`BATTERY_LOG_INTERVAL_S`). For that reading the board wakes from light sleep on a timer, with the screen off and no WiFi; a touch still wakes the booth as normal.
- **Where it's kept:** in the board's internal flash (LittleFS), so it survives the battery dying. Rows: `epoch,local_time,boot,uptime_s,event,a0_mv,battery_mv`.
- **How it reaches the Pi:** new rows are pushed to the photo server's `POST /sources/photobooth/battery`.
  - It only goes **with photo uploads**: WiFi never comes up just for the log. So the server's copy is as fresh as the last photo; rows logged since then wait in flash until the next one.
  - The server appends by byte offset, so retries never duplicate rows.
  - Rows written after the last photo before the battery died go up with the first photo after it's recharged.
- **On the booth:** the "Capture?" prompt shows **Bat: X%** under Yes/No.
  - It's a best guess from the last **resting** reading, the one logged at the start of each wake before the screen and camera draw current. Under load the voltage sags and would read low.
  - That reading is mapped through `BATTERY_PERCENT_MV`: a typical LiPo resting-voltage curve, with 0% at 3.50 V, about where the booth browns out.
  - Replace that table with the curve from a full discharge run once you have one. The line is hidden if A0 sees no battery.
- **Viewing:** on the server, the photobooth source's page has a **Battery logs** panel with a voltage chart, a CSV download and Delete.
- **Clearing:** flashing a build with a different `BATTERY_LOG_GENERATION` starts a fresh log under a new id, and wipes the old one from the booth's flash. The server keeps old logs until you delete them there.

## WiFi upload

When the booth goes to sleep (30 s after the last tap, or immediately on the existing sleep path), the camera is already off and the screen still on. If any photos are pending, it:
1. Brings WiFi up (the existing 15 s connect timeout).
2. POSTs each pending photo, oldest first, to `SERVER_URL` + `/sources/photobooth/upload`. The source id is `UPLOAD_SOURCE` in `src/booth_config.h`. Headers are `X-Access-Token` = `UPLOAD_TOKEN` and `X-Filename` = the photo's name. It streams from the SD card, or from PSRAM for shots taken without a card.
3. Shows "Uploading... n of N", then "Uploaded" / "Upload incomplete", or "Upload later / no WiFi: \<why\>".

**When WiFi won't connect,** it scans for `WIFI_SSID` and reports why. This happens at boot and before an upload.
- **On screen:** `<why>` is the driver's last disconnect reason plus the SSID's best RSSI, e.g. `AUTH_FAIL -61dBm`. If the scan can't find the network at all, it shows `SSID not seen`.
- **Battery log:** the same text goes in as a `wifi_fail:...` row, which includes the voltage at the failure. It reaches the server with the next upload that gets through.
- **Serial:** the full detail. This covers the status code, every AP broadcasting the SSID (RSSI, channel, BSSID, auth mode), or, if the SSID isn't seen, the first 10 networks the scan did find.

How to read it:
- **`SSID not seen`:** the network isn't on 2.4 GHz where the booth is, or it's on channel 12-13, or the antenna isn't making contact.
- **`AUTH_FAIL`, `4WAY_HANDSHAKE_TIMEOUT` or `HANDSHAKE_TIMEOUT`:** check the password and the router's security mode. A WPA3-only network is a likely culprit.
- **Weak RSSI (below about −80 dBm):** a signal or antenna problem.
- **Fails only on battery:** power. The `wifi_fail` rows in the battery log show the voltage.

- **Accepted photos:** a card photo the server accepted (stored or duplicate) moves to `/photos/uploaded/`. It stays on the card, just out of the way. RAM-only photos are dropped once uploaded.
- **Retries:** anything not sent is retried at the next sleep. That covers the server being down or refusing (the uploader stops at the first failure) and the per-session budget running out. Constants: `UPLOAD_BUDGET_MS` (60 s per session) and `UPLOAD_HTTP_TIMEOUT_MS` (20 s per photo).
- **Clock:** before uploading, it sets the clock from the server (NTP as fallback) and writes the RTC. That fixes drift, and it means the next sequences get real names even if the clock was never set. Then WiFi goes off again.
- **Needs all of** `WIFI_SSID`, `SERVER_URL` and `UPLOAD_TOKEN` in `secrets.h`. Without them upload is compiled out and nothing else changes.

## Verified vs. unverified

**Verified on hardware:** the live view, prompt and shot sequence, with the 1 s countdown, 3 s review and the reordered (shorter) flash. The booth runs in its case on a 1000 mAh LiPo.

**Not yet confirmed on hardware:** the upload. That covers photos moving to `/photos/uploaded/`, a retry after the server was down, and no-SD RAM shots.

**Verified on hardware (2026-11-14):** the WiFi failure diagnostics: disconnect reason, SSID scan, and the `wifi_fail` battery-log row. They caught a mis-placed antenna: `AUTH_EXPIRE`, and a scan that found 0 networks. Also verified: Setup → Reboot gets the USB upload port up without pulling the battery.

**Verified on hardware (2026-11-14, reported working):** the Setup button on the prompt; the Setup screen (exposure −2..+2 defaulting to −1, Done, Reboot with confirm); the 60 s stay-awake after boot; and dropping the OV3660 `brightness +1` tweak (from Espressif's example), which was adding to the blown-out exposures.

**Built, not yet run on hardware (2026-10-31):**
- the GUI rotated 180° (`DISPLAY_ROTATION = 3`)
- photos rotated 180° at the sensor (`CAMERA_ROTATE_180`), with the live view mirrored (`LIVE_FLIP_H`) and the review left as the photo
- a single shot per "Yes"
- the battery log: timer wakes, pushing with photo uploads, and the fresh-log clear
- the "Bat: X%" line on the Capture? prompt

**Verified on hardware:** the two-slot SD mount. A 16 GB FAT32 card in the round display's slot mounts at 20 MHz, and photos land in `/photos/`.

**Builds:** clean with and without `secrets.h`. Without it: 17.9% flash. With upload enabled: 39.6% flash (1,322,094 of 3,342,336 bytes) and 19.6% RAM.

**What's carried over:** these are copied from `../xiao_s3_sense_webcam`, where they work on hardware:
- the camera
- the display on a shared SPI bus with the SD card
- the touch reading
- the preview colours (`PREVIEW_SWAP_BYTES = true`)
- the Yes/No lockout

**Check on hardware, in order:**
- **Boot log:** a `Clock: source=…` line, then `Booth ready`.
- **Wake:** a tap shows "One moment..." and then the live view.
  - On battery, or with no computer attached, the board really light-sleeps first. Check that a tap still wakes it; that's the touch INT as a light-sleep wake source.
- **Prompt:** No and the 3 s timeout both return to live view without re-prompting.
- **Sequence:**
  - the countdown numbers are readable over the image
  - the flash is visible and not too long
  - each review shows the right photo
  - one file `<date_time>.jpg` lands on the card at full size and looks properly exposed
- **No card:** the review says "no SD card". Insert a card, let it sleep, tap again: the photos move to `/photos/`.
- **Idle:** the live view goes to sleep after 30 s.
- **Battery log:** a `Battery log: started fresh log …` line at boot. After taking a photo and letting the booth sleep, `Battery log <id>: … -> 200` on the serial monitor (or the server's log), and the chart appears on the server's photobooth page.
- **Orientation:** the uploaded photo is upright. The live view is mirrored, and the review is upright and not mirrored.
