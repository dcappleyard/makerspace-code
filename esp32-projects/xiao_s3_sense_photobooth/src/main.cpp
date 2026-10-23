#include "booth_config.h"

#include "booth.h"
#include "rtc_clock.h"
#include "screen.h"
#include "storage.h"

// Everything runs in this one task: the booth state machine (booth.cpp) does
// its own pacing and puts the board into light sleep between uses.

void setup()
{
    Serial.begin(115200);
    delay(1000);

    if (!psramFound())
        Serial.println("No PSRAM found -- check board_build.arduino.memory_type (qio_opi)");
    setupScreen(); // before mountSd() (shared SPI bus) and setupClock() (starts Wire)
    setupClock();  // RTC, plus a one-off NTP sync if secrets.h has WiFi; WiFi is off afterwards
    mountSd();
    setupBooth();
}

void loop() { serviceBooth(); }
