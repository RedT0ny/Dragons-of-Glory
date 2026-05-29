# Dragons-of-Glory

<div style="font-family: 'Segoe UI', sans-serif; font-size: 9pt; color: #0f1115;">
  <p>A python & Qt implementation of Dragonlance classic "Dragons of Glory".</p>

  <p style="font-family: 'Courier New', monospace; font-size: 10pt;">
    Dragons of Glory is a fan-made, non-profit adaptation of the classic Dragonlance module
    DL-11 "Dragons of Glory."
  </p>

  <hr style="border: none; border-top: 1px solid #0f1115; margin: 12px 0;">

  <h3 style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 12px 0 6px;">LEGAL &amp; COPYRIGHT INFORMATION</h3>

  <p style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 6px 0;">
    This game is unofficial Fan Content permitted under the Wizards of the Coast Fan Content Policy.
    It is not approved, endorsed, or sponsored by Wizards of the Coast LLC.
  </p>

  <p style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 6px 0;">
    Portions of the materials used are property of Wizards of the Coast LLC, including references to:
  </p>
  <ul style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 6px 0 6px 18px; padding: 0;">
    <li>Dragonlance®</li>
    <li>DL-11 "Dragons of Glory"</li>
    <li>TSR, Inc.</li>
  </ul>

  <p style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 6px 0;">
    DL-11 "Dragons of Glory" was published by TSR, Inc. in 1985 as part of the Dragonlance series of
    adventure modules. It featured a war game simulation of the War of the Lance in the Dragonlance
    campaign setting. It was created by:
  </p>
  <ul style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 6px 0 6px 18px; padding: 0;">
    <li>Douglas Niles</li>
    <li>Tracy Hickman</li>
    <li>Jeff Easley (cover artist)</li>
  </ul>

  <p style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 6px 0;">
    © Wizards of the Coast LLC. All Rights Reserved.
  </p>

  <hr style="border: none; border-top: 1px solid #0f1115; margin: 12px 0;">

  <h3 style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 12px 0 6px;">Contact / Credits</h3>
  <p style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 6px 0;">
    <b>Creator</b>: <a href="mailto:redtony@gmail.com?subject=About DoG" style="color: #14427c; text-decoration: underline;">Tony J. Soler</a>
  </p>

  <hr style="border: none; border-top: 1px solid #0f1115; margin: 12px 0;">

  <h3 style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 12px 0 6px;">Licensing</h3>
  <p style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 6px 0;">
    This game's original code is free software: you can redistribute it and/or modify it under the terms of the
    <a href="https://www.gnu.org/licenses/" style="color: #14427c; text-decoration: underline;">GNU General Public License</a> as published by the Free Software Foundation,
    either version 3 of the License, or (at your option) any later version.
  </p>

  <p style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 6px 0;">
    This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
    warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
    <a href="https://www.gnu.org/licenses/gpl-3.0.en.html" style="color: #14427c; text-decoration: underline;">GNU General Public License v3.0</a> for more details.
  </p>

  <p style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 6px 0; text-align: center;">
    --- <b>IMPORTANT NOTE</b> ---
  </p>

  <p style="font-family: 'Courier New', monospace; font-size: 10pt; margin: 6px 0;">
    This license applies ONLY to the original code written by the game's author. The Dragonlance setting, DL-11 module
    content, and all related Wizards of the Coast intellectual property are NOT covered by this license and remain the
    exclusive property of Wizards of the Coast LLC.
  </p>
</div>

Design overview:
![game_layout.svg](assets/design/game_layout.svg)

TODO:

- Add Dragon #170's Advanced Rules in "settings" - Intercept and supply done, winter turns missing.
- I18n (Partially)

TODO BUGFIX:

- Fix map subset not working correctly (use full map for now).
- Avoid garrisons (units that cannot move) being boarded onto ships.
- AI not deploying units created by events until next replacements phase.

Notes:

constants.py        ← Pure strings/numbers, NO imports (Not required?)
specs.py           ← Imports constants, defines domain
config.py          ← Imports specs, defines runtime
main.py            ← Imports everything

Every country has a color for their units. The country can be neutral, aligned with Whitestone or aligned with Highlord.
How to show the unit allegiance without changing the original color?
DECISION: Use a different icon, border and font/text color. White for Whitestone, Black for Highlord, Grey for Neutral.

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
Disable not only end phase button during AI turn, but also pressing enter key. Activate it in the strategic events turn
of the player only.

