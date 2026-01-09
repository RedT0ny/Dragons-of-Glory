import random
from src.content.config import CRT_DATA, MIN_COMBAT_ROLL, MAX_COMBAT_ROLL
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
        self.crt_data = load_data(CRT_DATA) # csv or yaml?

    def calculate_odds(self, attacker_cs, defender_cs):
        """
        Calculates the odds of a combat based on the attacker's combat rating and the defender's combat rating.
        Rule 7.2: Minimum 1/3 odds, Maximum 6/1 odds logic

        Returns:
            str: The odds string in the format "X:Y" where X is the attacker's odds and Y is the defender's odds.
        """
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

        # min -5, max 16
        final_roll = max(MIN_COMBAT_ROLL, min(MAX_COMBAT_ROLL, roll + drm))

        # 4. Look up result from CRT data
        result = self.crt_data[final_roll][odds_str]

        self.apply_results(result, self.attackers, True)
        self.apply_results(result, self.defenders, False)

        return result

    def apply_results(self, result_code, units, is_attacker):
        """
        Apply combat results to the given units.

        units: list of Unit objects in the hex
        combat_result: string like "DR", "2/E", "E/1", etc.
        is_attacker: True if applying to attacker's units
        """
        must_retreat = False

        # Parse combat result (e.g., "D1" or "2/E")
        if is_attacker:
            result = result_code.split('/')[0]
        else:
            result = result_code.split('/')[1]

        # Handle cumulative results like "DR"
        if len(result) > 1:
            # First apply the letter result, then the number
            result = result[0]
            must_retreat = True

        # If result is "D" or "E", apply to all units
        if result in ['D', 'E']:
            for unit in units:
                unit.apply_combat_loss(result, must_retreat)

        elif result in ['1', '2']:
            #TODO: Let the player choose which units take damage and retreat
            return NotImplementedError

        else:  # Error
            error_msg = f"Invalid combat result: {result_code}"
            raise ValueError(error_msg)

    def calculate_total_drm(self):
        # TODO: Implement Rule 7.4 (Leaders and Terrain)
        return 0