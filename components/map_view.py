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
  /* ── Tu ubicación: punto azul parpadeante con onda expansiva ──
     Mapbox coloca cada marcador con `transform` en su elemento raíz. Si la animación
     también usara transform en la raíz, lo sobrescribiría y el punto saltaría a una
     esquina: por eso sólo se animan los hijos. */
  .mapbox-marker-user { width: 24px; height: 24px; cursor: pointer; z-index: 20; }
  .mapbox-marker-user .user-ring,
  .mapbox-marker-user .user-core { position: absolute; border-radius: 50%; pointer-events: none; }
  .mapbox-marker-user .user-ring {
    inset: 0;
    background: rgba(0,136,255,0.45);
    animation: user-ring 1.6s ease-out infinite;
  }
  .mapbox-marker-user .user-core {
    left: 5px; top: 5px; width: 14px; height: 14px;
    background: #0088FF;
    border: 2.5px solid #ffffff;
    box-sizing: border-box;
    box-shadow: 0 0 8px rgba(0,136,255,0.9);
    animation: user-blink 1s ease-in-out infinite;
  }
  @keyframes user-ring {
    0%   { transform: scale(0.5); opacity: 0.9; }
    100% { transform: scale(2.8); opacity: 0; }
  }
  @keyframes user-blink {
    0%, 100% { opacity: 1; }
    50%      { opacity: 0.25; }
  }

  /* ── Aviso de ubicación sobre el mapa ── */
  .map-locate {
    position: absolute; top: 10px; left: 10px; z-index: 1000;
    display: flex; align-items: center; gap: 6px;
    background: rgba(255,255,255,0.94);
    border: 1px solid rgba(50,120,138,0.3);
    border-radius: 8px;
    padding: 5px 10px;
    font-size: 11px; font-weight: 500; color: #334155;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    cursor: default; user-select: none;
  }
  .map-locate.ready { cursor: pointer; }
  .map-locate.ready:hover { border-color: #0088FF; }
  .map-locate .locate-dot { width: 8px; height: 8px; border-radius: 50%; background: #94a3b8; }
  .map-locate.ready .locate-dot { background: #0088FF; animation: user-blink 1s ease-in-out infinite; }
  .map-locate.denied .locate-dot { background: #ef4444; }

  /* ── Camera markers: glowing circles ── */
  .mapbox-marker-camera {
    width: 22px; height: 22px;
    border: 2.5px solid rgba(255,255,255,0.85);
    border-radius: 50%;
    box-shadow: 0 0 8px rgba(0,0,0,0.15), 0 0 16px var(--marker-glow, rgba(50,120,138,0.4));
    /* Nunca `transition: all` ni `transform` aquí: Mapbox mueve el marcador con transform y
       el marcador se quedaría atrás al desplazar el mapa. */
    transition: box-shadow 0.2s ease, width 0.2s ease, height 0.2s ease;
    cursor: pointer;
  }
  .mapbox-marker-camera:hover {
    box-shadow: 0 0 0 4px rgba(255,255,255,0.9), 0 0 28px var(--marker-glow, rgba(50,120,138,0.6));
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
  var views = {}, maps = new Set(), position = null, watching = false;
  // 'locating' · 'ready' · 'denied' · 'unavailable'
  var locateState = navigator.geolocation ? 'locating' : 'unavailable', locateError = '';

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
        // Las etiquetas se dibujan encima de todo, también de la máscara blanca: los nombres de
        // lugares y calles de otros países se filtran aquí (el Golfo y el Pacífico se conservan).
        if (layer.type === 'symbol' && (layer['source-layer'] === 'place_label' || layer['source-layer'] === 'road')) {
          var onlyMexico = ['==', ['get', 'iso_3166_1'], 'MX'];
          map.setFilter(id, layer.filter ? ['all', layer.filter, onlyMexico] : onlyMexico);
        }
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

  function popupHtml() {
    return '<b>📍 Tu ubicación actual</b><br><span style="color:#64748B">Precisión: ±' +
           position.accuracy + ' m</span>';
  }

  // Un solo marcador por mapa; cada nueva lectura sólo lo mueve.
  function userMarker(el) {
    if (!position || !el._nexoMap) return;
    if (!el._nexoUser) {
      var dot = document.createElement('div');
      dot.className = 'mapbox-marker-user';
      dot.innerHTML = '<span class="user-ring"></span><span class="user-core"></span>';
      el._nexoUser = new mapboxgl.Marker({ element: dot, anchor: 'center' })
        .setLngLat([position.lng, position.lat])
        .setPopup(new mapboxgl.Popup({ offset: 16 }).setHTML(popupHtml()))
        .addTo(el._nexoMap);
    } else {
      el._nexoUser.setLngLat([position.lng, position.lat]);
      el._nexoUser.getPopup().setHTML(popupHtml());
    }
  }

  function locateChip(el) {
    var host = el.parentElement;
    if (!host) return;
    var chip = host.querySelector(':scope > .map-locate');
    if (!chip) {
      chip = document.createElement('div');
      chip.className = 'map-locate';
      chip.innerHTML = '<span class="locate-dot"></span><span class="locate-text"></span>';
      chip.addEventListener('click', function () {
        if (position && el._nexoMap) el._nexoMap.flyTo({ center: [position.lng, position.lat], zoom: 12 });
      });
      host.appendChild(chip);
    }
    var text = {
      locating: 'Obteniendo tu ubicación…',
      ready: position ? 'Tu ubicación · ±' + (position ? position.accuracy : 0) + ' m · centrar' : '',
      denied: 'Ubicación bloqueada: permítela en el candado de la barra de direcciones',
      unavailable: 'Ubicación no disponible' + (locateError ? ': ' + locateError : '')
    }[locateState];
    chip.className = 'map-locate ' + locateState;
    chip.title = locateState === 'ready' ? 'Centrar el mapa en tu ubicación' : '';
    chip.querySelector('.locate-text').textContent = text;
  }

  function refreshLocation() {
    maps.forEach(function (el) { userMarker(el); locateChip(el); });
  }

  // Seguimiento continuo: la primera lectura llega rápido (red/Wi-Fi) y luego se afina.
  function startWatching() {
    if (watching || !navigator.geolocation) return;
    watching = true;
    navigator.geolocation.watchPosition(function (pos) {
      position = { lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: Math.round(pos.coords.accuracy) };
      locateState = 'ready';
      refreshLocation();
    }, function (err) {
      if (position) return;  // conservar la última lectura buena
      locateState = err.code === 1 ? 'denied' : 'unavailable';
      locateError = err.code === 3 ? 'tiempo agotado' : (err.code === 2 ? 'sin señal de posición' : '');
      console.warn('Geolocalización:', err.message);
      refreshLocation();
    }, { enableHighAccuracy: false, maximumAge: 30000, timeout: 20000 });
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
    userMarker(el);
    locateChip(el);
    startWatching();
  }

  function sweep() {
    maps.forEach(function (el) {
      if (!el.isConnected) { el._nexoMap.remove(); el._nexoMap = null; el._nexoUser = null; maps.delete(el); }
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
