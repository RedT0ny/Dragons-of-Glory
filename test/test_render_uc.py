from PySide6.QtWidgets import QApplication, QGraphicsScene
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtCore import QRectF
import sys
import os

app = QApplication.instance() or QApplication(sys.argv)

class DummyUnit:
    def __init__(self):
        self.id = 'blode_ogre_inf_2'
        self.allegiance = 'evil'
        self.combat_rating = 2
        self.tactical_rating = 0
        self.movement = 1
        self.passengers = []
        self.is_transported = False
        self.transport_host = None
        self.unit_type = None
        self.race = None
        self.land = None

# Ensure project root is on path so `src` package is importable
proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)

from src.gui.map_items import UnitCounter

unit = DummyUnit()
uc = UnitCounter(unit, QColor('red'))

scene = QGraphicsScene()
scene.addItem(uc)

# Render scene centered on unit
pix = QPixmap(100, 100)
pix.fill()

painter = QPainter(pix)
painter.setRenderHint(QPainter.Antialiasing)
# source rect matches unit boundingRect centered at 0,0
source_rect = uc.boundingRect()
# Use scene.render with QRectF objects
scene.render(painter, target=QRectF(0, 0, pix.width(), pix.height()), source=source_rect)
painter.end()

out = os.path.join(os.path.dirname(__file__), '../tools/unit_render.png')
img = pix.toImage()
img.save(out)
print('Saved unit render to', out)
