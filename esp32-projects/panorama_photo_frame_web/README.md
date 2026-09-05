# panorama_photo_frame_web

A mains-powered panorama photo frame on the XIAO ePaper DIY Kit EE03 (10.3"
panel) with a microSD card for image storage and a **LAN web interface** for
uploading photos, setting the clock, and adjusting the counter.

This is the always-awake, networked successor to
`../panorama_photo_frame_w_counter`, which stays in the repo and still works.
Everything about the **picture display is identical** — same `.bin` format, same
`/pictures/` ordering, same sidecar metadata, same caption renderer, same
`prepare_image.py` on the host. What changed is the interface. See `DESIGN.md`
for why, and the sibling's `DESIGN.md` for the original battery-era rationale.

Same board/display as `../ee03-text-test`, `../test_bw_image_eink`, and
`../wifi_counter_eink`; the SD-card mod is the one proven out in
`../eink_sd_test` — see `../hardware_info.md`.

## What's different from the deep-sleep version

| | `panorama_photo_frame_w_counter` | this project |
|---|---|---|
| Power | battery, deep sleep between refreshes | **plugged in, always awake** |
| Clock | pasted over serial on every cold boot | **NTP, self-healing**, with a web override |
| Photos | pull the card, copy files, reinsert | **upload over the web** (card optional) |
| Counter | two buttons only | buttons **or** web |
| Buttons | deep-sleep ext1 wake sources | polled GPIO in `loop()` |
| SD card | mounted for sub-second windows | **mounted continuously** (eject before pulling) |
| Photo choice | next-in-order only | next, or **jump to any photo** |

Battery operation was the constraint that shaped the original design, and it
didn't work out — the frame ended up permanently plugged in, so this version
spends the power budget on being reachable instead.

## Setup

1. Copy `include/secrets.h.example` to `include/secrets.h` and fill in your real
   WiFi credentials. `include/secrets.h` is gitignored — never commit the real
   one. (Same convention as `../wifi_counter_eink`.)
2. Prepare each photo on your computer with
   `python-projects/grayscale_image_conversion/prepare_image.py`:
   ```
   python3 prepare_image.py ~/Pictures/harbor.tif --output-dir ./sd_pictures
   ```
   It prompts for Artist / Date / Location / Title / Film and writes
   `<name>.bin` (exactly 1,314,144 bytes), `<name>.xml`, and a `<name>.png`
   preview.
3. Put a `frame_config.xml` and a `/pictures/` directory on a FAT32 card (see
   `sd_card_template/`), or just insert a formatted card — the firmware creates
   `/pictures/` itself and falls back to sane defaults with no config file.
4. Flash:
   ```
   pio run -t upload
   ```
5. Open the serial monitor to read the IP address, or try
   `http://photo-frame.local/`. The IP is also drawn in the **top-right corner
   of the panel** at each refresh.

There's no `uploadfs` step and no serial clock ritual — both are gone.

## Web interface

| Page | What it does |
|---|---|
| `/` | Status: current photo, counter, time to next refresh, clock, WiFi, SD free space, uptime, heap. Buttons for next/redraw, the counter row, and card eject. |
| `/photos` | Every `.bin` on the card with its caption metadata, the current one marked, and a **Show** button to jump straight to any of them. |
| `/history` | **History Data** &mdash; the counter log as a table, newest first. |
| `/history/plot` | **History Plot** &mdash; counter value over time, with 1/3/6-month, 1-year and full windows. |
| `/upload` | Upload a `.bin` + `.xml` pair. |
| `/clock` | Local time, timezone, and manual clock override. |
| `/status.json` | The same status as `/`, machine-readable. |

State-changing routes are POST-only and answer with a 303 redirect. That's not
decoration: browsers, link-preview generators, and LAN scanners all issue
unsolicited GETs, and none of them should be able to advance the frame just by
touching a URL.

### Security — read this

**There is no authentication.** Anyone who can reach this device on your LAN can
browse your photos' metadata, change which photo is displayed, adjust the
counter, set the clock, and **write `.bin`/`.xml` files onto the SD card**,
including overwriting an existing photo under its own name.

