# pyrefly: ignore [missing-import]
from nicegui import ui
import json
import config
from services.cameras_service import get_cameras

COLORS = {'En línea':'#487965','Desconectada':'#8d999f','Alerta':'#b4544c','Posible coincidencia':'#bc9246'}

# Loaded once for every page. Pages refresh their content (the monitor every 15 s), which
# replaces the map container, and a script inside the page would only run on the first
# load. This bootstrap watches the document instead: it initialises every map container
# as soon as it appears, keeps the view the operator left, and frees the WebGL context of
# containers that disappear (browsers only allow a few at a time).
ui.add_head_html("""
<script src='https://api.mapbox.com/mapbox-gl-js/v3.31.0/mapbox-gl.js' crossorigin='anonymous'></script>
<link href='https://api.mapbox.com/mapbox-gl-js/v3.31.0/mapbox-gl.css' rel='stylesheet' crossorigin='anonymous' />
<style>
  .mapbox-marker-user {
    width: 16px; height: 16px;
    background: #4285F4;
    border: 3px solid #fff;
    border-radius: 50%;
    box-shadow: 0 0 0 4px rgba(66,133,244,0.35);
    animation: pulse-ring 1.8s ease-out infinite;
  }
  .mapbox-marker-camera {
    width: 20px; height: 20px;
    border: 2px solid #fff;
    border-radius: 50%;
    box-shadow: 0 2px 4px rgba(0,0,0,0.5);
  }
  .mapbox-marker-camera.selected {
    width: 28px; height: 28px;
    border-width: 3px;
    z-index: 10;
  }
  @keyframes pulse-ring {
    0%   { box-shadow: 0 0 0 0   rgba(66,133,244,0.5); }
    70%  { box-shadow: 0 0 0 12px rgba(66,133,244,0); }
    100% { box-shadow: 0 0 0 0   rgba(66,133,244,0); }
  }
  .mapboxgl-popup-content {
    background: #ffffff;
    color: #333333;
    border-radius: 8px;
    padding: 10px 15px;
    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
  }
  .mapboxgl-popup-anchor-bottom .mapboxgl-popup-tip {
    border-top-color: #ffffff;
  }
</style>
""", shared=True)

ui.add_body_html("""
<script>
(function () {
  var MEXICO = [[-118.407986, 14.532098], [-86.710405, 32.718655]];  // south-west, north-east
  var views = {}, maps = new Set(), position = null, asked = false;

  function userMarker(map) {
    if (!position) return;
    var dot = document.createElement('div');
    dot.className = 'mapbox-marker-user';
    new mapboxgl.Marker(dot).setLngLat([position.lng, position.lat])
      .setPopup(new mapboxgl.Popup({ offset: 15 }).setHTML(
        '<b>Tu ubicación actual</b><br>Precisión: ' + position.accuracy + ' m'))
      .addTo(map);
  }

  function drawMarkers(el) {
    (el._nexoMarkers || []).forEach(function (marker) { marker.remove(); });
    el._nexoMarkers = JSON.parse(el.dataset.markers || '[]').map(function (m) {
      var dot = document.createElement('div');
      dot.className = 'mapbox-marker-camera' + (m.selected ? ' selected' : '');
      dot.style.backgroundColor = m.color;
      var marker = new mapboxgl.Marker(dot).setLngLat([m.lng, m.lat])
        .setPopup(new mapboxgl.Popup({ offset: 25 }).setHTML(
          '<b>' + m.id + '</b><br>' + m.name + '<br><span style="color:' + m.color + '">' + m.status + '</span>'))
        .addTo(el._nexoMap);
      if (m.selected) marker.togglePopup();
      return marker;
    });
  }

  function init(el) {
    if (el._nexoMap || !el.isConnected) return;
    var data = JSON.parse(el.dataset.markers || '[]');
    var selected = data.find(function (m) { return m.selected; });
    var key = location.pathname + location.search + '|' + (el.dataset.selected || '');
    var view = views[key] || (selected ? { center: [selected.lng, selected.lat], zoom: 10 }
                                       : { center: [-102.5528, 23.6345], zoom: 4.5 });
    mapboxgl.accessToken = el.dataset.token;
    var map = new mapboxgl.Map({ container: el, style: 'mapbox://styles/mapbox/light-v11',
                                 center: view.center, zoom: view.zoom, maxBounds: MEXICO });
    el._nexoMap = map;
    maps.add(el);
    map.addControl(new mapboxgl.NavigationControl(), 'top-right');
    map.on('moveend', function () { views[key] = { center: map.getCenter().toArray(), zoom: map.getZoom() }; });
    drawMarkers(el);
    userMarker(map);
    // Ask once per page. The view stays on the cameras; the position is only a marker.
    if (!asked && navigator.geolocation) {
      asked = true;
      navigator.geolocation.getCurrentPosition(function (pos) {
        position = { lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: Math.round(pos.coords.accuracy) };
        maps.forEach(function (other) { if (other._nexoMap) userMarker(other._nexoMap); });
      }, function (err) { console.warn('Geolocalización no disponible:', err.message); },
      { enableHighAccuracy: true, timeout: 10000 });
    }
  }

  function sweep() {
    maps.forEach(function (el) {
      if (!el.isConnected) { el._nexoMap.remove(); el._nexoMap = null; maps.delete(el); }
    });
    document.querySelectorAll('.nexo-map').forEach(init);
  }

  var pending = false;
  new MutationObserver(function (mutations) {
    // New camera data for a live map: repaint the markers, keep the map (see update_map).
    mutations.forEach(function (m) {
      if (m.type === 'attributes' && m.target._nexoMap) drawMarkers(m.target);
    });
    if (pending) return;
    pending = true;
    setTimeout(function () { pending = false; if (typeof mapboxgl !== 'undefined') sweep(); }, 50);
  }).observe(document.documentElement, { childList: true, subtree: true,
                                         attributes: true, attributeFilter: ['data-markers'] });
  (function wait() { if (typeof mapboxgl === 'undefined') { setTimeout(wait, 150); return; } sweep(); })();
})();
</script>
""", shared=True)


