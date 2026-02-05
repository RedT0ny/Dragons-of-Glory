# Dragons-of-Glory
A python implementation of Dragonlance classic "Dragons of Glory".

Design overview:
![game_layout.svg](assets/img/game_layout.svg)

TODO:

- Add Dragon #170's Advanced Rules in "settings"
- Add attribute and diplomacy logic for Knight's countries
- Finalize movement and combat phases.
- Implement save and load game
- Check victory conditions
- double-click on a unit in the status tab should show the map tab and zoom on the unit.
- Implement dashboards
- Implement AI player
- Change replacements dialog to window
- I18n

TODO BUGFIX:

- Fix map subset not working correctly (use full map for now).
- Fix deployment of land-less units (e.g. dragonflights) on the map.
- Add position in the unit table.

Notes:

constants.py        ← Pure strings/numbers, NO imports (Not required?)
specs.py           ← Imports constants, defines domain
config.py          ← Imports specs, defines runtime
main.py            ← Imports everything

Every country has a color for their units. The country can be neutral, aligned with Whitestone or aligned with Highlord.
How to show the unit allegiance without changing the original color?
Options:
1. Add a new color for each unit allegiance.
2. Use a different shade of the original color.
3. Use a different font/text color.
4. Use a different icon color.
5. Use a different background color.
6. Use a different border color.
7. Use a different shadow color.

Moving units:

1. Show the unit on the map.
2. If several units stacking on the same Hex, show the top unit but modify the border to look like a "pile".
3. First click selects the stack, movement possibility (highlighted hex) is shown for the more restrictive unit in the stack.
4. Second click selects the top unit, third click would select the next unit in the stack, etc.
5. At the bottom of the right panel, a list will show the units stacked in the selected Hex.
6. Once the unit or stack is selected, it can be dragged to a new Hex.
7. The unit or stack will be moved to the new Hex.

Events and artifacts:

events in the scenario yaml:

if active_events [{ event_id : int(times) }] remove them from the game_state list of active events or reduce the number of possible occurrences by times.
if active_events: [{ event_id : all }] remove all possible occurrences of event_id from the game_state list.
if possible_events [{ event_id : int(times)}] add to the game_state event list only the ones in this list.
if possible_events: null remove all possible events from the game_state list.
if possible_events not defined, add all events to the game_state list.

events in the event.yaml:

if max_occurrences not indicated or = 1, the event can only be triggered once.
if max_occurrences is 0, the event can never be triggered.
if max_occurrences is > 0, the event can be triggered up to max_occurrences times.
if max_occurrences is < 0, the event can be triggered an infinite number of times.
Add a new field 'probability' to increase chances of an event being triggered? Use 
Pseudo-Random Distribution (PRD) and Bad Luck Protection (BLP)
add a new field 'triggered' to the event dataclass?

events in the game_state list:

if game_state events list is empty, skip event phase and show a placeholder.

How to deal with pre-requisites? List of pre_req_ids in the player dataclass.
Or simplify them as not-assignable artifacts (dragonmetal, Knight countries at war...)



