import random
from src.content.loader import load_data

class CombatResolver:
    """
    Handles resolution of Land and Air combat according to Rule 7 (DL_11).
    """
    def __init__(self, attackers, defenders, terrain_type):
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

        # Rule 7.2: Minimum 1/3 odds, Maximum 6/1 odds logic
        if defender_cs <= 0: return "6:1"
        ratio = attacker_cs / defender_cs
        # ... logic to map ratio to CRT columns ...
        if ratio >= 6: return "6:1"
        if ratio >= 5: return "5:1"
        if ratio >= 4: return "4:1"
        if ratio >= 3.33: return "3:2"
        if ratio >= 3: return "3:1"
        if ratio >= 2: return "2:1"
        if ratio >= 1.5: return "2:3"
        if ratio >= 1: return "1:1"
        if ratio >= 0.5: return "1:2"

        return "1:3"

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
        result = self.crt_data[final_roll][odds_str]

        self.apply_results(result)
        return result

    def apply_results(self, result_code):
        """
        Interprets: { a_res: "E", a_ret: bool, d_res: 1, d_ret: bool }
        """
        # Handle Attacker
        if result['a_res'] == "E":
            for u in self.attackers: u.status = "depleted"
        elif isinstance(result['a_res'], int):
            # Logic to eliminate X number of units...
            pass

        if result['a_ret']:
            # Trigger retreat logic for attackers
            pass

        # Handle Defender
        # ... similar logic for d_res and d_ret ...

    def calculate_total_drm(self):
        # TODO: Implement Rule 7.4 (Leaders and Terrain)
        return 0