# wifi_counter_eink

A browser-controlled counter on the EE03 10.3" e-paper panel -- a learning
project for ESP32 WiFi and basic web-server security, more than a
polished tool. Same board/display as `../ee03-text-test` and
`../test_bw_image_eink` -- see `../hardware_info.md`.

## Setup

1. Copy `include/secrets.h.example` to `include/secrets.h` and fill in
   your real WiFi SSID/password. `include/secrets.h` is gitignored --
   never commit the real one (see Security below for why).
2. Build/upload with PlatformIO (`pio run -t upload`, or the VS Code
   PlatformIO extension).
3. Open the serial monitor to see the assigned IP address, or try
   `http://wifi-counter.local/` if your network/OS supports mDNS.
4. Visit that address in a browser. The page shows the current count and
   two buttons; each POSTs to the ESP32, which updates the counter,
   persists it, and redraws just that region of the e-paper panel.

## Design notes

- **Plain black/white rendering, no gray mode.** `EPaper::updataPartial()`
  (fast, region-scoped refresh) reads the sprite's backing buffer
  assuming 1-bit-per-pixel packing. Gray mode (`initGrayMode()`, used by
  `../test_bw_image_eink`) switches the buffer to 4 bits/pixel, and
  `updataPartial()` has no check for that -- mixing the two would misread
  the buffer. The vendored
  `Seeed_GFX/examples/ePaper/Partial/HelloWorld/HelloWorld.ino` confirms
  partial refresh is only ever used in plain mode, which is what this
  project follows.
- **One full `epaper.update()` at boot, `updataPartial()` after that.**
  Matches the HelloWorld example's pattern: draw the initial screen, one
  full refresh to establish a baseline, then scope all further redraws
  to just the changed rectangle.
- The counter's redraw rectangle (`COUNTER_X`/`COUNTER_W` in
  `src/main.cpp`) is kept 8px-aligned, since `updataPartial()` internally
  aligns to 8px boundaries and would otherwise silently redraw a
  slightly wider strip than requested.
- Counter value persists across reboots via `Preferences` (NVS), opened
  and closed per write rather than held open, so each change is flushed
  immediately instead of risking loss if power is cut before some later
  `end()` call.

## Security

This is a deliberate teaching exercise in ESP32 WiFi/web basics, not
production IoT code. Here's what this project actually does, and why:

- **Credentials out of git.** WiFi SSID/password live in
  `include/secrets.h`, gitignored; `include/secrets.h.example` is the
  committed template. This is the first project in this repo that needs
  a secrets convention -- reuse this same split (real file gitignored,
  `.example` committed) for future WiFi projects here.
- **No authentication on the web server -- and what that actually
  means.** Anyone who can reach the ESP32's IP on the same WiFi network
  can view and change the counter; there's no login, token, or API key
  anywhere in this code. That's an acceptable simplification for a
  single-user home-LAN learning project, but it's worth being honest
  about: if this exact pattern were reused for something that actually
  mattered (a lock, an actuator, anything with real consequences), the
  lack of auth would be a real problem, not a theoretical one. The easy
  next step is `server.authenticate(user, pass)` (HTTP Basic Auth)
  guarding the state-changing routes.
- **Plain HTTP, no TLS.** All traffic (and any auth credentials, if you
  add Basic Auth later) travels unencrypted. That's a reasonable
  trade-off on a trusted home LAN, where the realistic threat model is
  "other devices on my own network" -- it becomes actively bad the
  moment this device is reachable from the public internet. **Don't
  port-forward this to the internet as-is.**
- **Why `/increment` and `/decrement` are POST-only (and reject GET with
  405).** Browsers, link-preview generators, and crawlers all issue
  unsolicited GET requests as a matter of routine -- something as
  mundane as a chat app generating a link preview, or a security scanner
  probing the LAN, could silently trigger a GET request. If incrementing
  were a GET route, that alone could change the counter with no user
  intent involved. Gating state changes behind POST closes that specific
  hole. It is *not* full CSRF protection, though -- a malicious page
  could still auto-submit a same-origin POST form without your consent.
  On a closed LAN with no authentication that's treated as out of scope
  here, but it's the natural next thing to explore (CSRF tokens,
  `SameSite` cookies) if this pattern gets reused for something less
  trivial than a counter.
- **mDNS discoverability.** `wifi-counter.local` makes the device easy
  for *you* to find on the LAN -- it's equally easy for anything else on
  the network to find. Minor on a home network, but another reason not
  to expose this beyond the LAN.

## Verified vs. unverified

- **Unverified / to confirm on hardware**: whether one full refresh at
  boot is enough, or whether repeated `updataPartial()` calls need an
  occasional full refresh to clear ghosting. That's a general e-paper
  characteristic, not something confirmed for this specific ED103TC2
  panel from source alone -- tune the cadence once you've watched it
  respond to real button presses over time.
- **Verified**: the project builds clean (`pio run`) at 30.5% flash /
  15% RAM -- WiFi + WebServer + Preferences + ESPmDNS add negligible
  size against the ~3.34MB app partition, unlike `../test_bw_image_eink`
  which is close to full from embedded images.
