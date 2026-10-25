#pragma once

#include "booth_config.h"

// Call once at boot, after setupScreen() (which starts Wire).
void setupClock();
bool clockValid();         // system time is set and sane (> CLOCK_SANE_EPOCH)
String timestampForName(); // local "YYYY-MM-DD_HH-MM-SS", or "" if !clockValid()
String formatLocalTime();  // local "YYYY-MM-DD HH:MM:SS TZ", or "not set"

// WiFi, for the boot-time NTP sync and the photo uploader. All no-ops returning
// false when include/secrets.h has no WIFI_SSID.
bool wifiUp();     // STA connect, bounded by WIFI_CONNECT_TIMEOUT_MS; true when connected
void wifiDown();   // disconnect and WIFI_OFF
bool ntpSyncNow(); // with WiFi up: SNTP sync, then write the RTC; true on a sync
// With WiFi up: set the clock (and RTC) from the photo server's HTTP Date header
// (SERVER_URL in secrets.h) -- no NTP or outside access needed.
bool serverTimeSync();
// With WiFi up: serverTimeSync(), else ntpSyncNow().
bool syncClockOnline();
