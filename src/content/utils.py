def to_roman(n: int):
    """Convert an integer to Roman numeral."""
    if not n: return ""
    roman_map = [(10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]
    result = ""
    for value, symbol in roman_map:
        while n >= value:
            result += symbol
            n -= value
    return result

def caption_id(unit_id: str):
    """Transform a unit ID string according to the specified rules.

    Example: 'kern_ogre_inf_1' → '1 Kern'
    Example: 'solamnia' → 'Solamnia'

    Args:
        unit_id: The original unit ID string

    Returns:
        Transformed string according to the rules
    """
    id_text = f"{unit_id}"

    if '_' in id_text:
        parts = id_text.split('_')
        if parts[-1].isdigit():
            return f"{to_roman(int(parts[-1]))} {parts[0].capitalize()}"
        # If underscores but no number at end, return original capitalized
        return parts[0].capitalize()

    # No underscores: capitalize the whole thing
    return id_text.capitalize()