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
- Implement AI player
- Review country colors and unit icons to make them more distinguishable.
- I18n

TODO BUGFIX:

- Fleets cannot be deployed in ports that are not coastal. Probably has something to do with deep river? Happens in Castle Gunthar.
- Fix map subset not working correctly (use full map for now).

Notes:

constants.py        ← Pure strings/numbers, NO imports (Not required?)
specs.py           ← Imports constants, defines domain
config.py          ← Imports specs, defines runtime
main.py            ← Imports everything

Every country has a color for their units. The country can be neutral, aligned with Whitestone or aligned with Highlord.
How to show the unit allegiance without changing the original color?
DECISION: Use a different icon, border and font/text color. White for Whitestone, Black for Highlord, Grey for Neutral.

Moving units QoL improvements needed:

1. First click selects the stack, movement possibility (highlighted hex) is shown for the more restrictive unit in the stack. (Done)
2. Second click selects the top unit, third click would select the next unit in the stack, etc.
3. (UNSURE) Once the unit or stack is selected, it can be dragged to a new Hex. How to distinguish between dragging and clicking? Maybe a long click (click and hold for 0.5s) could trigger the drag mode?

Events and artifacts:

events in the scenario yaml:

if active_events [{ event_id : int(times) }] remove them from the game_state list of active events or reduce the number of possible occurrences by times.
if active_events: [{ event_id : all }] remove all possible occurrences of event_id from the game_state list.
if possible_events [{ event_id : int(times)}] add to the game_state event list only the ones in this list.
if possible_events: null remove all possible events from the game_state list.
if possible_events not defined, add all events to the game_state list.
Add a banned_events field to the scenario yaml to remove specific events from the game_state list? E.g: banned_events: ["soths_legions", "gnome_tech"] for Silvanesti scenario.  

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
