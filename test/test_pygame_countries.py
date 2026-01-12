import pygame
import yaml
import math
import os

# Configuration for the hexagonal grid
HEX_RADIUS = 12.2
MAP_WIDTH = 65  # Max col observed in yaml + buffer
MAP_HEIGHT = 53 # Max row observed in yaml + buffer
SCREEN_WIDTH = 1600
SCREEN_HEIGHT = 1000

def get_hex_center(col, row, radius):
    """Calculates pixel center for a pointy-top hex using odd-r offset coordinates."""
    x = radius * math.sqrt(3) * (col + 0.5 * (row & 1))
    y = radius * 3/2 * row
    # Adjust these offsets to align the grid to the scaled image
    return int(x + 30), int(y + 20)

def draw_hexagon(surface, color, center, radius):
    """Draws a single pointy-top hexagon. Color can be (R,G,B,A)."""
    points = []
    for i in range(6):
        angle_deg = 60 * i - 30
        angle_rad = math.pi / 180 * angle_deg
        points.append((center[0] + radius * math.cos(angle_rad),
                       center[1] + radius * math.sin(angle_rad)))
    
    pygame.draw.polygon(surface, color, points)
    border_color = (40, 40, 40, color[3]) if len(color) > 3 else (40, 40, 40)
    pygame.draw.polygon(surface, border_color, points, 1)

def draw_location_symbol(surface, center, loc_type, is_capital):
    """Draws a symbol representing the type of location."""
    size = 6
    white = (255, 255, 255, 255)
    if loc_type == 'city':
        rect = pygame.Rect(center[0] - size//2, center[1] - size//2, size, size)
        pygame.draw.rect(surface, white, rect)
    elif loc_type == 'fortress':
        pts = [(center[0], center[1] - size), (center[0] + size, center[1]), 
               (center[0], center[1] + size), (center[0] - size, center[1])]
        pygame.draw.polygon(surface, white, pts)
    elif loc_type == 'port':
        pygame.draw.circle(surface, white, center, size // 2 + 1)
    else:
        pts = [(center[0], center[1] - size), (center[0] - size, center[1] + size), 
               (center[0] + size, center[1] + size)]
        pygame.draw.polygon(surface, white, pts)
    
    if is_capital:
        pygame.draw.circle(surface, (255, 215, 0, 255), (center[0], center[1] - size - 2), 2)

def run_visualization():
    pygame.init()
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    yaml_path = os.path.join(current_dir, "..", "data", "countries.yaml")
    map_path = os.path.join(current_dir, "..", "assets", "img", "test_map.png")

    # Load and Scale the Map
    try:
        raw_bg = pygame.image.load(map_path)
        img_rect = raw_bg.get_rect()
        
        # Calculate scaling to fit screen while maintaining aspect ratio
        ratio = min(SCREEN_WIDTH / img_rect.width, SCREEN_HEIGHT / img_rect.height)
        new_size = (int(img_rect.width * ratio), int(img_rect.height * ratio))
        
        bg_image = pygame.transform.smoothscale(raw_bg, new_size)
        display_width, display_height = new_size
    except pygame.error:
        print(f"Error: Could not find map image at {map_path}")
        return

    screen = pygame.display.set_mode((display_width, display_height))
    pygame.display.set_caption("Dragons of Glory - Scaled Map Overlay")
    clock = pygame.time.Clock()

    try:
        with open(yaml_path, 'r') as f:
            countries_data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: Could not find {yaml_path}")
        return

    hex_map = {}
    location_map = {}
    
    for cid, data in countries_data.items():
        color_hex = data.get('color', '#808080').lstrip('#')
        color_rgb = tuple(int(color_hex[i:i+2], 16) for i in (0, 2, 4))
        capital_id = data.get('capital_id')
    
        for coord in data.get('territories', []):
            if isinstance(coord, list) and len(coord) == 2:
                hex_map[tuple(coord)] = color_rgb
        
        for loc_id, loc_info in data.get('locations', {}).items():
            coords = tuple(loc_info.get('coords', []))
            if coords:
                location_map[coords] = {
                    'type': loc_info.get('type', 'city'),
                    'is_capital': (loc_id == capital_id)
                }

    overlay = pygame.Surface((display_width, display_height), pygame.SRCALPHA)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        screen.blit(bg_image, (0, 0))
        overlay.fill((0, 0, 0, 0)) 

        for row in range(MAP_HEIGHT):
            for col in range(MAP_WIDTH):
                center = get_hex_center(col, row, HEX_RADIUS)
                if (col, row) in hex_map:
                    color = hex_map[(col, row)]
                    draw_hexagon(overlay, (*color, 250), center, HEX_RADIUS)
                else:
                    draw_hexagon(overlay, (200, 200, 200, 30), center, HEX_RADIUS)

        for coords, loc in location_map.items():
            center = get_hex_center(coords[0], coords[1], HEX_RADIUS)
            draw_location_symbol(overlay, center, loc['type'], loc['is_capital'])

        screen.blit(overlay, (0, 0))
        pygame.display.flip()
        clock.tick(30)

    pygame.quit()

if __name__ == "__main__":
    run_visualization()
