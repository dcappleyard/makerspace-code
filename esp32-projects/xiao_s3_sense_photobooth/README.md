# xiao_s3_sense_photobooth

A battery-friendly photo booth on the **XIAO ESP32-S3 Sense** with the **1.28" round touch display**. It's the same hardware as `../xiao_s3_sense_webcam`, and the camera, display and SD code started as a copy of it.
- **No web server.** WiFi is only used once at boot, to set the clock, and is then switched off. Pushing photos to a Raspberry Pi is planned but not built yet; see [Later: WiFi upload](#later-wifi-upload).
- **Hardware:** see `../hardware_info.md`.

## How it works

| Step | What happens |
|---|---|
| **Asleep** | Screen off, camera off, WiFi off, CPU in light sleep. **Tap the screen** to wake. |
| **Live view** | The camera feed on the round screen. After **30 s** with no touch, it goes back to sleep. |
| **Tap** | Asks **"Capture?"**: **Yes** on the left half, **No** on the right. |
| **No, or no answer in 3 s** | Back to the live view. |
| **Yes** | Three shots, **A**, **B** and **C**. For each one:<br>- a **3..2..1** countdown over the live view, 1 s per number<br>- a white **flash** at capture<br>- the photo is shown for **3 s** |
| **After C** | Back to the live view. |

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
- **If `include/secrets.h` has WiFi credentials,** it also connects once, syncs from NTP, writes the time back to the RTC, and **switches WiFi off**.
- **Without credentials,** it runs on the RTC alone. On a brand-new RTC (or a dead coin cell), photos get `nodate_` names until one boot with WiFi sets it.

### Sleep and power

- **Asleep:** the booth uses ESP32-S3 **light sleep**, woken by the touch controller's interrupt (GPIO44).
  - Before sleeping, it shuts the camera down (no clock, no DMA), puts the display panel to sleep, and turns the backlight off.
  - Deep sleep isn't used: GPIO44 can't wake it, because only GPIO0–21 can.
- **The camera sensor itself stays powered.** The Sense board has no power-down line, so the sensor is unclocked but not off. SD cards also keep some idle current. Measure before counting on a number.
- **With a computer on USB** (`STAY_AWAKE_ON_USB_HOST`), "asleep" means screen and camera off but the CPU awake. Light sleep would drop the USB serial port, which breaks uploads and the serial monitor. On battery or a power-only charger it really light-sleeps.

## Setup

1. **Optional: copy `include/secrets.h.example` to `include/secrets.h`** and set `WIFI_SSID` / `WIFI_PASSWORD`, so the clock gets set from NTP at boot. It's gitignored, and the build works without it.
2. **Insert a FAT32 microSD card** in either slot: the Sense board's, or the round display's. The firmware creates `/photos/` itself.
3. **Set the display's KE switches:** both OFF worked on our unit; see `../hardware_info.md`.
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
src/rtc_clock.{h,cpp} PCF8563 RTC read/write, one-off NTP sync at boot
src/main.cpp         setup order and loop
lib/driver/driver.h  Seeed_GFX screen selection (BOARD_SCREEN_COMBO 501 = round display)
```

**Camera settings:** image settings (exposure, white balance, mirror/flip, and so on) come from NVS, using the same keys `../xiao_s3_sense_webcam` saves from its web page. To tune them, flash the webcam, adjust in the browser, then flash the booth back; the settings carry over.

**Camera facing you:** if the camera faces the subject, like a selfie, you may want the live view mirrored. There's no setting for that yet.

## Later: WiFi upload

The plan is to **push** photos to a Raspberry Pi on the network after each sequence, or in batches when awake. Pushing means the booth only needs WiFi briefly, whereas a Pi pulling on a schedule would need the booth awake and reachable.

The booth already shuts WiFi down after the boot sync, so an upload step would bring it up, send the new photos, and switch it off again. Waiting on the network and Pi-side design.

## Verified vs. unverified

**Verified on hardware:** the live view, prompt and three-shot sequence run. Then these changes were made, and are built but not yet run:
- display rotated 90° clockwise (`DISPLAY_ROTATION = 1`)
- 1 s countdown steps, 3 s review
- capture reordered for a shorter flash

**Verified on hardware:** the two-slot SD mount. A 16 GB FAT32 card in the round display's slot mounts at 20 MHz, and photos land in `/photos/`.

**Builds:** clean with and without `secrets.h` (16.3% flash without WiFi, 33.5% with).

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
  - three files `…_A/_B/_C.jpg` land on the card at full size and look properly exposed
- **No card:** the review says "no SD card". Insert a card, let it sleep, tap again: the photos move to `/photos/`.
- **Idle:** the live view goes to sleep after 30 s.
- **Power:** ideally, measure the current asleep vs. in live view. The webcam's battery logger can't run here (no web page), so use a USB power meter, or a discharge test with a fixed number of wakes.
