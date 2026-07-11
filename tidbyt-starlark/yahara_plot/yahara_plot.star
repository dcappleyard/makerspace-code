load("render.star", "render")
load("http.star", "http")
load("encoding/json.star", "json")

# Yahara river at East Main
SITE_28500 = "05428500"

# Lake Monona
SITE_29000 = "05429000"

PARAM_TEMP = "00010"
PARAM_DISCHARGE = "00060"
PARAM_GAGE = "00065"

RED = "#ff0000"
BLUE = "#0000ff"
TEAL = "#00ffff"
WHITE = "#ffffff"
BLACK = "#000000"

def fetch_iv_7d(site, params):
    url = "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=%s&parameterCd=%s&period=P7D&siteStatus=all" % (
        site,
        params,
    )
    return json.decode(http.get(url).body())

def fmt1(v):
    scaled = int(v * 10 + 0.5)
    return "%d.%d" % (scaled // 10, scaled % 10)

def fmt0(v):
    return "%d" % int(v + 0.5)

def normalize_series(points):
    if len(points) == 0:
        return []

    ymin = points[0][1]
    ymax = points[0][1]

    for p in points:
        if p[1] < ymin:
            ymin = p[1]
        if p[1] > ymax:
            ymax = p[1]

    if ymax <= ymin:
        out = []
        for i in range(len(points)):
            out.append((points[i][0], 0.0))
        return out

    out = []
    for p in points:
        out.append((p[0], (p[1] - ymin) / (ymax - ymin)))

    return out

def extract_series_raw(data, parameter_code):
    series_list = data["value"]["timeSeries"]

    for series in series_list:
        code = series["variable"]["variableCode"][0]["value"]
        if code == parameter_code:
            values = series["values"][0]["value"]

            points = []
            n = len(values)

            # Downsample to about 64 points per line.
            step = n // 64
            if step < 1:
                step = 1

            x = 0.0
            for i in range(0, n, step):
                raw = values[i]["value"]
                if raw != "":
                    points.append((x, float(raw)))
                    x = x + 1.0

            return points

    return []

def latest_value(points):
    if len(points) == 0:
        return None
    return points[len(points) - 1][1]

def make_plot(points, color):
    if len(points) < 2:
        points = [(0.0, 0.0), (1.0, 0.0)]

    norm = normalize_series(points)
    xmax = float(len(norm) - 1)

    return render.Plot(
        data = norm,
        width = 64,
        height = 24,
        color = color,
        x_lim = (0.0, xmax),
        y_lim = (0.0, 1.0),
    )

def main():
    data_28500 = fetch_iv_7d(SITE_28500, PARAM_GAGE + "," + PARAM_DISCHARGE)
    data_29000 = fetch_iv_7d(SITE_29000, PARAM_GAGE + "," + PARAM_TEMP)

    gage_28500 = extract_series_raw(data_28500, PARAM_GAGE)
    discharge_28500 = extract_series_raw(data_28500, PARAM_DISCHARGE)

    #gage_29000 = extract_series_raw(data_29000, PARAM_GAGE)
    temp_29000 = extract_series_raw(data_29000, PARAM_TEMP)

    g285_now = latest_value(gage_28500)
    q285_now = latest_value(discharge_28500)
    #g290_now = latest_value(gage_29000)
    t290_now = latest_value(temp_29000)

    g285_txt = "--f"
    q285_txt = "--c"
    #g290_txt = "--f"
    t290_txt = "--C"

    if g285_now != None:
        g285_txt = fmt1(g285_now) + "f"
    if q285_now != None:
        q285_txt = fmt0(q285_now) + "c"
    #if g290_now != None:
    #    g290_txt = fmt1(g290_now) + "f"
    if t290_now != None:
        t290_txt = fmt1(t290_now) + "C"

    return render.Root(
        child = render.Box(
            width = 64,
            height = 32,
            color = BLACK,
            child = render.Column(
                children = [
                    render.Row(
                        children = [
                            render.Text(t290_txt, font = "tom-thumb", color = RED),
                            render.Text(" ", font = "tom-thumb", color = WHITE),
                            render.Text(q285_txt, font = "tom-thumb", color = WHITE),
                            render.Text(" ", font = "tom-thumb", color = WHITE),
                            render.Text(g285_txt, font = "tom-thumb", color = BLUE),
     #                       render.Text(" ", font = "tom-thumb", color = WHITE),
      #                      render.Text(g290_txt, font = "tom-thumb", color = BLUE),
                        ],
                    ),
                    render.Stack(
                        children = [
                            make_plot(gage_28500, BLUE),
                            make_plot(discharge_28500, WHITE),
       #                     make_plot(gage_29000, BLUE),
                            make_plot(temp_29000, RED),
                        ],
                    ),
                ],
            ),
        ),
    )