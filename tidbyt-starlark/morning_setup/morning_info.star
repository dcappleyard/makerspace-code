load("render.star", "render")
load("http.star", "http")
load("time.star", "time")

LAT = "43.0731"
LON = "-89.4012"
TIMEZONE = "America/Chicago"

# Set to True for °C, False for °F
USE_CELSIUS = False

# Weather target time for tomorrow morning, 24-hour format
TARGET_HOUR = 6

def bus_icon():
    return render.Box(
        width = 16,
        height = 13,
        child = render.Column(
            cross_align = "center",
            children = [
                render.Box(width = 12, height = 1, color = "#fff"),
                render.Box(width = 14, height = 1, color = "#fff"),

                render.Row(children = [
                    render.Box(width = 3, height = 3, color = "#fff"),
                    render.Box(width = 1, height = 3, color = "#000"),
                    render.Box(width = 3, height = 3, color = "#fff"),
                    render.Box(width = 1, height = 3, color = "#000"),
                    render.Box(width = 3, height = 3, color = "#fff"),
                ]),

                render.Box(width = 14, height = 3, color = "#fff"),

                render.Row(children = [
                    render.Box(width = 3, height = 2, color = "#fff"),
                    render.Box(width = 6, height = 2, color = "#000"),
                    render.Box(width = 3, height = 2, color = "#fff"),
                ]),

                render.Row(children = [
                    render.Box(width = 3, height = 2, color = "#000"),
                    render.Box(width = 2, height = 2, color = "#fff"),
                    render.Box(width = 6, height = 2, color = "#000"),
                    render.Box(width = 2, height = 2, color = "#fff"),
                    render.Box(width = 3, height = 2, color = "#000"),
                ]),
            ],
        ),
    )

def apple_icon():
    return render.Box(
        width = 16,
        height = 13,
        child = render.Column(
            cross_align = "center",
            children = [
                render.Row(children = [
                    render.Box(width = 6, height = 1, color = "#000"),
                    render.Box(width = 2, height = 1, color = "#fff"),
                    render.Box(width = 8, height = 1, color = "#000"),
                ]),

                render.Row(children = [
                    render.Box(width = 7, height = 1, color = "#000"),
                    render.Box(width = 1, height = 1, color = "#fff"),
                    render.Box(width = 1, height = 1, color = "#000"),
                    render.Box(width = 3, height = 1, color = "#fff"),
                    render.Box(width = 4, height = 1, color = "#000"),
                ]),

                render.Box(width = 8, height = 1, color = "#fff"),
                render.Box(width = 12, height = 1, color = "#fff"),
                render.Box(width = 14, height = 5, color = "#fff"),
                render.Box(width = 12, height = 1, color = "#fff"),
                render.Box(width = 10, height = 1, color = "#fff"),
                render.Box(width = 6, height = 1, color = "#fff"),
            ],
        ),
    )

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
    hour_str = str(TARGET_HOUR)

    if TARGET_HOUR < 10:
        hour_str = "0" + hour_str

    target = _tomorrow_date() + "T" + hour_str + ":00"

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
                        # apple_icon(),

                        # render.Box(width = 4),

                        render.Text(
                            content = weather,
                            font = "6x13",
                        ),
                    ],
                ),
            ],
        )
    )
