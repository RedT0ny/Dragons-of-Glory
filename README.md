# Dragons-of-Glory
A python implementation of Dragonlance classic "Dragons of Glory", with Dragon #170's Advanced Rules and other updates.




Notes:




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