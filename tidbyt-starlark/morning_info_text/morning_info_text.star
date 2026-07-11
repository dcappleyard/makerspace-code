load("render.star", "render")
load("schema.star", "schema")
load("http.star", "http")
load("time.star", "time")

LAT = "43.0731"
LON = "-89.4012"
TIMEZONE = "America/Chicago"

USE_CELSIUS = False
TARGET_HOUR = 7
DEFAULT_TARGET_HOUR = 7


def get_schema():
    return schema.Schema(
        version = "1",
        fields = [
            schema.Text(
                id = "target_hour",
                name = "Wheather Time",
                desc = " Hour for tomorrow morning's weather, using 24-hour time",
                icon = "user"
            ),
        ],
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

def _forecast_date(target_hour):
    now = time.now()
    current_hour = int(now.format("15"))

    if current_hour < target_hour:
        return now.format("2006-01-02")

    tomorrow = now + time.parse_duration("24h")
    return tomorrow.format("2006-01-02")

def _short_time(iso_time):
    parts = iso_time.split("T")[1].split(":")
    hour = int(parts[0])
    minute = parts[1]

    suffix = " AM"
    if hour >= 12:
        suffix = " PM"

    hour12 = hour % 12
    if hour12 == 0:
        hour12 = 12

    return "{}:{}{}".format(hour12, minute, suffix)

def weather_text(code):
    if code == 0:
        return "Clear"

    if code in [1, 2]:
        return "Pt Cloud"

    if code == 3:
        return "Cloudy"

    if code in [45, 48]:
        return "Fog"

    if code in [51, 53, 55]:
        return "Drizzle"

    if code in [61, 63, 65]:
        return "Rain"

    if code in [71, 73, 75]:
        return "Snow"

    if code in [80, 81, 82]:
        return "Showers"

    if code >= 95:
        return "Storm"

    return "Weather"


def _fetch_forecast(target_hour):
    forecast_date = _forecast_date(target_hour)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        + "?latitude=" + LAT
        + "&longitude=" + LON
        + "&timezone=" + TIMEZONE
        + "&temperature_unit=" + temp_unit()
        + "&daily=sunrise"
        + "&hourly=temperature_2m,weather_code"
        + "&start_date=" + forecast_date
        + "&end_date=" + forecast_date
    )

    resp = http.get(url)
    return resp.json()

def _weather_at_hour(data, target_hour):
    forecast_date = _forecast_date(target_hour)

    hour_str = str(target_hour)
    if target_hour < 10:
        hour_str = "0" + hour_str

    target = forecast_date + "T" + hour_str + ":00"

    times = data["hourly"]["time"]
    temps = data["hourly"]["temperature_2m"]
    codes = data["hourly"]["weather_code"]

    for i, t in enumerate(times):
        if t == target:
            temp = int(temps[i] + 0.5)
            desc = weather_text(codes[i])
            return "{}°{} {}".format(temp, temp_suffix(), desc)

    return "--°{} Weather".format(temp_suffix())


def main(config):
    target_hour = int(config.get("target_hour", DEFAULT_TARGET_HOUR))
    data = _fetch_forecast(target_hour)
    sunrise = _short_time(data["daily"]["sunrise"][0])
    weather = _weather_at_hour(data, target_hour)

    return render.Root(
        child = render.Box(
            width = 64,
            height = 32,

            child = render.Column(
                main_align = "center",
                cross_align = "center",
                children = [
                    render.Text(
                        content = "↑ " + sunrise,
                        font = "tb-8",
                    ),

                    render.Box(height = 2),

                    render.Text(
                        content = weather,
                        font = "tb-8",
                    ),
                ],
            )
        )
    )
