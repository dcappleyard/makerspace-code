#include "power.h"

#include <WiFi.h>
#include <driver/gpio.h>
#include <esp_sleep.h>

RTC_DATA_ATTR RtcState rtc;

namespace
{
constexpr uint32_t RTC_MAGIC = 0xEE040001;

// Resting LiPo voltage -> %, read before WiFi loads the cell.
struct Point
{
    uint16_t mv;
    uint8_t pct;
};
constexpr Point CURVE[] = {
    {4200, 100}, {4110, 90}, {4020, 80}, {3950, 70}, {3870, 60}, {3840, 50},
    {3800, 40},  {3770, 30}, {3730, 20}, {3690, 10}, {3610, 5},  {3300, 0},
};

uint8_t percentFor(uint16_t mv)
{
    if (mv >= CURVE[0].mv)
        return 100;
    for (size_t i = 1; i < sizeof(CURVE) / sizeof(CURVE[0]); i++)
    {
        if (mv >= CURVE[i].mv)
        {
            const Point &hi = CURVE[i - 1], &lo = CURVE[i];
            return lo.pct + (uint32_t)(mv - lo.mv) * (hi.pct - lo.pct) / (hi.mv - lo.mv);
        }
    }
    return 0;
}
} // namespace

bool beginPower()
{
    // Release the pins held through sleep before anything drives them.
    gpio_hold_dis((gpio_num_t)PIN_BAT_ADC_EN);
    gpio_hold_dis((gpio_num_t)TFT_ENABLE);
    gpio_deep_sleep_hold_dis();

    bool timerWake = esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER;
    if (!timerWake || rtc.magic != RTC_MAGIC)
    {
        memset(&rtc, 0, sizeof rtc);
        rtc.magic = RTC_MAGIC;
        timerWake = false;
    }
    else
    {
        rtc.wakes++;
    }
    return timerWake;
}

Battery readBattery()
{
    pinMode(PIN_BAT_ADC_EN, OUTPUT);
    digitalWrite(PIN_BAT_ADC_EN, HIGH);
    delay(10);
    uint32_t sum = 0;
    for (int i = 0; i < 16; i++)
        sum += analogRead(PIN_BAT_ADC);
    digitalWrite(PIN_BAT_ADC_EN, LOW);
    Battery b;
    b.raw = sum / 16;
    b.mv = (uint16_t)(b.raw * BATTERY_SCALE * BATTERY_CAL * 1000.0f + 0.5f);
    b.pct = percentFor(b.mv);
    return b;
}

bool stayAwake(bool timerWake)
{
    if (!timerWake && millis() < BOOT_STAY_AWAKE_MS)
        return true;
    return STAY_AWAKE_ON_USB_HOST && HWCDC::isPlugged();
}

void deepSleep(uint32_t seconds)
{
    Serial.printf("Deep sleep for %lus\n", (unsigned long)seconds);
    Serial.flush();

    WiFi.disconnect(true, false);
    WiFi.mode(WIFI_OFF);

    // Panel controller is already in its own deep sleep after update(); cut its
    // supply too (e-paper keeps the image unpowered). Hold both enables LOW so
    // they don't float on during sleep.
    pinMode(TFT_ENABLE, OUTPUT);
    digitalWrite(TFT_ENABLE, LOW);
    pinMode(PIN_BAT_ADC_EN, OUTPUT);
    digitalWrite(PIN_BAT_ADC_EN, LOW);
    gpio_hold_en((gpio_num_t)TFT_ENABLE);
    gpio_hold_en((gpio_num_t)PIN_BAT_ADC_EN);
    gpio_deep_sleep_hold_en();

    esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);
    esp_deep_sleep_start();
}
