# Setting the board's clock

There's no WiFi/NTP and no external RTC module on this project (see `DESIGN.md`) —
the internal ESP32 clock is set manually over serial, on a bounded window at every
cold boot. It survives deep sleep but not a real power loss (unplugging, dead
battery), so you'll need to repeat this after either.

1. Get the current Unix timestamp in one terminal tab:
   ```
   date +%s
   ```
2. Find the board's current serial port (the name can shift between resets/replugs):
   ```
   pio device list
   ```
   Look for the entry described as `USB JTAG/serial debug unit` (e.g.
   `/dev/cu.usbmodem101`) — **not** `/dev/cu.Bluetooth-Incoming-Port` or
   `/dev/cu.debug-console`, which are unrelated virtual ports and will silently
   swallow anything you type if `pio device monitor` defaults to one of them.
3. Open the monitor pointed at that exact port:
   ```
   pio device monitor --port /dev/cu.usbmodem101
   ```
   (substitute whatever `pio device list` showed)
4. Press the board's **reset** button to trigger a fresh cold boot — this is what
   opens the time-set window; a deep-sleep timer/button wake skips it entirely.
5. Within the window (currently 2 minutes — see `TIME_SET_WINDOW_MS` in
   `src/main.cpp`), paste the number from step 1 and press Enter.
6. You should see `Clock set.` printed back.
7. To leave the monitor: `Ctrl+C`. You don't need the monitor's menu (`Ctrl+T`) for
   any of this.

The timestamp will be a few seconds stale by the time you paste it (typing/copy
delay) — that's fine for this use case.