def MapView(cameras=None,detections=None,selected=None,on_select=None,height=None):
    """Mapbox map of the cameras. Returns the container, which update_map can repaint in place."""
    px_height = height if height else 500
    with ui.element('div').classes('map-stage').style(f'height:{px_height}px; position:relative;'):
        # The bootstrap above turns this container into a Mapbox map.
        container = ui.element('div').classes('nexo-map').style('width:100%;height:100%;border-radius:8px;z-index:0;')
        container.props['data-token'] = config.MAPBOX_TOKEN
        container.props['data-selected'] = selected or ''
        update_map(container, cameras, detections, selected)
        ui.label('MAPA INTERACTIVO · MÉXICO').classes('map-note').style('position:absolute;bottom:10px;right:10px;z-index:1000;')
    return container


def update_map(container,cameras=None,detections=None,selected=None):
    """New marker data for an existing map: the markers change, the map and its view stay."""
    container.props['data-markers'] = json.dumps(markers(cameras, detections, selected))


def markers(cameras=None,detections=None,selected=None):
    cameras = get_cameras() if cameras is None else cameras
    detection_list = [event.detection for event in (detections or [])]

    # Preparamos los datos de las cámaras para inyectarlos en JS
    markers_data = []
    for camera in cameras:
        # Interpolamos X,Y (0-100) a Lat,Lng dentro de México
        # Lat: 14.53 a 32.71 -> Rango = 18.18 (y invertido: 100=sur, 0=norte)
        # Lng: -118.4 a -86.7 -> Rango = 31.7
        lat = 32.718655 - (camera.y / 100.0) * 18.186557
        lng = -118.407986 + (camera.x / 100.0) * 31.697581

        detection = next((d for d in reversed(detection_list) if d.camera_id==camera.id), None)
        status = detection.status if detection else camera.status
        color = '#487965' if status == 'Validada por operador' else '#8d999f' if status == 'Descartada' else '#bc9246' if detection else COLORS.get(camera.status, '#000000')
        if selected == camera.id:
            color = '#245f83'

        markers_data.append({
            'id': camera.id,
            'name': camera.name,
            'lat': lat,
            'lng': lng,
            'status': status,
            'color': color,
            'selected': selected == camera.id
        })
    return markers_data