Filenames are sanitized and sizes are strictly bounded, so a request can't
escape `/pictures`, can't write a dotfile, and can't quietly fill the card — but
that is containment, not access control. This is an acceptable trade on a
trusted home LAN and nowhere else. **Do not port-forward this.**

To turn on HTTP Basic Auth, uncomment `WEB_AUTH_USER` and `WEB_AUTH_PASS` in
`include/secrets.h`. `requireAuth()` in `src/web.cpp` already guards every
route, so those two lines protect the whole interface at once. Note that Basic
Auth over plain HTTP sends the password in near-cleartext on every request: it
raises the bar against casual access, not against anyone sniffing the network.

## Uploading photos

Pick the matching `.bin` and `.xml` in the form and submit them together. The
upload is **all-or-nothing**: both files stream to temporary files at the card
root and are only moved into `/pictures/` once every check has passed. If
anything fails — a rejected filename, a truncated `.bin`, a short write, a
client that disconnects halfway — nothing is committed and `/pictures/` is left
exactly as it was. A half-updated pair would show a new photo under the old
caption, which is worse than no update at all.

Checks applied to every upload:

- Filename is reduced to its basename (both `/` and `\` are stripped), must be
  1-40 chars of `[A-Za-z0-9._-]` with exactly one dot, must not start with `.`,
  and must end in `.bin` or `.xml` (case-insensitive).
- **`.bin` must be exactly 1,314,144 bytes.** This is the important one: the
  display path hard-fails a short read, so a truncated file would blank that
  slot. Extension mismatches and stray `._` shadow files are rejected outright.
- `.xml` is capped at 8 KB.
- At least 2 MB must be free on the card before the transfer starts.

A 1.3 MB upload takes roughly 10-30 seconds. The form disables its button and
says so, because otherwise it looks like a hang and people double-submit.

Uploading doesn't change what's on screen — you may be adding several photos.
The uploaded row is highlighted on `/photos` with a **Show** button.

## Clock

The frame syncs over NTP whenever it has WiFi, so a power cut heals itself with
no intervention. This replaces the serial clock-setting ritual the previous
version needed (its `clock_set_instructions.md` is gone).

Timezone is a POSIX TZ string in `frame_config.xml`, defaulting to
`CST6CDT,M3.2.0,M11.1.0` (US Central with US DST rules). The Clock page can
change it and writes the new value back to the card.

The manual override on the Clock page is for when NTP can't be reached — a
network with no outbound DNS/NTP, say. **If NTP later does reach a server it
will step the clock and override whatever you set by hand.** That's correct
(NTP is more accurate) but surprising if you don't expect it.

The frame never depends on the clock being right: photo cycling uses a
monotonic timer, not wall time, and a counter change with no valid clock is
logged as `TIME_NOT_SET` rather than a bogus timestamp.

## Buttons

Same GPIO pins as the other EE03 projects (2, 3, 5), now polled with a 50 ms
debounce rather than used as deep-sleep wake sources:

| Button | Action |
|---|---|
| GPIO2 | Advance to the next photo (and restart the refresh interval) |
| GPIO3 | Counter +1 |
| GPIO5 | Counter -1 |

The web UI offers a row of steps from **-5 to +5** (no 0 -- it would be a no-op
that still costs an SD write and a log line). Each is a plain POST form, so the
row works with JavaScript disabled. The GPIO buttons stay at +/-1.

**A counter change does not redraw the panel.** The value is written to
`frame_config.xml` and logged to `counter_track.txt` immediately, but the screen
only catches up at the next scheduled or forced refresh. This is deliberate: 4bpp
gray-mode images can't use the panel's fast partial refresh (see
`../wifi_counter_eink/README.md`), so every visual change costs a multi-second
full-panel flash. Press **Redraw** on the status page if you want it now.

## Counter history

Every counter change appends a line to `/counter_track.txt` on the card:
`<timestamp>` tab `<+N/-N>` tab `<new value>`, with `TIME_NOT_SET` in place of
the timestamp if the clock has never been set.

The **History** page renders that log as a table, newest first. It reads a
bounded window from the *end* of the file (16 KB, roughly 500 entries) rather
than loading the whole thing -- the log grows without limit and the heap is
shared with the network stack. When entries are older than that window the page
says so and links to **view the whole file**, which streams
`/counter_track.txt` verbatim as plain text at `/history/raw` without ever
holding it in RAM.

### History Plot

Counter value plotted against date, with window buttons for 1 month, 3 months,
6 months, 1 year, and full history (full is the default).

The chart is **server-rendered inline SVG** &mdash; no JavaScript, no charting
library, nothing fetched from a CDN. A local device whose page only works when
the browser has internet access would fail in exactly the situation you'd most
want it.

The log is scanned twice rather than buffered: the first pass counts entries and
finds the axis ranges, the second emits a decimated polyline (capped at 400
points, which is more than a ~900 px wide plot can show anyway). Peak memory
stays flat however large the log grows, which is the same reason the data page
reads only a window from the end.

Entries logged as `TIME_NOT_SET` can't be placed on a time axis, so they're
skipped and the count of them is reported under the chart &mdash; they're still
visible on History Data. A time window is measured back from *now*, so it needs
a valid clock; with an unset clock the page shows everything and says why rather
than silently plotting an empty month.

## Refresh timing and responsiveness

The refresh interval is tracked with `millis()`, not wall-clock time. This
matters more than it sounds: the ESP32 boots at epoch 0 and NTP steps the clock
by decades within seconds of connecting, so an epoch-based deadline computed
before that sync would be instantly overdue afterwards — a refresh storm on
every boot. `millis()` is monotonic and immune to the clock being set.

Web requests never wait for the panel. A handler queues the work and returns
immediately with a 303; `loop()` does the multi-second refresh afterwards. If
several requests arrive close together they collapse into one refresh, with the
most significant action winning (jump > advance > rescan > redraw).

The panel needs about 3 seconds undisturbed after a gray refresh for the
waveform to develop, because Seeed_GFX's 16-gray `update()` is fire-and-forget —
unlike its black-and-white path, it doesn't wait for the panel before sleeping
it. That settle is a timer gate rather than a blocking delay, so the web server
stays fully responsive throughout. The only genuinely unresponsive window is the
~1.5-2 s of the refresh itself.

## Swapping the SD card

**This changed from the previous version — eject before pulling the card.**

The deep-sleep frame kept the card unmounted almost all of the time, so pulling
it was usually safe. This one keeps it mounted continuously, because uploads
arrive at arbitrary moments and span multiple callbacks. Pulling a mounted card
risks FAT corruption.

1. Press **Eject card** on the status page (or `POST /sd/eject`).
2. Wait for the page to say the card is safe to remove.
3. Pull it.
4. After reinserting, press **Mount card**.

The frame keeps displaying the current photo the whole time. With no card,
scheduled refreshes are **skipped silently** and resume once it's back — they
deliberately do *not* draw an error screen, since wiping a perfectly good photo
to announce a missing card is worse than showing a stale one. An error screen
appears only at boot with nothing on screen yet, or when you explicitly ask for
a refresh.

Electrically the Adafruit #4682 breakout is 3.3 V with no level shifting and
SD-over-SPI is routinely hot-swapped — the hazard is filesystem corruption from
mid-write removal, not hardware damage.

## Storage and hardware notes

Images and metadata live on the SD card, read over the card's own SPI host
(`SPIClass(FSPI)` → SPI2_HOST), physically separate from the panel's bus
(SPI3_HOST) so the two never contend — the arrangement proven in
`../eink_sd_test`.

The SD clock runs at **20 MHz** here, up from 4 MHz in the previous version.
That's the highest-leverage constant in the project: it cuts the 1.3 MB image
read on every refresh from roughly 5 s to 1.3 s and speeds uploads by the same
factor. SD-over-SPI is specified to 25 MHz and 20 MHz divides the 80 MHz APB
clock cleanly. If the card starts failing to mount, reading short, or corrupting
writes, step **down** the ladder in `src/frame_config.h`: 20 → 16 → 10 → 4 MHz.
The breakout is jumper-wired, so signal integrity is the plausible failure, not
the card.

This project also targets the `seeed-xiao-esp32-s3-plus` board id rather than
the `-sense` id the sibling projects use. The hardware has always been the Plus
(16 MB flash — see `../hardware_info.md`); the Plus variant header is purely
additive, and it defines `BAT_VOLT_PIN` if battery sensing is ever wired up.

### The partition table trap

`partitions.csv` gives `app0` the subtype **`ota_0`**, not `factory`, and that
is load-bearing rather than cosmetic. PlatformIO's `_update_max_upload_size()`
only lowers the reported size limit for a partition whose subtype is `ota_0`.
With `factory` — as the sibling project uses — the limit stays at the board
JSON's full flash size, so **an over-large firmware builds and flashes
"successfully" and then fails to boot, with no warning at all.** With `ota_0`,
`pio run` reports usage against the real 4 MB partition. Worth knowing, since
this build links the entire WiFi stack.

`app1` is reserved so OTA updates are possible later without re-laying-out the
table — reflashing a wall-mounted frame over USB is miserable. **OTA is not
implemented here**, only the space for it.

## Source layout

Unlike the single-`main.cpp` siblings, this one is split — the firmware is
around 2,000 lines and the upload handling has no business sitting next to the
display code:

```
src/frame_config.h   pins, geometry, constants, shared types
src/storage.{h,cpp}  SD lifecycle, XML helpers, photo/config read+write
src/app.h            the interface web.cpp uses to talk to the main loop
src/web.{h,cpp}      routes, HTML, upload handling
src/main.cpp         setup/loop, refresh state machine, buttons, display, WiFi/NTP
```

`frame_config.h` must be the **first** include in every `.cpp`. It's where
`<FS.h>` gets included before `<TFT_eSPI.h>` — Seeed_GFX's ESP32-S3 processor
header `#define`s `FS_NO_GLOBALS` before including `FS.h`, which suppresses
`using fs::File;`/`using fs::FS;` and breaks both `SD.open()`'s return type and
`WebServer.h`'s unqualified use of `FS`. This project trips both at once. Keeping
the fix in one universally-included header makes it structural rather than a
comment someone can regress by reordering includes.

## Verified vs. unverified

**Verified:** the project builds clean at **26.7% flash (1,118,410 of 4,194,304
bytes) and 15.2% RAM**. The host-side image/metadata pipeline
(`prepare_image.py`) was already verified by the previous project.

**Not yet run on hardware in this configuration.** Check these first:

- **Uploads**, in this order: happy path (and time it), a truncated `.bin`, an
  aborted transfer run *twice* in a row (a leaked file handle won't show on one
  pass), a valid `.xml` paired with a bad `.bin` (neither should land), and
  overwriting the photo currently on screen.
- **No-WiFi boot**: wrong SSID should fail at ~20 s and still display photos,
  honour buttons, and cycle on the timer. Then power the AP on and confirm it
  joins within 60 s without rebooting.
- **Deferred work**: `POST /show` must return in well under 0.5 s with the panel
  changing 2-5 s later, and `/` must stay responsive during the 3 s settle.
- **Counter steps**: each of the ten buttons moves the counter by its own
  amount and logs one line with that step (`+5`, `-3`, ...); `POST /counter`
  with `d=0` or `d=9` is rejected with a 400.
- **History Plot**: the line matches the values on History Data, the window
  buttons narrow the range, and the axis labels read correctly. The plot
  geometry (bounds, axis inversion, decimation, flat-value and single-timestamp
  edge cases) was checked off-device, but not the rendered result.
- **Clock**: correct Central time within ~30 s of boot — in summer the offset
  must be **−05:00 (CDT)**, which is what actually tests the DST rules.
- **Card eject/reinsert**, and a scheduled refresh with no card (must skip
  silently, not wipe the screen).
- **`epaper.begin()` once at boot rather than per refresh** is unexercised —
  every refresh used to *be* a boot out of deep sleep. If the first refresh
  renders correctly but later ones are blank or ghosted, move `begin(1)` (the
  `initFromSleep` path) into `performRefresh()`.
- **Long-awake gray refreshes** are the biggest genuine unknown. The previous
  version never did more than one gray refresh per power cycle; this does 12+ a
  day with the panel continuously awake, and the driver pushes a hardcoded 16 °C
  for waveform selection every wake. Soak it for 24-48 h at a 1-hour interval
  and watch for accumulating ghosting, alongside `ESP.getMinFreeHeap()` for
  leaks and the WiFi reconnect count.
- **20 MHz SD** stability, per the ladder above.
