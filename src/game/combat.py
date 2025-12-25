import random
from src.content.loader import load_data

class CombatResolver:
    """
    Handles resolution of Land and Air combat according to Rule 7 (DL_11).
    """
    def __init__(self, attackers, defenders, terrain_type, is_air_combat=False):
        self.attackers = attackers
        self.defenders = defenders
        self.terrain_type = terrain_type
        # Use the centralized loader
        self.crt_data = load_data("data/crt.yaml")

    """
    Calculates the odds of a combat based on the attacker's combat rating and the defender's combat rating.
    
    Returns:
        str: The odds string in the format "X:Y" where X is the attacker's odds and Y is the defender's odds.
    """
    def calculate_odds(self, attacker_cs, defender_cs):

        # Rule 7.2: Minimum 1/4 odds, Maximum 7/1 odds logic
        if defender_cs <= 0: return "6:1"
        ratio = attacker_cs / defender_cs
        # ... logic to map ratio to CRT columns ...
        if ratio >= 6: return "6:1"
        if ratio >= 5: return "5:1"
        if ratio >= 4: return "4:1"
        if ratio >= 3: return "3:1"
        if ratio >= 2: return "2:1"
        if ratio >= 1: return "1:1"
        if ratio >= 0.5: return "1:2"
        if ratio >= 0.33: return "1:3"

        return "1:4"

    def resolve(self):
        # 1. Calculate Odds
        attacker_cs = sum(u.combat_rating for u in self.attackers)
        defender_cs = sum(u.combat_rating for u in self.defenders)
        
        odds_str = self.calculate_odds(attacker_cs, defender_cs)
        
        # 2. Determine DRMs (Leader Tactical Ratings, Terrain, etc.)
        drm = self.calculate_total_drm()

        # 3. Roll 1d10
        roll = random.randint(1, 10)
        final_roll = max(1, min(10, roll + drm))
        
        # 4. Look up result from YAML data
        # Note: YAML keys might be ints or strings depending on formatting; 
        # ensure consistency.
        result_code = self.crt_data[final_roll][odds_str]
        
        return result_code

    def calculate_total_drm(self):
        # TODO: Implement Rule 7.4 (Leaders and Terrain)
        return 0