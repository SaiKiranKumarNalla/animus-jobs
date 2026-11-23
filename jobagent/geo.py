"""Offline geocoder: location strings -> (lat, lon, label). Cities first, then countries."""
import re

CITIES = {
    # France
    "paris": (48.86, 2.35), "toulouse": (43.60, 1.44), "lyon": (45.76, 4.84), "marseille": (43.30, 5.37),
    "grenoble": (45.19, 5.72), "bordeaux": (44.84, -0.58), "nantes": (47.22, -1.55), "lille": (50.63, 3.06),
    "strasbourg": (48.57, 7.75), "montpellier": (43.61, 3.88), "nice": (43.70, 7.27), "rennes": (48.11, -1.68),
    "suresnes": (48.87, 2.23), "saclay": (48.73, 2.17), "sophia antipolis": (43.62, 7.05), "orsay": (48.70, 2.19),
    "boulogne": (48.84, 2.24), "île-de-france": (48.85, 2.35), "ile-de-france": (48.85, 2.35),
    # Europe
    "london": (51.51, -0.13), "cambridge": (52.21, 0.12), "oxford": (51.75, -1.26), "manchester": (53.48, -2.24),
    "edinburgh": (55.95, -3.19), "dublin": (53.35, -6.26), "berlin": (52.52, 13.40), "munich": (48.14, 11.58),
    "münchen": (48.14, 11.58), "hamburg": (53.55, 9.99), "frankfurt": (50.11, 8.68), "heidelberg": (49.40, 8.67),
    "erlangen": (49.60, 11.00), "forchheim": (49.72, 11.06), "tübingen": (48.52, 9.06), "tubingen": (48.52, 9.06),
    "cologne": (50.94, 6.96), "köln": (50.94, 6.96), "amsterdam": (52.37, 4.90), "utrecht": (52.09, 5.12),
    "rotterdam": (51.92, 4.48), "eindhoven": (51.44, 5.48), "leiden": (52.16, 4.49), "groningen": (53.22, 6.57),
    "delft": (52.01, 4.36), "brussels": (50.85, 4.35), "leuven": (50.88, 4.70), "ghent": (51.05, 3.72),
    "zurich": (47.38, 8.54), "zürich": (47.38, 8.54), "geneva": (46.20, 6.14), "lausanne": (46.52, 6.63),
    "basel": (47.56, 7.59), "bern": (46.95, 7.45), "vienna": (48.21, 16.37), "milan": (45.46, 9.19),
    "rome": (41.90, 12.50), "turin": (45.07, 7.69), "madrid": (40.42, -3.70), "barcelona": (41.39, 2.17),
    "lisbon": (38.72, -9.14), "porto": (41.15, -8.61), "copenhagen": (55.68, 12.57), "stockholm": (59.33, 18.07),
    "oslo": (59.91, 10.75), "helsinki": (60.17, 24.94), "warsaw": (52.23, 21.01), "prague": (50.08, 14.44),
    "budapest": (47.50, 19.04), "athens": (37.98, 23.73), "tallinn": (59.44, 24.75), "luxembourg": (49.61, 6.13),
    # Americas
    "new york": (40.71, -74.01), "boston": (42.36, -71.06), "san francisco": (37.77, -122.42),
    "palo alto": (37.44, -122.14), "los angeles": (34.05, -118.24), "san diego": (32.72, -117.16),
    "seattle": (47.61, -122.33), "chicago": (41.88, -87.63), "austin": (30.27, -97.74), "houston": (29.76, -95.37),
    "philadelphia": (39.95, -75.17), "baltimore": (39.29, -76.61), "washington": (38.91, -77.04),
    "rochester": (44.02, -92.47), "minneapolis": (44.98, -93.27), "denver": (39.74, -104.99),
    "atlanta": (33.75, -84.39), "miami": (25.76, -80.19), "toronto": (43.65, -79.38), "montreal": (45.50, -73.57),
    "vancouver": (49.28, -123.12), "winnipeg": (49.90, -97.14), "mexico city": (19.43, -99.13),
    "são paulo": (-23.55, -46.63), "sao paulo": (-23.55, -46.63), "buenos aires": (-34.60, -58.38),
    # Asia / Middle East / Africa / Oceania
    "hyderabad": (17.39, 78.49), "bangalore": (12.97, 77.59), "bengaluru": (12.97, 77.59), "mumbai": (19.08, 72.88),
    "delhi": (28.61, 77.21), "chennai": (13.08, 80.27), "pune": (18.52, 73.86), "haifa": (32.79, 34.99),
    "tel aviv": (32.09, 34.78), "jerusalem": (31.77, 35.21), "dubai": (25.20, 55.27), "abu dhabi": (24.45, 54.38),
    "riyadh": (24.71, 46.68), "doha": (25.29, 51.53), "singapore": (1.35, 103.82), "tokyo": (35.68, 139.69),
    "seoul": (37.57, 126.98), "shanghai": (31.23, 121.47), "beijing": (39.90, 116.41), "shenzhen": (22.54, 114.06),
    "hong kong": (22.32, 114.17), "taipei": (25.03, 121.57), "sydney": (-33.87, 151.21), "melbourne": (-37.81, 144.96),
    "brisbane": (-27.47, 153.03), "auckland": (-36.85, 174.76), "cape town": (-33.92, 18.42),
    "johannesburg": (-26.20, 28.05), "nairobi": (-1.29, 36.82), "lagos": (6.52, 3.38), "cairo": (30.04, 31.24),
}
COUNTRIES = {
    "france": (46.6, 2.4), "fr": (46.6, 2.4), "germany": (51.2, 10.4), "deutschland": (51.2, 10.4), "de": (51.2, 10.4),
    "united kingdom": (54.0, -2.0), "uk": (54.0, -2.0), "gb": (54.0, -2.0), "england": (52.5, -1.5),
    "ireland": (53.4, -8.2), "netherlands": (52.2, 5.3), "nederland": (52.2, 5.3), "nl": (52.2, 5.3),
    "belgium": (50.6, 4.6), "be": (50.6, 4.6), "switzerland": (46.8, 8.2), "ch": (46.8, 8.2),
    "austria": (47.6, 14.1), "italy": (42.8, 12.6), "it": (42.8, 12.6), "spain": (40.4, -3.7), "es": (40.4, -3.7),
    "portugal": (39.6, -8.0), "denmark": (56.0, 10.0), "sweden": (62.0, 15.0), "se": (62.0, 15.0),
    "norway": (61.0, 8.0), "finland": (64.0, 26.0), "poland": (52.0, 19.0), "czech": (49.8, 15.5),
    "hungary": (47.2, 19.5), "greece": (39.0, 22.0), "estonia": (58.6, 25.0), "luxembourg": (49.8, 6.1),
    "united states": (39.8, -98.6), "usa": (39.8, -98.6), "us": (39.8, -98.6), "u.s.": (39.8, -98.6),
    "canada": (56.1, -106.3), "ca": (56.1, -106.3), "mexico": (23.6, -102.6), "brazil": (-14.2, -51.9),
    "argentina": (-38.4, -63.6), "india": (21.0, 78.0), "in": (21.0, 78.0), "israel": (31.0, 34.9), "il": (31.0, 34.9),
    "uae": (24.0, 54.0), "united arab emirates": (24.0, 54.0), "saudi arabia": (23.9, 45.1), "qatar": (25.3, 51.2),
    "singapore": (1.35, 103.8), "sg": (1.35, 103.8), "japan": (36.2, 138.3), "jp": (36.2, 138.3),
    "south korea": (35.9, 127.8), "korea": (35.9, 127.8), "kr": (35.9, 127.8), "china": (35.9, 104.2), "cn": (35.9, 104.2),
    "taiwan": (23.7, 121.0), "australia": (-25.3, 133.8), "au": (-25.3, 133.8), "new zealand": (-40.9, 174.9),
    "south africa": (-30.6, 22.9), "kenya": (0.0, 37.9), "nigeria": (9.1, 8.7), "egypt": (26.8, 30.8),
    "europe": (50.0, 10.0), "eu": (50.0, 10.0), "emea": (48.0, 12.0), "west africa": (10.0, -2.0),
    "massachusetts": (42.4, -71.4), "california": (36.8, -119.4), "texas": (31.0, -99.0), "ma": (42.4, -71.4),
    "ny": (40.7, -74.0), "nj": (40.1, -74.5), "ontario": (51.2, -85.3), "manitoba": (53.8, -98.8), "kansas": (38.5, -98.0),
}
CITY_CC = {}
for _cc, _names in {
    "FR": "paris toulouse lyon marseille grenoble bordeaux nantes lille strasbourg montpellier nice rennes suresnes saclay|sophia antipolis|orsay boulogne île-de-france ile-de-france",
    "GB": "london cambridge oxford manchester edinburgh", "IE": "dublin",
    "DE": "berlin munich münchen hamburg frankfurt heidelberg erlangen forchheim tübingen tubingen cologne köln",
    "NL": "amsterdam utrecht rotterdam eindhoven leiden groningen delft", "BE": "brussels leuven ghent",
    "CH": "zurich zürich geneva lausanne basel bern", "AT": "vienna", "IT": "milan rome turin", "ES": "madrid barcelona",
    "PT": "lisbon porto", "DK": "copenhagen", "SE": "stockholm", "NO": "oslo", "FI": "helsinki", "PL": "warsaw",
    "CZ": "prague", "HU": "budapest", "GR": "athens", "EE": "tallinn", "LU": "luxembourg",
    "US": "new york|boston|san francisco|palo alto|los angeles|san diego|seattle|chicago|austin|houston|philadelphia|baltimore|washington|rochester|minneapolis|denver|atlanta|miami",
    "CA": "toronto montreal vancouver winnipeg", "MX": "mexico city", "BR": "são paulo|sao paulo", "AR": "buenos aires",
    "IN": "hyderabad bangalore bengaluru mumbai delhi chennai pune", "IL": "haifa|tel aviv|jerusalem",
    "AE": "dubai|abu dhabi", "SA": "riyadh", "QA": "doha", "SG": "singapore", "JP": "tokyo", "KR": "seoul",
    "CN": "shanghai beijing shenzhen", "HK": "hong kong", "TW": "taipei", "AU": "sydney melbourne brisbane",
    "NZ": "auckland", "ZA": "cape town|johannesburg", "KE": "nairobi", "NG": "lagos", "EG": "cairo",
}.items():
    for _part in _names.split("|"):
        for _n in ([_part.strip()] if _part.strip() in CITIES else _part.split()):
            CITY_CC[_n.strip()] = _cc

