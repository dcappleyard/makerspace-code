#pragma once

#include "cam_config.h"

#include <functional>

// -----------------------------------------------------------------------------
// LiPo on the round display: voltage on A0 (through the display's divider),
// an estimated %, whether a USB host is attached, and a discharge logger for
// building calibration curves.
//
// Logs go to the internal flash (LittleFS on the board's otherwise unused
// "spiffs" partition), not the SD card: they must survive the battery dying,
// with or without a card. Each sample is appended and closed immediately.
//
// serviceBattery() runs in loop(); the web handlers (another task) call the
// rest. One mutex covers the shared state and the filesystem.
// -----------------------------------------------------------------------------

void setupBattery();
void serviceBattery();

struct BatteryReading
{
    bool valid;   // false: A0 reads ~0 (no battery, or the KE switch isn't routing it)
    int a0Mv;     // measured at the pin
    int batteryMv; // a0Mv * BATTERY_DIVIDER -- an estimate, the ratio is assumed
    int percent;  // from the calibration table; -1 when !valid
    bool usbHost; // a USB *host* is sending frames; a power-only charger reads false
};
BatteryReading batteryNow();

// Everything the page's battery panel needs: live reading, calibration,
// logger state, and the list of runs.
String batteryJson();

bool startBatteryLog(uint32_t intervalS, String &runName);
void stopBatteryLog();

bool validRunName(const String &name);
bool readRun(const String &name, const std::function<bool(const uint8_t *, size_t)> &sink);
bool deleteRun(const String &name); // refuses the run being logged

// 11 A0 millivolt values for 100%, 90%, ... 0% (non-increasing), and where
// they came from (a run name, for display).
bool setCalibration(const int *mv11, const String &source);
void resetCalibration();
