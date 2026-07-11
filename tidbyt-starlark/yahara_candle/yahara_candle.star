load("render.star", "render")
load("http.star", "http")
load("encoding/json.star", "json")

SITE = "05427948"
PARAMETER = "00010"  # 00010 water temp, 00065 gage height, 00060 discharge

CHART_TOP = 2
CHART_BOTTOM = 29
CANDLE_X = 3
BODY_WIDTH = 5

BODY_HOURS = 12
WICK_DAYS = 7
YEAR_DAYS = 365


GREEN = "#00ff66"
RED = "#ff3333"
WHITE = "#ffffff"
GRAY = "#777777"
BG = "#000000"


def usgs_iv(period):
    url = "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=%s&parameterCd=%s&period=%s&siteStatus=all" % (
        SITE,
        PARAMETER,
        period,
    )
    return json.decode(http.get(url).body())


def usgs_dv():
    # statCd 00001 = daily max, 00002 = daily min
    url = "https://waterservices.usgs.gov/nwis/dv/?format=json&sites=%s&parameterCd=%s&period=P%dD&statCd=00001,00002&siteStatus=all" % (
        SITE,
        PARAMETER,
        YEAR_DAYS,
    )
    return json.decode(http.get(url).body())

def values_from_timeseries(data):
    out = []
    series_list = data["value"]["timeSeries"]

    for series in series_list:
        blocks = series["values"]
        for block in blocks:
            for item in block["value"]:
                value = item["value"]
                if value != "":
                    out.append(float(value))

    return out

def min_val(vals):
    m = vals[0]
    for v in vals:
        if v < m:
            m = v
    return m


def max_val(vals):
    m = vals[0]
    for v in vals:
        if v > m:
            m = v
    return m


def clamp(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def y_for_value(v, year_min, year_max):
    if year_max <= year_min:
        return 16

    chart_height = CHART_BOTTOM - CHART_TOP
    ratio = (v - year_min) / (year_max - year_min)
    y = CHART_BOTTOM - int(ratio * chart_height)

    return clamp(y, CHART_TOP, CHART_BOTTOM)

def fmt1(v):
    sign = ""
    if v < 0:
        sign = "-"
        v = -v

    scaled = int(v * 10)
    whole = scaled // 10
    frac = scaled % 10

    return "%s%d.%d" % (sign, whole, frac)

def rect(x, y, w, h, color):
    if h < 1:
        h = 1
    if w < 1:
        w = 1

    return render.Box(
        width = 64,
        height = 32,
        child = render.Column(
            cross_align = "start",
            children = [
                render.Box(width = 64, height = y),
                render.Row(
                    cross_align = "start",
                    children = [
                        render.Box(width = x, height = h),
                        render.Box(width = w, height = h, color = color),
                    ],
                ),
            ],
        ),
    )


def main():
    body_data = usgs_iv("PT%dH" % BODY_HOURS)
    wick_data = usgs_iv("P%dD" % WICK_DAYS)
    year_data = usgs_dv()

    body_vals = values_from_timeseries(body_data)
    wick_vals = values_from_timeseries(wick_data)
    year_vals = values_from_timeseries(year_data)

    if len(body_vals) == 0 or len(wick_vals) == 0 or len(year_vals) == 0:
        return render.Root(
            child = render.Text("No USGS data", color = RED),
        )

    current = body_vals[-1]
    start_body = body_vals[0]

    body_low = min_val(body_vals)
    body_high = max_val(body_vals)

    wick_low = min_val(wick_vals)
    wick_high = max_val(wick_vals)

    year_min = min_val(year_vals)
    year_max = max_val(year_vals)

    color = GREEN
    if current < start_body:
        color = RED

    y_current = y_for_value(current, year_min, year_max)
    y_wick_high = y_for_value(wick_high, year_min, year_max)
    y_wick_low = y_for_value(wick_low, year_min, year_max)

    candle_x = 1
    wick_x = candle_x + 2
    marker_x = candle_x + 1

    body_y = y_wick_high
    body_h = y_wick_low - y_wick_high + 1

    color = GREEN
    if current < start_body:
        color = RED

    cur_text = fmt1(current)

    text_y = y_current - 3
    if text_y < 0:
        text_y = 0
    if text_y > 25:
        text_y = 25

    return render.Root(
        child = render.Stack(
            children = [
                render.Box(width = 64, height = 32, color = BG),

                # 1-year min/max bars
                rect(candle_x, CHART_TOP, 5, 1, WHITE),
                rect(candle_x, CHART_BOTTOM, 5, 1, WHITE),

                # 7-day body, full solid block
                rect(candle_x, body_y, 5, body_h, color),

                # Center wick drawn on top so it remains visible
                rect(wick_x, y_wick_high, 1, y_wick_low - y_wick_high + 1, GRAY),

                # Current value marker
                rect(marker_x, y_current, 3, 1, WHITE),

                # Current value text
                render.Column(
                    cross_align = "start",
                    children = [
                        render.Box(width = 64, height = text_y),
                        render.Row(
                            children = [
                                render.Box(width = 8, height = 6),
                                render.Text(cur_text, font = "tom-thumb", color = WHITE),
                            ],
                        ),
                    ],
                ),
            ],
        ),
    )