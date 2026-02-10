import random
from src.content.config import CRT_DATA
from src.content.constants import MIN_COMBAT_ROLL, MAX_COMBAT_ROLL
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

        # Logic to map ratio to CRT columns (rounding in favor of defender)
        if ratio >= 6: return "6:1"
        if ratio >= 5: return "5:1"
        if ratio >= 4: return "4:1"
        if ratio >= 3: return "3:1"
        if ratio >= 2: return "2:1"
        if ratio >= 1.5: return "3:2"
        if ratio >= 1: return "1:1"
        if ratio >= 0.66: return "2:3"
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

        # Parse combat result (e.g., "D1", "2/E", or "-/DR")
        if is_attacker:
            result = result_code.split('/')[0]
        else:
            result = result_code.split('/')[1]

        # Handle "No Effect" result
        if result == '-':
            return

        # Handle cumulative results like "DR" (Damage + Retreat)
        if len(result) > 1:
            # If result is "DR", first char is 'D', second is 'R' (retreat)
            # If result is "1R", first char is '1', second is 'R'
            if 'R' in result:
                must_retreat = True
            result = result[0]

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


class CombatClickHandler:
    def __init__(self, game_state, view):
        self.game_state = game_state
        self.view = view
        self.attackers = []

    def handle_click(self, target_hex):
        units_at_hex = self.game_state.map.get_units_in_hex(target_hex.q, target_hex.r)
        active_player = self.game_state.active_player

        # Identify what was clicked
        friendly_units = [
            u for u in units_at_hex
            if u.allegiance == active_player
            and not u.attacked_this_turn
            and self._is_unit_on_map(u)
        ]
        enemy_units = [
            u for u in units_at_hex
            if u.allegiance != active_player
            and u.allegiance != 'neutral'
            and self._is_unit_on_map(u)
        ]

        # --- Scenario 2: Clicked Friendly Stack ---
        if friendly_units:
            if self.attackers:
                new_selection = list(set(self.attackers + friendly_units))
            else:
                new_selection = friendly_units

            # Calculate common targets for this NEW proposed selection
            common_targets = self.calculate_common_targets(new_selection)

            if not common_targets:
                # Case 2b: "Turn possible targets to none" -> Refresh and show ONLY current stack
                self.attackers = friendly_units
                # Recalculate targets for just this stack
                common_targets = self.calculate_common_targets(self.attackers)
            else:
                # Case 2a: Valid combination
                self.attackers = new_selection

            # Update UI
            self.view.units_clicked.emit(self.attackers)
            self.view.highlight_movement_range(common_targets)
            return

        # --- Scenario 3, 4, 5: Clicked Enemy or Empty ---

        # Check if this hex is a Valid Target for the CURRENT selection
        current_targets = self.calculate_common_targets(self.attackers)
        clicked_offset = target_hex.axial_to_offset()

        if clicked_offset in current_targets:
            # --- Scenario 5: Clicked a Possible Target ---
            from PySide6.QtWidgets import QMessageBox

            # Show Odds Dialog
            odds_str = self.calculate_odds_preview(self.attackers, enemy_units, target_hex)

            reply = QMessageBox.question(
                None,
                "Confirm Attack",
                f"Attack with {len(self.attackers)} units?\nOdds: {odds_str}",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                self.game_state.resolve_combat(self.attackers, target_hex)
                # Mark attackers
                for u in self.attackers:
                    u.attacked_this_turn = True

                # Clear all
                self.reset_selection()
            return

        # If not a valid target...
        if enemy_units:
            # --- Scenario 3: Clicked Invalid Enemy ---
            self.reset_selection()
        else:
            # --- Scenario 4: Clicked Empty Hex ---
            self.reset_selection()

    def reset_selection(self):
        self.attackers = []
        self.view.highlight_movement_range([])
        self.view.units_clicked.emit([])

    def calculate_common_targets(self, attackers):
        """
        Returns list of (col, row) valid targets that ALL attacker stacks can attack.
        Actually, the rule is: "several stacks... can combine... against a defender's hex".
        This means the target hex must be adjacent to ALL participating stacks.
        """
        attackers = [u for u in attackers if self._is_unit_on_map(u)]
        if not attackers:
            return []

        # Group attackers by location (Stack)
        from collections import defaultdict
        stacks = defaultdict(list)
        for u in attackers:
            if u.position and u.position[0] is not None and u.position[1] is not None:
                stacks[u.position].append(u)

        if not stacks:
            return []

        # Find valid targets for EACH stack
        stack_targets = []
        for pos, unit_list in stacks.items():
            # Get targets for this specific stack
            # A target is valid if it has enemies and is adjacent (and valid terrain)
            targets_for_this_stack = set(self.calculate_valid_targets(unit_list))
            stack_targets.append(targets_for_this_stack)

        # Find intersection
        if not stack_targets:
            return []

        common_set = set.intersection(*stack_targets)
        return list(common_set)

    def calculate_valid_targets(self, attackers):
        """Returns list of (col, row) tuples for valid attack targets."""
        attackers = [u for u in attackers if self._is_unit_on_map(u)]
        if not attackers:
            return []

        # 1. Get all unique positions of attackers (usually they are in one stack, but could be multi-hex attack)
        attacker_hexes = set()
        for u in attackers:
            if u.position and u.position[0] is not None and u.position[1] is not None:
                from src.game.map import Hex
                attacker_hexes.add(Hex.offset_to_axial(*u.position))

        valid_target_offsets = set()

        # 2. Check neighbors of all attacker positions
        for start_hex in attacker_hexes:
            for next_hex in start_hex.neighbors():
                # Is there an enemy there?
                if self.game_state.map.has_enemy_army(next_hex, self.game_state.active_player):
                    # Validate "Move into" rule
                    if self.is_valid_attack_hex(attackers, start_hex, next_hex):
                        valid_target_offsets.add(next_hex.axial_to_offset())

        return list(valid_target_offsets)

    def is_valid_attack_hex(self, attackers, start_hex, target_hex):
        """
        Checks if specific units can attack across this hexside.
        """
        hexside = self.game_state.map.get_hexside(start_hex, target_hex)

        if hexside == "mountain":
            # Check if ALL attackers are capable
            for u in attackers:
                can_cross = u.unit_type == 'wing' or u.unit_type in ['dwarves', 'ogres']
                if not can_cross:
                    return False
        return True

    def calculate_odds_preview(self, attackers, defenders, hex_position):
        """Helper to just get the string "3:1" etc without rolling."""
        # We create a dummy resolver just to calc odds
        terrain = self.game_state.map.get_terrain(hex_position)
        resolver = CombatResolver(attackers, defenders, terrain)

        attacker_cs = sum(u.combat_rating for u in attackers)
        defender_cs = sum(u.combat_rating for u in defenders)
        return resolver.calculate_odds(attacker_cs, defender_cs)

    def _is_unit_on_map(self, unit):
        return bool(getattr(unit, "is_on_map", False) and unit.position and unit.position[0] is not None and unit.position[1] is not None)
