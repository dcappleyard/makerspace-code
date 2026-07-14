#include <Arduino.h>
#include <TFT_eSPI.h>

#ifdef EPAPER_ENABLE
EPaper epaper;
#endif

constexpr int BUTTON_1 = 2;
constexpr int BUTTON_2 = 3;
constexpr int BUTTON_3 = 5;

int currentPage = -1;

void drawHeader(const char* title)
{
    epaper.fillScreen(TFT_WHITE);

    epaper.fillRect(0, 0, epaper.width(), 90, TFT_BLACK);

    epaper.setTextColor(TFT_WHITE, TFT_BLACK);
    epaper.setTextSize(3);
    epaper.drawString(title, 40, 25);

    epaper.setTextColor(TFT_BLACK, TFT_WHITE);
}

void showTextPage()
{
    Serial.println("Drawing text page");

    drawHeader("Page 1: Text");

    epaper.setTextSize(4);
    epaper.drawString("Hello, Dave!", 80, 180);

    epaper.setTextSize(2);
    epaper.drawString(
        "Button-controlled e-paper display",
        80,
        280
    );

    epaper.drawString(
        "Press another button to change pages.",
        80,
        340
    );

    epaper.update();
}

void showGraphicsPage()
{
    Serial.println("Drawing graphics page");

    drawHeader("Page 2: Graphics");

    epaper.drawRect(80, 160, 400, 250, TFT_BLACK);
    epaper.fillRect(550, 160, 400, 250, TFT_BLACK);

    epaper.drawCircle(280, 600, 130, TFT_BLACK);
    epaper.fillCircle(750, 600, 130, TFT_BLACK);

    for (int x = 80; x <= 950; x += 60)
    {
        epaper.drawLine(
            x,
            850,
            x + 200,
            1100,
            TFT_BLACK
        );
    }

    epaper.setTextSize(2);
    epaper.drawString(
        "Rectangles, circles, and lines",
        80,
        1250
    );

    epaper.update();
}

void showFramePlaceholder()
{
    Serial.println("Drawing picture-frame placeholder");

    drawHeader("Page 3: Picture Frame");

    constexpr int margin = 100;
    constexpr int imageTop = 160;

    const int imageWidth = epaper.width() - (margin * 2);
    const int imageHeight = epaper.height() - imageTop - 250;

    epaper.drawRect(
        margin,
        imageTop,
        imageWidth,
        imageHeight,
        TFT_BLACK
    );

    // Simple mountain-like placeholder.
    epaper.drawLine(
        margin,
        imageTop + imageHeight,
        margin + imageWidth / 3,
        imageTop + imageHeight / 2,
        TFT_BLACK
    );

    epaper.drawLine(
        margin + imageWidth / 3,
        imageTop + imageHeight / 2,
        margin + imageWidth / 2,
        imageTop + imageHeight * 3 / 4,
        TFT_BLACK
    );

    epaper.drawLine(
        margin + imageWidth / 2,
        imageTop + imageHeight * 3 / 4,
        margin + imageWidth * 3 / 4,
        imageTop + imageHeight / 3,
        TFT_BLACK
    );

    epaper.drawLine(
        margin + imageWidth * 3 / 4,
        imageTop + imageHeight / 3,
        margin + imageWidth,
        imageTop + imageHeight,
        TFT_BLACK
    );

    epaper.fillCircle(
        margin + imageWidth - 150,
        imageTop + 150,
        60,
        TFT_BLACK
    );

    epaper.setTextSize(2);
    epaper.drawString(
        "Future photograph goes here",
        margin,
        epaper.height() - 150
    );

    epaper.update();
}

void changePage(int page)
{
    if (page == currentPage)
    {
        return;
    }

    currentPage = page;

    switch (page)
    {
        case 1:
            showTextPage();
            break;

        case 2:
            showGraphicsPage();
            break;

        case 3:
            showFramePlaceholder();
            break;
    }
}

void setup()
{
    Serial.begin(115200);
    delay(1000);

    pinMode(BUTTON_1, INPUT_PULLUP);
    pinMode(BUTTON_2, INPUT_PULLUP);
    pinMode(BUTTON_3, INPUT_PULLUP);

#ifdef EPAPER_ENABLE
    Serial.println("Initializing EE03 display...");
    epaper.begin();

    changePage(1);
#else
    Serial.println("EPAPER_ENABLE is not defined.");
#endif
}

void loop()
{
    if (digitalRead(BUTTON_1) == LOW)
    {
        Serial.println("Button 1 pressed");
        changePage(1);

        while (digitalRead(BUTTON_1) == LOW)
        {
            delay(10);
        }
    }

    if (digitalRead(BUTTON_2) == LOW)
    {
        Serial.println("Button 2 pressed");
        changePage(2);

        while (digitalRead(BUTTON_2) == LOW)
        {
            delay(10);
        }
    }

    if (digitalRead(BUTTON_3) == LOW)
    {
        Serial.println("Button 3 pressed");
        changePage(3);

        while (digitalRead(BUTTON_3) == LOW)
        {
            delay(10);
        }
    }

    delay(20);
}