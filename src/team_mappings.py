# src/team_mappings.py

MLB_TEAM_TO_CODES = {
    "Arizona Diamondbacks": ["AZ", "ARI", "ARZ"],
    "Atlanta Braves": ["ATL"],
    "Baltimore Orioles": ["BAL"],
    "Boston Red Sox": ["BOS"],
    "Chicago Cubs": ["CHC"],
    "Chicago White Sox": ["CWS", "CHW"],
    "Cincinnati Reds": ["CIN"],
    "Cleveland Guardians": ["CLE"],
    "Colorado Rockies": ["COL"],
    "Detroit Tigers": ["DET"],
    "Houston Astros": ["HOU"],
    "Kansas City Royals": ["KC", "KCR"],
    "Los Angeles Angels": ["LAA"],
    "Los Angeles Dodgers": ["LAD"],
    "Miami Marlins": ["MIA"],
    "Milwaukee Brewers": ["MIL"],
    "Minnesota Twins": ["MIN"],
    "New York Mets": ["NYM"],
    "New York Yankees": ["NYY"],
    "Athletics": ["ATH", "OAK"],
    "Oakland Athletics": ["OAK", "ATH"],
    "Philadelphia Phillies": ["PHI"],
    "Pittsburgh Pirates": ["PIT"],
    "San Diego Padres": ["SD", "SDP"],
    "San Francisco Giants": ["SF", "SFG"],
    "Seattle Mariners": ["SEA"],
    "St. Louis Cardinals": ["STL"],
    "Tampa Bay Rays": ["TB", "TBR"],
    "Texas Rangers": ["TEX"],
    "Toronto Blue Jays": ["TOR"],
    "Washington Nationals": ["WSH", "WSN"],
}

RETROSHEET_TEAM_NAMES = {
    "ANA": "Los Angeles Angels",
    "ARI": "Arizona Diamondbacks",
    "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox",
    "CHA": "Chicago White Sox",
    "CHN": "Chicago Cubs",
    "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",
    "DET": "Detroit Tigers",
    "FLO": "Miami Marlins",
    "HOU": "Houston Astros",
    "KCA": "Kansas City Royals",
    "LAN": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYA": "New York Yankees",
    "NYN": "New York Mets",
    "OAK": "Oakland Athletics",
    "ATH": "Athletics",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SDN": "San Diego Padres",
    "SEA": "Seattle Mariners",
    "SFN": "San Francisco Giants",
    "SLN": "St. Louis Cardinals",
    "TBA": "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WAS": "Washington Nationals",
}


def get_team_codes(team_name):
    """
    Returns possible MLB Stats API team abbreviations for a team name.
    """
    return MLB_TEAM_TO_CODES.get(team_name, [team_name])


def retrosheet_team_name(team_code):
    if team_code is None:
        return None
    code = str(team_code).strip().upper()
    return RETROSHEET_TEAM_NAMES.get(code, code)
