import pygame
import yaml
import math
import os

# Configuration for the hexagonal grid
HEX_RADIUS = 12
MAP_WIDTH = 65  # Max col observed in yaml + buffer
MAP_HEIGHT = 55 # Max row observed in yaml + buffer
SCREEN_WIDTH = 1600
SCREEN_HEIGHT = 1000

def get_hex_center(col, row, radius):
    """Calculates pixel center for a pointy-top hex using odd-r offset coordinates."""
    x = radius * math.sqrt(3) * (col + 0.5 * (row & 1))
    y = radius * 3/2 * row
    return int(x + 50), int(y + 50) # Added margin

def draw_hexagon(surface, color, center, radius):
    """Draws a single pointy-top hexagon."""
    points = []
    for i in range(6):
        angle_deg = 60 * i - 30
        angle_rad = math.pi / 180 * angle_deg
        points.append((center[0] + radius * math.cos(angle_rad),
                       center[1] + radius * math.sin(angle_rad)))
    pygame.draw.polygon(surface, color, points)
    pygame.draw.polygon(surface, (40, 40, 40), points, 1) # Hex border

def draw_location_symbol(surface, center, loc_type, is_capital):
    """Draws a symbol representing the type of location."""
    size = 6
    if loc_type == 'city':
        # Square for cities
        rect = pygame.Rect(center[0] - size//2, center[1] - size//2, size, size)
        pygame.draw.rect(surface, (255, 255, 255), rect)
    elif loc_type == 'fortress':
        # Diamond for fortresses
        pts = [(center[0], center[1] - size), (center[0] + size, center[1]), 
               (center[0], center[1] + size), (center[0] - size, center[1])]
        pygame.draw.polygon(surface, (255, 255, 255), pts)
    elif loc_type == 'port':
        # Circle for ports
        pygame.draw.circle(surface, (255, 255, 255), center, size // 2 + 1)
    else:
        # Triangle for undercities/others
        pts = [(center[0], center[1] - size), (center[0] - size, center[1] + size), 
               (center[0] + size, center[1] + size)]
        pygame.draw.polygon(surface, (255, 255, 255), pts)
    
    if is_capital:
        # Gold dot on top for capitals
        pygame.draw.circle(surface, (255, 215, 0), (center[0], center[1] - size - 2), 2)

def run_visualization():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Dragons of Glory - Territory Allocation Tester")
    clock = pygame.time.Clock()

    # Load country data using a robust path relative to the script location
    current_dir = os.path.dirname(os.path.abspath(__file__))
    yaml_path = os.path.join(current_dir, "..", "data", "countries.yaml")
    
    try:
        with open(yaml_path, 'r') as f:
            countries_data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: Could not find {yaml_path}. Check your directory structure.")
        return

    # Map hexes to colors and store locations
    hex_map = {}
    location_map = {} # (col, row) -> {type, is_capital}
    
    for cid, data in countries_data.items():
        color_hex = data.get('color', '#808080').lstrip('#')
        color_rgb = tuple(int(color_hex[i:i+2], 16) for i in (0, 2, 4))
        capital_id = data.get('capital_id')
    
        # Load territories
        for coord in data.get('territories', []):
            if isinstance(coord, list) and len(coord) == 2:
                hex_map[tuple(coord)] = color_rgb
            elif isinstance(coord, list) and len(coord) == 1: # Handle edge case [31, 13]
                pass # Handled by the check above usually, but YAML can be tricky
        
        # Load locations
        for loc_id, loc_info in data.get('locations', {}).items():
            coords = tuple(loc_info.get('coords', []))
            if coords:
                location_map[coords] = {
                    'type': loc_info.get('type', 'city'),
                    'is_capital': (loc_id == capital_id)
                }

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        screen.fill((20, 20, 20)) # Dark background

        # Draw the full grid
        for row in range(MAP_HEIGHT):
            for col in range(MAP_WIDTH):
                center = get_hex_center(col, row, HEX_RADIUS)
            
                # Use country color if allocated, otherwise use a faint gray for empty hexes
                color = hex_map.get((col, row), (50, 50, 50))
                draw_hexagon(screen, color, center, HEX_RADIUS)
                
                # Draw location symbol if present
                loc = location_map.get((col, row))
                if loc:
                    draw_location_symbol(screen, center, loc['type'], loc['is_capital'])

        pygame.display.flip()
        clock.tick(30)

    pygame.quit()

if __name__ == "__main__":
    run_visualization()
