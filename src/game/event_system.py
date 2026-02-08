import random

from src.content.config import UNITS_DATA
from src.content.specs import UnitType
from src.game.event import check_requirements
from src.content import factory


class EventSystem:
    def __init__(self, game_state):
        self.game_state = game_state

    def check_event_trigger_conditions(self, conditions) -> bool:
        """Checks if a list of trigger conditions is met."""
        if not conditions:
            return False

        # Example condition format: "turn: 5" or "always_true" or dict
        for cond in conditions:
            if isinstance(cond, str):
                if cond == "always_true":
                    return True
                # Parse simple strings if needed
            elif isinstance(cond, dict):
                if "turn" in cond and self.game_state.turn == cond["turn"]:
                    return True
                # Add more conditions as needed (e.g. "unit_at")

        return False

    def check_event_requirements_met(self, requirements) -> bool:
        """Checks if event prerequisites are met."""
        if not requirements:
            return True

        current_player_obj = self.game_state.current_player
        for req in requirements:
            # Reusing the shared check_requirements from event.py
            if not check_requirements(req, current_player_obj, self.game_state):
                return False
        return True

    def _resolve_add_units(self, unit_key: str, allegiance: str):
        """Resolves generic add_units keys to specific units and readies them."""
        catalog = factory.UnitCatalog(UNITS_DATA)
        existing_ids = {u.id for u in self.game_state.units}
        available_specs = catalog.get_available_specs(existing_ids)
        candidates = []

        # 1. Wizards
        if unit_key == "wizard":
            candidates = [s for s in available_specs
                          if s.unit_type == UnitType.WIZARD.value and s.allegiance == allegiance]
            candidates = candidates[:1]

        # 2. Flying Citadel
        elif unit_key == "citadel":
            # Assuming UnitType.CITADEL exists, otherwise checking string representation
            candidates = [s for s in available_specs
                          if (s.unit_type == UnitType.CITADEL.value if hasattr(UnitType, 'CITADEL') else str(s.unit_type).lower() == 'citadel')
                          and s.allegiance == allegiance]
            candidates = candidates[:1]

        # 3. Golden General (Laurana)
        elif unit_key == "golden_general":
            candidates = [s for s in available_specs if s.id == "laurana"]
            candidates = candidates[:1]

        # 4. Good Dragons
        elif unit_key == "good_dragons":
            candidates = [s for s in available_specs
                          if s.unit_type == UnitType.WING.value and s.allegiance == "whitestone"]

        # Fallback: Try to find by direct ID match
        if not candidates:
            candidates = [s for s in available_specs if s.id == unit_key]
            candidates = candidates[:1]

        if not candidates:
            print(f"Warning: No units found for add_units key '{unit_key}'")

        created = factory.create_units_from_specs(
            candidates,
            allegiance=allegiance,
            countries=self.game_state.countries,
            ready=True
        )
        self.game_state.units.extend(created)
        for u in created:
            print(f"Unit {u.id} added/ready for {allegiance}")

    def apply_event_effect(self, spec):
        """Applies the effects of an event."""
        if not spec.effects:
            return

        player = self.game_state.current_player
        effects = spec.effects

        # 1. Alliance: Activates country and readies units
        if "alliance" in effects:
            country_id = effects["alliance"]
            self.game_state.activate_country(country_id, player.allegiance)

        # 2. Add Units: Adds specific units to the pool (READY state)
        if "add_units" in effects:
            unit_key = effects["add_units"]
            self._resolve_add_units(unit_key, player.allegiance)

        # 3. Grant Asset: Processed last
        if "grant_asset" in effects:
            asset_id = effects["grant_asset"]
            # Delegate to Player class to ensure consistent asset creation and storage
            player.grant_asset(asset_id, self.game_state)

        # Other effects...

    def draw_strategic_event(self, allegiance):
        """
        Draws an event for the given allegiance based on triggers and probability.
        """
        # 1. Check for Auto-Triggers (Highest priority)
        candidates = []
        for event in self.game_state.strategic_event_pool:
            if event.id in self.game_state.completed_event_ids:
                continue
            if event.occurrence_count >= event.spec.max_occurrences:
                continue
            # "Each player can only draw either an event of their allegiance or an event without allegiance"
            if event.spec.allegiance and event.spec.allegiance != allegiance:
                continue
            candidates.append(event)

        # 2. Check for Auto-triggers
        for event in candidates:
            if event.spec.trigger_conditions:
                if self.check_event_trigger_conditions(event.spec.trigger_conditions):
                    return event

        # 3. Check for possible events + requirements
        possible_events = []
        weights = []

        for event in candidates:
            # If it has trigger conditions and none were met, skip
            if event.spec.trigger_conditions:
                continue

            # Pre-requirements
            if not self.check_event_requirements_met(event.spec.requirements):
                continue

            # Turn check and Probability Weight Calculation
            if event.spec.turn is None:
                diff = 0
            else:
                if self.game_state.turn < event.spec.turn:
                    continue
                diff = self.game_state.turn - event.spec.turn

            # Formula: chance reduces as diff increases
            # Base prob * (1 / (1 + 0.5 * diff)) - tunable decay
            decay = 1.0 / (1.0 + 0.5 * diff)

            # Use spec.probability (default 1.0)
            weight = getattr(event.spec, 'probability', 1.0) * decay

            possible_events.append(event)
            weights.append(weight)

        if not possible_events:
            return None

        # Draw one
        chosen = random.choices(possible_events, weights=weights, k=1)[0]
        return chosen

    def check_events(self):
        """Iterates through active events to see if turn-based triggers fire."""
        for event in self.game_state.events[:]:  # Iterate over a copy to allow removal
            if event.check_trigger(self.game_state):
                event.activate(self.game_state)

                # Logic: If the event has hit its specific limit, remove it from the active pool
                # and track it as completed.
                if event.occurrence_count >= event.spec.max_occurrences:
                    self.game_state.completed_event_ids.add(event.id)
                    self.game_state.events.remove(event)
