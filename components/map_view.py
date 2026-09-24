# pyrefly: ignore [missing-import]
from nicegui import ui
import json
import config
from services.cameras_service import get_cameras

# ── Vibrant neon color palette for camera statuses ──────────────────────────
COLORS = {
    'En línea':              '#00F0FF',  # Cyan neón
    'Desconectada':          '#7C8B9A',  # Gris azulado
    'Alerta':                '#FF3D71',  # Rojo neón / magenta
    'Posible coincidencia':  '#FFB800',  # Ámbar intenso
}

# ── Head HTML: Mapbox GL JS + vibrant dark theme styles ─────────────────────
ui.add_head_html("""
<script src='https://api.mapbox.com/mapbox-gl-js/v3.31.0/mapbox-gl.js' crossorigin='anonymous'></script>
<link href='https://api.mapbox.com/mapbox-gl-js/v3.31.0/mapbox-gl.css' rel='stylesheet' crossorigin='anonymous' />
<style>
  /* ── User location marker: teal pulsing dot ── */
  .mapbox-marker-user {
    width: 18px; height: 18px;
    background: radial-gradient(circle, #32788A 0%, #285f6e 100%);
    border: 3px solid rgba(255,255,255,0.9);
    border-radius: 50%;
    box-shadow: 0 0 12px rgba(50,120,138,0.7), 0 0 30px rgba(50,120,138,0.3);
    animation: user-pulse 2s ease-in-out infinite;
  }
  @keyframes user-pulse {
    0%, 100% { box-shadow: 0 0 12px rgba(50,120,138,0.7), 0 0 30px rgba(50,120,138,0.3); transform: scale(1); }
    50%      { box-shadow: 0 0 20px rgba(50,120,138,0.9), 0 0 50px rgba(50,120,138,0.5); transform: scale(1.15); }
  }

  /* ── Camera markers: glowing circles ── */
  .mapbox-marker-camera {
    width: 22px; height: 22px;
    border: 2.5px solid rgba(255,255,255,0.85);
    border-radius: 50%;
    box-shadow: 0 0 8px rgba(0,0,0,0.15), 0 0 16px var(--marker-glow, rgba(50,120,138,0.4));
    transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
    cursor: pointer;
  }
  .mapbox-marker-camera:hover {
    transform: scale(1.3);
    box-shadow: 0 0 14px rgba(0,0,0,0.2), 0 0 28px var(--marker-glow, rgba(50,120,138,0.6));
  }
  .mapbox-marker-camera.selected {
    width: 30px; height: 30px;
    border-width: 3px;
    z-index: 10;
    animation: selected-glow 1.5s ease-in-out infinite;
  }
  @keyframes selected-glow {
    0%, 100% { box-shadow: 0 0 10px rgba(0,0,0,0.15), 0 0 20px var(--marker-glow, rgba(50,120,138,0.5)); }
    50%      { box-shadow: 0 0 18px rgba(0,0,0,0.2), 0 0 40px var(--marker-glow, rgba(50,120,138,0.8)); }
  }

  /* ── Clean light popups ── */
  .mapboxgl-popup-content {
    background: rgba(255, 255, 255, 0.96) !important;
    backdrop-filter: blur(16px) saturate(180%);
    -webkit-backdrop-filter: blur(16px) saturate(180%);
    color: #1E293B !important;
    border-radius: 12px !important;
    padding: 14px 18px !important;
    box-shadow: 0 8px 32px rgba(0,0,0,0.12), 0 0 1px rgba(50,120,138,0.3) !important;
    border: 1px solid rgba(50,120,138,0.25) !important;
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif !important;
    font-size: 13px !important;
  }
  .mapboxgl-popup-content b {
    color: #32788A;
    font-size: 14px;
  }
  .mapboxgl-popup-anchor-bottom .mapboxgl-popup-tip {
    border-top-color: rgba(255, 255, 255, 0.96) !important;
  }
  .mapboxgl-popup-anchor-top .mapboxgl-popup-tip {
    border-bottom-color: rgba(255, 255, 255, 0.96) !important;
  }
  .mapboxgl-popup-anchor-left .mapboxgl-popup-tip {
    border-right-color: rgba(255, 255, 255, 0.96) !important;
  }
  .mapboxgl-popup-anchor-right .mapboxgl-popup-tip {
    border-left-color: rgba(255, 255, 255, 0.96) !important;
  }
  .mapboxgl-popup-close-button {
    color: #64748B !important;
    font-size: 18px !important;
    right: 6px !important;
    top: 4px !important;
  }
  .mapboxgl-popup-close-button:hover {
    color: #32788A !important;
  }

  /* ── Map container border ── */
  .nexo-map {
    position: absolute;
    inset: 0;
    width: 100% !important;
    height: 100% !important;
    box-sizing: border-box;
    border: 2px solid rgb(50,120,138);
    border-radius: 12px;
  }

  /* ── Navigation controls light styling ── */
  .mapboxgl-ctrl-group {
    background: rgba(255,255,255,0.92) !important;
    backdrop-filter: blur(8px);
    border: 1px solid rgba(50,120,138,0.25) !important;
    border-radius: 8px !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.08) !important;
  }
  .mapboxgl-ctrl-group button {
    background: transparent !important;
    border-color: rgba(50,120,138,0.12) !important;
  }
  .mapboxgl-ctrl-group button + button {
    border-top: 1px solid rgba(50,120,138,0.12) !important;
  }
  .mapboxgl-ctrl-group button .mapboxgl-ctrl-icon {
    filter: none;
  }
  .mapboxgl-ctrl-group button:hover .mapboxgl-ctrl-icon {
    filter: brightness(0.6);
  }
  .mapboxgl-ctrl-attrib {
    background: rgba(255,255,255,0.8) !important;
    color: #64748b !important;
    font-size: 10px !important;
  }
  .mapboxgl-ctrl-attrib a { color: #475569 !important; }

  /* ── Map overlay label ── */
  .map-note {
    background: rgba(255,255,255,0.9);
    backdrop-filter: blur(8px);
    color: #32788A;
    padding: 4px 12px;
    border-radius: 6px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.5px;
    border: 1px solid rgba(50,120,138,0.3);
    text-shadow: none;
  }

  /* ── Map legend ── */
  .map-legend {
    position: absolute;
    bottom: 10px;
    left: 10px;
    z-index: 1000;
    background: rgba(255,255,255,0.92);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(50,120,138,0.25);
    border-radius: 10px;
    padding: 10px 14px;
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
  }
  .map-legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: #475569;
    font-weight: 500;
  }
  .map-legend-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    border: 1.5px solid rgba(0,0,0,0.15);
    box-shadow: 0 0 6px var(--dot-glow, rgba(50,120,138,0.5));
  }
</style>
""", shared=True)

