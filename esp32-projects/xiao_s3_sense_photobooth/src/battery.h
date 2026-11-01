#pragma once

#include "booth_config.h"

// -----------------------------------------------------------------------------
// Battery log: the LiPo's voltage on A0 (through the round display's divider;
// the KE switch must route it), one CSV row per event, kept in the internal
// flash (LittleFS) so it survives the battery dying. New rows are pushed to
// the eink_photo_server (POST /sources/<id>/battery, see upload.cpp), where
// they can be charted.
//
// Rows: epoch,local_time,boot,uptime_s,event,a0_mv,battery_mv
// Events: boot, wake, sleep, upload, and "timer" every BATTERY_LOG_INTERVAL_S
// while asleep (the booth wakes briefly from light sleep just for that).
//
// A fresh log -- new id, empty file -- starts whenever BATTERY_LOG_GENERATION
// in booth_config.h differs from the one the board last ran, so bumping it in
// a flash clears the log. Everything runs in the loop() task.
// -----------------------------------------------------------------------------

void setupBattery();                   // mounts LittleFS, starts/clears the log, logs "boot"
void logBattery(const char *event);    // appends one row (measures A0 now)
uint32_t msUntilBatterySample();       // for the light-sleep timer
// Called after every sleep/wake cycle and loop pass while asleep: logs a
// "timer" row when one is due. Returns true if a log upload is due too.
bool serviceBatteryTimer();

// For the uploader.
String batteryLogId();
size_t batteryLogSize();
size_t batteryLogSent();
void setBatteryLogSent(size_t bytes);
// Reads up to `max` bytes of the log from `offset`; returns how many.
size_t readBatteryLog(size_t offset, uint8_t *buf, size_t max);
void markBatteryLogPushed(); // resets the BATTERY_UPLOAD_INTERVAL_S clock