VIRTUAL = ("remote", "online", "worldwide", "anywhere", "virtual", "global")


def locate(text):
    """Return {'lat','lon','place','virtual'} or None."""
    t = (text or "").lower()
    if not t.strip():
        return None
    for city in sorted(CITIES, key=len, reverse=True):
        if re.search(rf"(?<![a-zà-ü]){re.escape(city)}(?![a-zà-ü])", t):
            lat, lon = CITIES[city]
            return {"lat": lat, "lon": lon, "place": city.title(), "virtual": False, "cc": CITY_CC.get(city, "")}
    for c in sorted(COUNTRIES, key=len, reverse=True):
        pat = rf"(?<![a-z.]){re.escape(c)}(?![a-z])"
        if len(c) <= 3:  # country codes only as standalone tokens / after a comma
            pat = rf"(^|[,(/]\s*|\s){re.escape(c)}(\s*$|[,)/])"
        if re.search(pat, t):
            lat, lon = COUNTRIES[c]
            return {"lat": lat, "lon": lon, "place": c.upper() if len(c) <= 3 else c.title(), "virtual": False,
                    "cc": country_code(c)}
    if any(v in t for v in VIRTUAL):
        return {"lat": None, "lon": None, "place": "Remote / Online", "virtual": True, "cc": ""}
    return None

