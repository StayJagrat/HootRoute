"""Polyline helpers on [lon, lat] coordinates. Equirectangular metres, fine at city scale. Mirrors streetwise-web/src/lib/geo.ts."""
import math

KY = 110_540.0


def _kx(lat): return math.cos(math.radians(lat)) * 111_320.0


def distance(a, b):
    kx = _kx((a[1] + b[1]) / 2); return math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * KY)


def cumulative(line):
    out = [0.0]
    for i in range(1, len(line)): out.append(out[-1] + distance(line[i - 1], line[i]))
    return out


def length(line): return cumulative(line)[-1] if line else 0.0


def project(line, p, cum=None):
    """(metres along `line` of the closest point to `p`, distance from `p` to the line in metres)."""
    cum = cum or cumulative(line); kx = _kx(p[1]); best = (0.0, math.inf)
    px, py = p[0] * kx, p[1] * KY
    for i in range(1, len(line)):
        ax, ay = line[i - 1][0] * kx, line[i - 1][1] * KY; bx, by = line[i][0] * kx, line[i][1] * KY
        dx, dy = bx - ax, by - ay; L = dx * dx + dy * dy or 1.0
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
        off = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if off < best[1]: best = (cum[i - 1] + t * math.sqrt(L), off)
    return best


def point_at(line, meters, cum=None):
    cum = cum or cumulative(line); m = max(0.0, min(cum[-1], meters)); i = 1
    while i < len(cum) - 1 and cum[i] < m: i += 1
    seg = (cum[i] - cum[i - 1]) or 1.0; t = (m - cum[i - 1]) / seg; a, b = line[i - 1], line[i]
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
