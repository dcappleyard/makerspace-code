# Design: EE04 4.26" B/W frame as a battery-powered pull client

## Why

The EE04 is a small battery board with a monochrome panel. It should be fed by the
same eink_photo_server as the other frames, so there's one place to manage photos
and schedules, and it should run for months on a LiPo.

## Decisions (2026-11-25)

**Battery and deep sleep.** The frame is awake only to pull. Everything that
depends on staying awake is gone: the status page, Pull now, mDNS, NTP and the
`millis()` scheduler.
- **The countdown moves to the RTC sleep timer.** `millis()` resets on every wake.
- **The server stays the clock.** It sends relative seconds (`next_check_s`), so the frame never needs the time of day, and the EE04 has no RTC chip.
- **Drift is the server's job.** The RTC timer drifts about 1%. The existing early-wake rule and wake offset absorb it.

**Photos first, on a new `ee04_bw1` pipeline.** The server fits the photo (cover
or letterbox), tunes it (contrast 1.15 by default), dithers to 1-bit and packs
it in the exact layout of Seeed_GFX's 1-bit sprite buffer. The firmware copies
48,000 bytes straight into the sprite. There's no decoding on the device.

**Offline fallback = the last image.** There's no SD card, and e-paper holds its
image with no power, so failing to pull costs nothing visible. Retries back off
(5, 15 and 30 min, then hourly) so an outage doesn't drain the battery.

**`keep` avoids a refresh.**
- **The current image name lives in RTC memory.** That lets the frame report `current` on every timer wake, so an unchanged schedule slot costs a short WiFi session and no refresh.
- **A cold boot clears it on purpose,** as the EE03 does at boot: the frame doesn't trust what's on the panel and asks for a redraw.

**Battery is reported, not just read.**
- **What's sent:** `battery` (%) and `battery_mv` ride on each pull.
- **On the server:** the % feeds the existing `battery_monitor` overlay, and both readings land in the frame's event log.
- **When it's read:** before WiFi starts, so the radio's load doesn't sag it.
- **Low-battery cutoff:** below 3.30 V the frame stops pulling and sleeps 12 h.

**Power in sleep.**
- **The panel:** the controller is put to sleep by `update()`. Its supply enable (GPIO43) and the battery divider's enable (GPIO6) are then driven LOW and held through deep sleep.
- **On wake:** the frame powers the panel only when it draws.

**Fast reconnect.** The last AP's BSSID and channel are kept in RTC memory, so
a wake usually joins without a scan. If that fails, it falls back to a normal
connect.

**Development stays practical.** It stays awake for 2 min after a cold boot, and
while a USB host is attached, as `xiao_s3_sense_photobooth` does. So
uploads and the serial monitor work without timing games.

## Deliberately not done (yet)

- **Buttons.** KEY0–2 (GPIO 2/3/5) are RTC-capable, so they could become deep-sleep wake sources (e.g. "next image"). For now they do nothing.
- **Text and dashboard content.** The pipeline contract allows any server-rendered 1-bit image. Photos come first.
- **A local cache / offline cycling.** No SD card. A LittleFS cache would be possible (48 KB per image), but it isn't worth it while the last image simply stays up.
- **Partial refresh.** Seeed_GFX supports it on this panel, but every change here is a whole new image.
- **OTA updates** and a status page: both need the frame to stay awake.
- **A BUSY-wait timeout.** Seeed_GFX's `CHECK_BUSY()` spins forever if the panel never answers. A disconnected panel would hang the frame awake, which shows up as a flat battery.
