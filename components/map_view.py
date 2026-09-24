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

# ── Body HTML: mapa blanco de Mexico, delimitado con su frontera real ─────────
ui.add_body_html("""
<script>
(function () {
  // Rectángulo que contiene a México con un poco de margen: el mapa no sale de aquí.
  var MEXICO = [[-118.6, 14.3], [-86.5, 32.9]];
  var LIMITS = [[-126, 9.5], [-79, 37.5]];
  var TEAL = 'rgb(50,120,138)';
  // Vista mundial de fronteras (la que usan los ejemplos de Mapbox).
  var WORLDVIEW = ['any', ['==', 'all', ['get', 'worldview']], ['in', 'US', ['get', 'worldview']]];
  var views = {}, maps = new Set(), position = null, asked = false;

  // Respaldo sin token: teselas claras de CARTO (sin máscara de fronteras).
  var CARTO_LIGHT = {
    version: 8,
    sources: { 'carto-light': { type: 'raster', tileSize: 256,
      tiles: ['a', 'b', 'c', 'd'].map(function (s) { return 'https://' + s + '.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png'; }),
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO' } },
    layers: [{ id: 'carto-light-tiles', type: 'raster', source: 'carto-light' }]
  };

  // Mapa blanco: tierra blanca, agua gris azulado muy tenue, sin parques ni relieve, etiquetas en español.
  function whiten(map) {
    map.getStyle().layers.forEach(function (layer) {
      var id = layer.id;
      try {
        if (layer.type === 'background') map.setPaintProperty(id, 'background-color', '#ffffff');
        else if (id === 'land' || id.indexOf('landcover') === 0) map.setPaintProperty(id, 'background-color', '#ffffff');
        if (layer.type === 'fill' && id.indexOf('water') === 0) map.setPaintProperty(id, 'fill-color', '#eaf2f4');
        if (/^(landuse|national-park|hillshade|landcover|land-structure)/.test(id)) map.setLayoutProperty(id, 'visibility', 'none');
        if (/^admin-0-boundary/.test(id)) map.setLayoutProperty(id, 'visibility', 'none');  // la sustituye el contorno de México
        if (layer.type === 'symbol' && layer.layout && layer.layout['text-field'])
          map.setLayoutProperty(id, 'text-field', ['coalesce', ['get', 'name_es'], ['get', 'name']]);
      } catch (e) { /* capa sin esa propiedad */ }
    });
  }

  // Delimitación: todo lo que no es México queda en blanco y México lleva su contorno real.
  function delimitMexico(map) {
    if (map.getSource('paises')) return;
    map.addSource('paises', { type: 'vector', url: 'mapbox://mapbox.country-boundaries-v1' });
    map.addLayer({ id: 'fuera-de-mexico', type: 'fill', source: 'paises', 'source-layer': 'country_boundaries',
      filter: ['all', ['!=', ['get', 'iso_3166_1'], 'MX'], WORLDVIEW],
      paint: { 'fill-color': '#ffffff', 'fill-opacity': 1 } });
    map.addLayer({ id: 'mexico-relleno', type: 'fill', source: 'paises', 'source-layer': 'country_boundaries',
      filter: ['all', ['==', ['get', 'iso_3166_1'], 'MX'], WORLDVIEW],
      paint: { 'fill-color': TEAL, 'fill-opacity': 0.03 } });
    map.addLayer({ id: 'mexico-contorno', type: 'line', source: 'paises', 'source-layer': 'country_boundaries',
      filter: ['all', ['==', ['get', 'iso_3166_1'], 'MX'], WORLDVIEW],
      layout: { 'line-join': 'round' },
      paint: { 'line-color': TEAL, 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 1.6, 8, 3] } });
  }

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
    if (el._nexoMap || !el.isConnected || !el.clientWidth) return;
    var data = JSON.parse(el.dataset.markers || '[]');
    var selected = data.find(function (m) { return m.selected; });
    var key = location.pathname + location.search + '|' + (el.dataset.selected || '');
    var token = (el.dataset.token || '').trim();
    if (token.length > 10) mapboxgl.accessToken = token;
    var useMapbox = token.length > 10;

    var options = {
      container: el,
      style: useMapbox ? 'mapbox://styles/mapbox/light-v11' : CARTO_LIGHT,
      maxBounds: LIMITS,
      minZoom: 3.2,
      renderWorldCopies: false,
      attributionControl: true
    };
    var saved = views[key];
    if (saved) { options.center = saved.center; options.zoom = saved.zoom; }
    else if (selected) { options.center = [selected.lng, selected.lat]; options.zoom = 9; }
    else { options.bounds = MEXICO; options.fitBoundsOptions = { padding: 24 }; }

    var map = new mapboxgl.Map(options);
    el._nexoMap = map;
    maps.add(el);
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('moveend', function () { views[key] = { center: map.getCenter().toArray(), zoom: map.getZoom() }; });
    map.on('style.load', function () {
      if (!useMapbox) return;
      whiten(map);
      try { delimitMexico(map); } catch (err) { console.warn('Delimitación de México:', err); }
    });
    map.on('error', function (e) { console.warn('Mapbox:', e && e.error ? e.error.message : e); });

    // El contenedor puede medir 0 px al crearse (pestañas, paneles): se ajusta cuando cambia de tamaño.
    if (window.ResizeObserver) {
      new ResizeObserver(function () { try { map.resize(); } catch (e) {} }).observe(el);
    }

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
  // Un mapa que se creó oculto (0 px) se inicia en cuanto aparece.
  setInterval(function () { if (typeof mapboxgl !== 'undefined') sweep(); }, 1000);
  (function wait() { if (typeof mapboxgl === 'undefined') { setTimeout(wait, 150); return; } sweep(); })();
})();
</script>
""", shared=True)


def MapView(cameras=None, detections=None, selected=None, on_select=None, height=None):
    """Mapa blanco de México (Mapbox) con las cámaras. Devuelve el contenedor."""
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
        lat = camera.lat if getattr(camera, 'lat', None) is not None else 32.718655 - (camera.y / 100.0) * 18.186557
        lng = camera.lng if getattr(camera, 'lng', None) is not None else -118.407986 + (camera.x / 100.0) * 31.697581

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
