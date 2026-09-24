from nicegui import ui
from components.camera_feed import CameraFeed


def CameraGrid(cameras,columns=2,on_select=None):
    with ui.element('div').classes('camera-grid').style(f'grid-template-columns:repeat({columns},minmax(0,1fr))'):
        for camera in cameras[:columns*columns]:
            CameraFeed(camera,on_select)
