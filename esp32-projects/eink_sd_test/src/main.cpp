#include <Arduino.h>

// Must be included before TFT_eSPI.h -- Seeed_GFX's ESP32-S3 processor header
// (Processors/TFT_eSPI_ESP32_S3.h) does `#define FS_NO_GLOBALS` before pulling
// in FS.h, which suppresses `using fs::File;`/`using fs::FS;` and breaks
// unqualified `File`/`FS` use elsewhere -- including SD.open()'s return type.
// Same fix as ../panorama_photo_frame_w_counter/src/main.cpp.
#include <FS.h>

#include <TFT_eSPI.h>
#include <SPI.h>
#include <SD.h>

// Strain-relief monitor for the "beta-ee03-eink with SD card" build -- see
// ../hardware_info.md. The earlier CMD0/connect failures are root-caused
// (Adafruit breakout's DI/DO pads were wired instead of SI/SO) and fixed, so
// this isn't a signal-integrity experiment anymore: it just re-tests the SD
// card on a fixed interval and shows PASS/FAIL + a check counter on the
// e-ink panel, so a bad connection shows up immediately while the wires get
// strain relief -- no laptop/serial monitor needed to watch it. Not a
// permanent fixture -- stays powered over USB, no deep sleep, re-run via
// reset button.

#ifdef EPAPER_ENABLE
EPaper epaper;
#endif

// SPI1 bus on the EE03 board: shared CLK/MOSI/MISO, dedicated CS per device.
// GPIO40 is a second CS pad on this bus reserved for a font-flash chip
// footprint -- confirmed unpopulated on this board, so it's left untouched
// here (nothing to assert/deassert, no second device to isolate from).
constexpr int SD_SPI_SCLK = 11;
constexpr int SD_SPI_MISO = 12;
constexpr int SD_SPI_MOSI = 13;
constexpr int SD_CS = 39;

SPIClass sdSPI(FSPI);

// Standard operating frequency -- no longer probing for signal-integrity
// issues, so just use the SD library's own normal default.
constexpr uint32_t SD_TEST_FREQUENCY_HZ = 4000000;

constexpr unsigned long TEST_INTERVAL_MS = 15000;

// Region the status block is redrawn into on each check. x and w are kept
// 8px-aligned since EPaper::updataPartial() (Seeed_GFX Extensions/EPaper.cpp)
// 8px-aligns internally and would otherwise silently redraw a slightly wider
// strip than requested -- same convention as ../wifi_counter_eink.
constexpr int STATUS_X = 80;
constexpr int STATUS_Y = 200;
constexpr int STATUS_W = 1700;
constexpr int STATUS_H = 300;

int checkCounter = 0;

struct SdTestResult
{
    bool mounted;
    bool writeReadOk;
    uint64_t cardSizeMB;
    String detail;
};

SdTestResult testSdCard(uint32_t freqHz)
{
    SdTestResult result = {false, false, 0, ""};

    pinMode(SD_CS, OUTPUT);
    digitalWrite(SD_CS, HIGH);

    sdSPI.begin(SD_SPI_SCLK, SD_SPI_MISO, SD_SPI_MOSI, SD_CS);

    if (!SD.begin(SD_CS, sdSPI, freqHz))
    {
        result.detail = "SD.begin() failed -- check wiring/CS pin";
        SD.end();
        sdSPI.end();
        return result;
    }

    uint8_t cardType = SD.cardType();
    if (cardType == CARD_NONE)
    {
        result.detail = "SD.begin() succeeded but cardType() == CARD_NONE -- no card detected";
        SD.end();
        sdSPI.end();
        return result;
    }

    result.mounted = true;
    result.cardSizeMB = SD.cardSize() / (1024 * 1024);

    const char *testPath = "/hwtest.txt";
    String testContents = "eink_sd_test write/read check @ " + String(millis());

    File wf = SD.open(testPath, FILE_WRITE);
    if (!wf)
    {
        result.detail = "Mounted, but failed to open " + String(testPath) + " for write";
        SD.end();
        sdSPI.end();
        return result;
    }
    wf.print(testContents);
    wf.close();

    File rf = SD.open(testPath, FILE_READ);
    if (!rf)
    {
        result.detail = "Mounted, but failed to reopen " + String(testPath) + " for read";
        SD.end();
        sdSPI.end();
        return result;
    }
    String readBack = rf.readString();
    rf.close();

    if (readBack != testContents)
    {
        result.detail = "Write/read mismatch -- wrote \"" + testContents + "\", read \"" + readBack + "\"";
        SD.end();
        sdSPI.end();
        return result;
    }

    result.writeReadOk = true;
    result.detail = "OK";
    SD.end();
    sdSPI.end();
    return result;
}

