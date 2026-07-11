load("render.star", "render")
load("http.star", "http")
load("time.star", "time")

LAT = "43.0731"
LON = "-89.4012"
TIMEZONE = "America/Chicago"

# Set to True for °C, False for °F
USE_CELSIUS = False

# Weather target time for tomorrow morning, 24-hour format
TARGET_HOUR = 7

BUS_ICON = [
    "0000000000000000",
    "0001111111111000",
    "0011111111111100",
    "0111001001001110",
    "0111111111111110",
    "0110010010010010",
    "0111111111111110",
    "0111111111111110",
    "0011000000001100",
    "0110000000000110",
    "1100000000000011",
    "0001100000011000",
    "0000000000000000",
]

def bitmap_icon(bitmap, pixel_size=1):
    rows = []

    for row in bitmap:
        children = []

        for c in row:
            color = "#FFF" if c == "1" else "#000"

            children.append(
                render.Box(
                    width = pixel_size,
                    height = pixel_size,
                    background = color,
                )
            )

        rows.append(render.Row(children = children))

    return render.Column(children = rows)

def temp_unit():
    if USE_CELSIUS:
        return "celsius"
    return "fahrenheit"

def temp_suffix():
    if USE_CELSIUS:
        return "C"
    return "F"

def _tomorrow_date():
    now = time.now()
    tomorrow = now + time.parse_duration("24h")
    return tomorrow.format("2006-01-02")

def _short_time(iso_time):
    parts = iso_time.split("T")[1].split(":")
    hour = int(parts[0])
    minute = parts[1]

    suffix = "AM"
    if hour >= 12:
        suffix = "PM"

    hour12 = hour % 12
    if hour12 == 0:
        hour12 = 12

    return "{}:{}{}".format(hour12, minute, suffix)

def weather_icon(code):
    if code == 0:
        return "☼"

    if code in [1, 2]:
        return "◐"

    if code == 3:
        return "☁"

    if code in [45, 48]:
        return "≋"

    if code in [51, 53, 55, 61, 63, 65]:
        return "☂"

    if code in [71, 73, 75]:
        return "❄"

    if code >= 95:
        return "⚡"

    return "•"

def _fetch_forecast():
    tomorrow = _tomorrow_date()

    url = (
        "https://api.open-meteo.com/v1/forecast"
        + "?latitude=" + LAT
        + "&longitude=" + LON
        + "&timezone=" + TIMEZONE
        + "&temperature_unit=" + temp_unit()
        + "&daily=sunrise"
        + "&hourly=temperature_2m,weather_code"
        + "&start_date=" + tomorrow
        + "&end_date=" + tomorrow
    )

    resp = http.get(url)
    return resp.json()

def _weather_at_hour(data):
    target = _tomorrow_date() + "T{:02d}:00".format(TARGET_HOUR)

    times = data["hourly"]["time"]
    temps = data["hourly"]["temperature_2m"]
    codes = data["hourly"]["weather_code"]

    for i, t in enumerate(times):
        if t == target:
            temp = int(temps[i] + 0.5)
            icon = weather_icon(codes[i])
            return "{} {}°{}".format(icon, temp, temp_suffix())

    return "• --°{}".format(temp_suffix())

def main(config):
    data = _fetch_forecast()

    sunrise = _short_time(data["daily"]["sunrise"][0])
    weather = _weather_at_hour(data)

    return render.Root(
        child = render.Column(
            main_align = "center",
            cross_align = "center",
            children = [
                render.Text(
                    content = "↑ " + sunrise,
                    font = "6x13",
                ),

                render.Box(height = 4),

                render.Row(
                    main_align = "center",
                    cross_align = "center",
                    children = [
                        bitmap_icon(BUS_ICON),

                        render.Box(width = 4),

                        render.Text(
                            content = weather,
                            font = "6x13",
                        ),
                    ],
                ),
            ],
        )
    )