# ── Body HTML: map bootstrap with white style ────────────────────────────────
ui.add_body_html("""
<script>
(function () {
  var MEXICO = [[-118.407986, 14.532098], [-86.710405, 32.718655]];
  var views = {}, maps = new Set(), position = null, asked = false;

  var CARTO_LIGHT = {
    version: 8,
    sources: {
      'carto-light': {
        type: 'raster',
        tiles: [
          'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
          'https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
          'https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
          'https://d.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png'
        ],
        tileSize: 256,
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
      }
    },
    layers: [{
      id: 'carto-light-tiles',
      type: 'raster',
      source: 'carto-light',
      minzoom: 0,
      maxzoom: 20
    }]
  };

  function userMarker(map) {
    if (!position) return;
    var dot = document.createElement('div');
    dot.className = 'mapbox-marker-user';
    new mapboxgl.Marker(dot).setLngLat([position.lng, position.lat])
      .setPopup(new mapboxgl.Popup({ offset: 15 }).setHTML(
        '<b>📍 Tu ubicación actual</b><br><span style="color:#64748B">Precisión: ' + position.accuracy + ' m</span>'))
      .addTo(map);
  }

  function drawMarkers(el) {
    (el._nexoMarkers || []).forEach(function (marker) { marker.remove(); });
    el._nexoMarkers = JSON.parse(el.dataset.markers || '[]').map(function (m) {
      var dot = document.createElement('div');
      dot.className = 'mapbox-marker-camera' + (m.selected ? ' selected' : '');
      dot.style.backgroundColor = m.color;
      dot.style.setProperty('--marker-glow', m.color + '80');
      var statusIcon = m.status === 'En línea' ? '🟢' : m.status === 'Alerta' ? '🔴' : m.status === 'Posible coincidencia' ? '🟡' : '⚪';
      var marker = new mapboxgl.Marker(dot).setLngLat([m.lng, m.lat])
        .setPopup(new mapboxgl.Popup({ offset: 25 }).setHTML(
          '<b>' + statusIcon + ' ' + m.id + '</b><br>' +
          '<span style="color:#334155">' + m.name + '</span><br>' +
          '<span style="color:' + m.color + ';font-weight:600;">' + m.status + '</span>'))
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
    
    var token = el.dataset.token && el.dataset.token.trim().length > 10 ? el.dataset.token.trim() : null;
    if (token) {
      mapboxgl.accessToken = token;
    }
    var mapStyle = token ? 'mapbox://styles/mapbox/light-v11' : CARTO_LIGHT;

    var map = new mapboxgl.Map({
      container: el,
      style: mapStyle,
      center: view.center,
      zoom: view.zoom,
      maxBounds: MEXICO
    });
    el._nexoMap = map;
    maps.add(el);
    map.addControl(new mapboxgl.NavigationControl(), 'top-right');
    map.on('moveend', function () { views[key] = { center: map.getCenter().toArray(), zoom: map.getZoom() }; });

    // Handle map resize on load & timers
    function forceResize() {
      try { if (map) map.resize(); } catch(e) {}
    }
    map.on('load', function() {
      forceResize();
      try {
        map.addSource('mexico-border', {
          type: 'geojson',
          data: {
            type: 'Feature',
            geometry: {
              type: 'Polygon',
              coordinates: [[
                [-117.12, 32.53], [-114.72, 32.72], [-111.07, 31.33], [-108.21, 31.33],
                [-106.45, 31.75], [-104.98, 30.60], [-103.30, 28.97], [-102.40, 29.76],
                [-101.40, 29.77], [-100.08, 28.14], [-99.10, 26.39], [-97.14, 25.97],
                [-97.14, 22.88], [-94.81, 18.51], [-92.23, 14.55], [-90.60, 13.93],
                [-88.62, 15.86], [-87.40, 15.60], [-86.71, 17.55], [-87.43, 20.23],
                [-87.53, 21.47], [-90.35, 21.02], [-91.74, 18.68], [-93.55, 18.43],
                [-96.04, 19.07], [-96.56, 19.87], [-97.56, 22.01], [-105.23, 20.63],
                [-105.64, 22.00], [-108.40, 25.17], [-109.94, 27.53], [-112.16, 29.01],
                [-114.57, 31.93], [-117.12, 32.53]
              ]]
            }
          }
        });
        map.addLayer({
          id: 'mexico-border-glow',
          type: 'line',
          source: 'mexico-border',
          paint: {
            'line-color': '#32788A',
            'line-width': 2.5,
            'line-opacity': 0.7,
            'line-blur': 1
          }
        });
      } catch(err) {
        console.warn('Border layer error:', err);
      }
    });

    setTimeout(forceResize, 150);
    setTimeout(forceResize, 500);
    setTimeout(forceResize, 1000);

    drawMarkers(el);
    userMarker(map);
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


def MapView(cameras=None, detections=None, selected=None, on_select=None, height=None):
    """Mapbox map of the cameras with vibrant dark theme. Returns the container."""
    px_height = height if height else 500
    with ui.element('div').classes('map-stage').style(
        f'height:{px_height}px; position:relative; '
        'background: #FFFFFF; '
        'border-radius: 12px; overflow: hidden; '
        'box-shadow: 0 4px 16px rgba(0,0,0,0.08);'):
        container = ui.element('div').classes('nexo-map').style(
            'width:100%;height:100%;border-radius:12px;z-index:0;')
        container.props['data-token'] = config.MAPBOX_TOKEN
        container.props['data-selected'] = selected or ''
        update_map(container, cameras, detections, selected)

        # Legend overlay
        with ui.element('div').classes('map-legend'):
            for label, color in [('En línea', '#00F0FF'), ('Alerta', '#FF3D71'),
                                  ('Coincidencia', '#FFB800'), ('Desconectada', '#7C8B9A'),
                                  ('Tu ubicación', '#0088FF')]:
                with ui.element('div').classes('map-legend-item'):
                    ui.element('div').classes('map-legend-dot').style(
                        f'background:{color}; --dot-glow:{color}80;')
                    ui.label(label)

        ui.label('MAPA INTERACTIVO · MÉXICO').classes('map-note').style(
            'position:absolute;bottom:10px;right:10px;z-index:1000;')
    return container


def update_map(container, cameras=None, detections=None, selected=None):
    """New marker data for an existing map: the markers change, the map and its view stay."""
    container.props['data-markers'] = json.dumps(markers(cameras, detections, selected))


def markers(cameras=None, detections=None, selected=None):
    cameras = get_cameras() if cameras is None else cameras
    detection_list = [event.detection for event in (detections or [])]

    markers_data = []
    for camera in cameras:
        # Interpolamos X,Y (0-100) a Lat,Lng dentro de México
        # Lat: 14.53 a 32.71 -> Rango = 18.18 (y invertido: 100=sur, 0=norte)
        # Lng: -118.4 a -86.7 -> Rango = 31.7
        lat = 32.718655 - (camera.y / 100.0) * 18.186557
        lng = -118.407986 + (camera.x / 100.0) * 31.697581

        detection = next((d for d in reversed(detection_list) if d.camera_id == camera.id), None)
        status = detection.status if detection else camera.status

        # Vibrant neon colors based on status
        if selected == camera.id:
            color = '#A855F7'   # Purple neón for selected
        elif status == 'Validada por operador':
            color = '#22D3EE'   # Cyan bright
        elif status == 'Descartada':
            color = '#64748B'   # Slate gray
        elif detection:
            color = '#FFB800'   # Amber for possible match
        else:
            color = COLORS.get(camera.status, '#00F0FF')

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