void printSdResult(const SdTestResult &sdResult)
{
    Serial.printf("--- Check #%d @ %lums ---\n", checkCounter, millis());
    Serial.println(sdResult.mounted ? "SD mount: OK" : "SD mount: FAILED");
    Serial.println(sdResult.writeReadOk ? "SD write/read: PASS" : "SD write/read: FAIL");
    Serial.println("Detail: " + sdResult.detail);
    if (sdResult.mounted)
    {
        Serial.printf("Card size: %llu MB\n", (unsigned long long)sdResult.cardSizeMB);
    }
    Serial.println();
}

// Draws the status block into the sprite buffer only -- does not touch the
// physical panel. Used both for the initial (pre-first-update) draw and as
// the first half of updateStatus() below.
void renderStatusPixels(const SdTestResult &sdResult)
{
#ifdef EPAPER_ENABLE
    epaper.fillRect(STATUS_X, STATUS_Y, STATUS_W, STATUS_H, TFT_WHITE);
    epaper.setTextSize(3);
    epaper.drawString("Check #" + String(checkCounter), STATUS_X, STATUS_Y);

    epaper.setTextSize(2);
    String sdLine = String("SD: ") + (sdResult.writeReadOk ? "PASS" : "FAIL") + " -- " + sdResult.detail;
    epaper.drawString(sdLine, STATUS_X, STATUS_Y + 70);

    if (sdResult.mounted)
    {
        String sizeLine = "Card size: " + String((unsigned long)sdResult.cardSizeMB) + " MB";
        epaper.drawString(sizeLine, STATUS_X, STATUS_Y + 120);
    }
#endif
}

// Redraws the status block and pushes just that region to the panel. Only
// valid to call after the initial full epaper.update() in setup() has
// established a baseline image -- see Seeed_GFX's
// examples/ePaper/Partial/HelloWorld/HelloWorld.ino for the pattern this
// follows (full update() once, updataPartial() for changes after that).
void updateStatus(const SdTestResult &sdResult)
{
#ifdef EPAPER_ENABLE
    renderStatusPixels(sdResult);
    epaper.updataPartial(STATUS_X, STATUS_Y, STATUS_W, STATUS_H);
#endif
}

void setup()
{
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("=== eink_sd_test: strain-relief monitor ===");
    Serial.printf("=== Checking SD every %lus, refreshing e-ink each time ===\n", TEST_INTERVAL_MS / 1000);
    Serial.println();

#ifdef EPAPER_ENABLE
    epaper.begin();
    epaper.fillScreen(TFT_WHITE);
    epaper.setTextColor(TFT_BLACK, TFT_WHITE);
    epaper.setTextSize(4);
    epaper.drawString("eink_sd_test: strain relief monitor", 80, 60);
    epaper.setTextSize(2);
    epaper.drawString("SD card re-checked every 15s while moving wires", 80, 130);
#endif

    checkCounter = 1;
    SdTestResult sdResult = testSdCard(SD_TEST_FREQUENCY_HZ);
    printSdResult(sdResult);
    renderStatusPixels(sdResult);

#ifdef EPAPER_ENABLE
    epaper.update(); // one full refresh at boot -- baseline for partial updates
#endif
}

void loop()
{
    delay(TEST_INTERVAL_MS);

    checkCounter++;
    SdTestResult sdResult = testSdCard(SD_TEST_FREQUENCY_HZ);
    printSdResult(sdResult);
    updateStatus(sdResult);
}
