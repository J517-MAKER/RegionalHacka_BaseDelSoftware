from config import BASE_DIR
from nicegui import ui


def apply_theme():
    ui.colors(primary='#245f83', secondary='#526575', positive='#357358', negative='#b54b43', warning='#9d7426')
    ui.add_css((BASE_DIR / 'assets/css/app.css').read_text(encoding='utf-8'))
