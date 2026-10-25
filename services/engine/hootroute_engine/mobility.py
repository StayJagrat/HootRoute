"""Travel profiles and OSM restrictions. Missing accessibility tags remain unknown."""
from dataclasses import dataclass
import hashlib
import json
import math
import re


MODES = ("walk", "cycle", "wheelchair")
LABELS = {"walk": "Walking", "cycle": "Cycling", "wheelchair": "Wheelchair / step-free"}
ROUGH = {"unpaved", "gravel", "fine_gravel", "dirt", "earth", "ground", "sand", "mud", "grass", "cobblestone", "sett", "pebblestone", "woodchips", "rock"}
DENIED = {"no", "private", "customers", "permit"}


def incline_pct(value):
    text = str(value or "").strip()
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(%|°|deg)?", text)
    if not match: return None  # 'up', 'down' and 'steep' do not provide a measured gradient
    number = float(match[1])
    return abs(math.tan(math.radians(number)) * 100) if match[2] in {"°", "deg"} else abs(number)


def metres(value):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(m|cm|ft|in)?\s*", str(value or ""))
    if not match: return None
    return float(match[1]) * {None: 1, "m": 1, "cm": .01, "ft": .3048, "in": .0254}[match[2]]


def cycle_lane(tags):
    return tags.get("highway") == "cycleway" or any(
        part in {"lane", "track", "opposite_lane", "opposite_track"}
        for key in ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both")
        for part in str(tags.get(key, "")).split(";"))


@dataclass(frozen=True)
class TravelProfile:
    mode: str = "walk"
    speed_kmh: float = 4.86
    prefer_cycleways: bool = False
    avoid_rough: bool = False
    require_known_access: bool = False
    max_incline_pct: float = 5.0

    @property
    def speed(self): return self.speed_kmh / 3.6

    @property
    def options(self):
        if self.mode == "walk": return {}
        common = {"speedKmh": self.speed_kmh, "avoidRoughSurfaces": self.avoid_rough}
        return {**common, **({"preferCycleways": self.prefer_cycleways} if self.mode == "cycle" else
                            {"requireKnownAccess": self.require_known_access, "maxInclinePct": self.max_incline_pct})}

    @property
    def key(self):
        if self.mode == "walk": return "walk"
        return self.mode + "_" + hashlib.sha256(json.dumps(self.options, sort_keys=True).encode()).hexdigest()[:12]

    def summary(self):
        return {"mode": self.mode, "label": LABELS[self.mode], "speedMps": self.speed, "options": self.options}


def travel_profile(mode="walk", options=None):
    if mode not in MODES: raise ValueError("Choose walking, cycling, or wheelchair / step-free.")
    if mode == "walk": return TravelProfile()
    options = options or {}
    supplied_speed = options.get("speedKmh")
    speed = float((15 if mode == "cycle" else 3) if supplied_speed is None else supplied_speed)
    low, high = (3, 30) if mode == "cycle" else (1, 8)
    slope = float(options.get("maxInclinePct", 5))
    if not math.isfinite(speed) or not low <= speed <= high: raise ValueError(f"Estimated pace must be between {low} and {high} km/h for this mode.")
    if not math.isfinite(slope) or not 0 <= slope <= 15: raise ValueError("Maximum mapped incline must be between 0 and 15 percent.")
    return TravelProfile(mode, speed, bool(options.get("preferCycleways", True)) if mode == "cycle" else False,
                         bool(options.get("avoidRoughSurfaces", mode == "wheelchair")),
                         bool(options.get("requireKnownAccess", False)) if mode == "wheelchair" else False, slope)


def allows(tags, profile):
    hw = tags.get("highway", "")
    if hw in {"motorway", "motorway_link", "trunk", "trunk_link", "construction", "proposed"}: return False
    permission = tags.get("bicycle" if profile.mode == "cycle" else "foot", tags.get("access"))
    if permission in DENIED: return False
    if profile.mode == "walk": return True
    if hw == "steps": return False
    if profile.mode == "cycle":
        if permission in {"dismount", "use_sidepath"}: return False
        if hw in {"footway", "pedestrian", "path"} and permission not in {"yes", "designated", "permissive"}: return False
    else:
        if tags.get("wheelchair") in {"no", "limited"}: return False
        if profile.require_known_access and tags.get("wheelchair") not in {"yes", "designated"}: return False
        slope = incline_pct(tags.get("incline"))
        if slope is not None and slope > profile.max_incline_pct: return False
        if tags.get("incline") == "steep": return False
        width = metres(tags.get("width"))
        if width is not None and width < .9: return False
        kerb = metres(tags.get("kerb:height"))
        if kerb is not None and kerb > .03: return False
        if tags.get("kerb") == "raised" and kerb is None: return False
        if tags.get("smoothness") in {"bad", "very_bad", "horrible", "very_horrible", "impassable"}: return False
    if profile.avoid_rough and tags.get("surface") in ROUGH: return False
    return True


def directions(tags, profile):
    """Permitted directions along an OSM way: +1 follows its node order."""
    if profile.mode != "cycle": return (1, -1)
    one = tags.get("oneway:bicycle", tags.get("oneway", "yes" if tags.get("junction") == "roundabout" else "no"))
    if "oneway:bicycle" not in tags and any(str(tags.get(k, "")).startswith("opposite") for k in ("cycleway", "cycleway:left", "cycleway:right")):
        one = "no"
    result = (-1,) if one == "-1" else (1,) if one in {"yes", "1", "true"} else (1, -1)
    return tuple(d for d in result if tags.get("bicycle:forward" if d == 1 else "bicycle:backward") not in DENIED)
