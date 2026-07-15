#include <Arduino.h>
#include <TFT_eSPI.h>

#include "image_data.h"

#ifdef EPAPER_ENABLE
EPaper epaper;
#endif

// Same button pins as ../ee03-text-test/src/main.cpp -- wired to the EE03
// kit's built-in buttons.
constexpr int BUTTON_1 = 2;
constexpr int BUTTON_2 = 3;

int currentImage = -1;

void showImage(int index)
{
#ifdef EPAPER_ENABLE
    if (index == currentImage)
    {
        return;
    }

    currentImage = index;

    Serial.print("Pushing image ");
    Serial.println(index + 1);

    epaper.pushImage(
        0, 0,
        IMAGE_WIDTH, IMAGE_HEIGHT,
        (uint16_t *)IMAGES[index]
    );
    epaper.update();
#endif
}

void setup()
{
    Serial.begin(115200);
    delay(1000);

    pinMode(BUTTON_1, INPUT_PULLUP);
    pinMode(BUTTON_2, INPUT_PULLUP);

#ifdef EPAPER_ENABLE
    Serial.println("Initializing EE03 display...");
    epaper.begin();
    epaper.fillScreen(TFT_WHITE);
    epaper.update();

    epaper.initGrayMode(GRAY_LEVEL16);

    showImage(0);
#else
    Serial.println("EPAPER_ENABLE is not defined.");
#endif
}

void loop()
{
    if (digitalRead(BUTTON_1) == LOW)
    {
        Serial.println("Button 1 pressed");
        showImage(0);

        while (digitalRead(BUTTON_1) == LOW)
        {
            delay(10);
        }
    }

    if (digitalRead(BUTTON_2) == LOW)
    {
        Serial.println("Button 2 pressed");
        showImage(1);

        while (digitalRead(BUTTON_2) == LOW)
        {
            delay(10);
        }
    }

    delay(20);
}