ISO2 = {"FR": "france", "DE": "germany", "GB": "united kingdom", "UK": "united kingdom", "IE": "ireland",
        "NL": "netherlands", "BE": "belgium", "CH": "switzerland", "AT": "austria", "IT": "italy", "ES": "spain",
        "PT": "portugal", "DK": "denmark", "SE": "sweden", "NO": "norway", "FI": "finland", "PL": "poland",
        "CZ": "czech", "HU": "hungary", "GR": "greece", "EE": "estonia", "LU": "luxembourg", "US": "united states",
        "CA": "canada", "MX": "mexico", "BR": "brazil", "AR": "argentina", "IN": "india", "IL": "israel",
        "AE": "uae", "SA": "saudi arabia", "QA": "qatar", "SG": "singapore", "JP": "japan", "KR": "south korea",
        "CN": "china", "TW": "taiwan", "AU": "australia", "NZ": "new zealand", "ZA": "south africa", "KE": "kenya",
        "NG": "nigeria", "EG": "egypt", "TR": "turkey", "IR": "iran", "RU": "russia", "HK": "hong kong",
        "SI": "slovenia", "HR": "croatia", "RO": "romania", "RS": "serbia", "SK": "slovakia", "LT": "lithuania",
        "LV": "latvia", "IS": "iceland", "CY": "cyprus", "MT": "malta", "TH": "thailand", "MY": "malaysia",
        "VN": "vietnam", "PK": "pakistan", "CL": "chile", "CO": "colombia"}
COUNTRIES.update({"turkey": (39.0, 35.2), "iran": (32.4, 53.7), "russia": (61.5, 105.3), "slovenia": (46.1, 14.9),
                  "croatia": (45.1, 15.2), "romania": (45.9, 24.9), "serbia": (44.0, 21.0), "slovakia": (48.7, 19.7),
                  "lithuania": (55.2, 23.9), "latvia": (56.9, 24.6), "iceland": (64.9, -19.0), "cyprus": (35.1, 33.4),
                  "malta": (35.9, 14.4), "thailand": (15.9, 100.9), "malaysia": (4.2, 102.0), "vietnam": (14.1, 108.3),
                  "pakistan": (30.4, 69.3), "chile": (-35.7, -71.5), "colombia": (4.6, -74.3)})


_EXTRA_CC = {"usa": "US", "u.s.": "US", "united states": "US", "massachusetts": "US", "california": "US",
             "texas": "US", "ma": "US", "ny": "US", "nj": "US", "kansas": "US", "uk": "GB", "england": "GB",
             "deutschland": "DE", "nederland": "NL", "korea": "KR", "ontario": "CA", "manitoba": "CA",
             "europe": "EU", "eu": "EU", "emea": "EU", "west africa": "AF", "czech": "CZ"}


def country_code(name):
    name = name.lower()
    if name in _EXTRA_CC:
        return _EXTRA_CC[name]
    if len(name) == 2:
        return name.upper()
    for cc, n in ISO2.items():
        if n == name:
            return cc
    return ""
