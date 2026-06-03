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


def get_team_codes(team_name):
    """
    Returns possible MLB Stats API team abbreviations for a team name.
    """
    return MLB_TEAM_TO_CODES.get(team_name, [team_name])