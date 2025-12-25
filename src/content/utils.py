def to_roman(n):
    """Convert an integer to Roman numeral."""
    if not n: return ""
    roman_map = [(10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]
    result = ""
    for value, symbol in roman_map:
        while n >= value:
            result += symbol
            n -= value
    return result
