# Quick and simple version
import csv
from src.content.config import CRT_DATA
from src.content.constants import MIN_COMBAT_ROLL, MAX_COMBAT_ROLL

# Read directly into a 2D dictionary
combat_results = {}

with open(CRT_DATA, 'r') as f:
    reader = csv.reader(f, delimiter=';')
    headers = next(reader)

    for row in reader:
        roll = int(row[0])
        combat_results[roll] = {}

        for i in range(1, len(headers)):
            combat_results[roll][headers[i]] = row[i]


# Simple lookup
def quick_lookup(roll, odds):
    roll = max(min(roll, 16), -5)
    return combat_results[roll][odds]


# Use it
print(quick_lookup(5, '3:1'))  # Should be '2/2R'

for roll, odds in combat_results.items():
    print(f"{roll}: {odds}")