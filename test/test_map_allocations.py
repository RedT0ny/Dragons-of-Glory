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

def run_visualization():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Dragons of Glory - Territory Allocation Tester")
    clock = pygame.time.Clock()

    # Load country data using a robust path relative to the script location
    current_dir = os.path.dirname(os.path.abspath(__file__))
    yaml_path = os.path.join(current_dir, "..", "data", "countries.yaml")
    
    with open(yaml_path, 'r') as f:
        countries_data = yaml.safe_load(f)

    # Map hexes to colors based on country data
    hex_map = {}
    for cid, data in countries_data.items():
        color_hex = data.get('color', '#808080').lstrip('#')
        color_rgb = tuple(int(color_hex[i:i+2], 16) for i in (0, 2, 4))
        
        for coord in data.get('territories', []):
            if isinstance(coord, list) and len(coord) == 2:
                hex_map[tuple(coord)] = color_rgb

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

        pygame.display.flip()
        clock.tick(30)

    pygame.quit()

if __name__ == "__main__":
    run_visualization()
