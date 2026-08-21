#!/usr/bin/env python3
"""
=============================================================================
Sistema Automatizado de Monitoreo FIRMS NRT - Provincia de Leoncio Prado, Huánuco
Proyecto de Tesis: Detección NRT, Validación en Campo (Ground Truthing) y Accesibilidad
=============================================================================
"""

import os
import sys
import io
import json
import math
import datetime
import requests
import pandas as pd

# ---------------------------------------------------------------------------
# 1. CONFIGURACIÓN Y PARÁMETROS DEL SISTEMA (SOLO NRT)
# ---------------------------------------------------------------------------
FIRMS_API_KEY = os.getenv("FIRMS_API_KEY", "e10ebd29b9c7a2e16d862032a9f824a2")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Bounding Box ampliado oficial Leoncio Prado (minLon, minLat, maxLon, maxLat)
BBOX = "-76.55,-9.65,-75.55,-8.30"
DAY_RANGE = "2"  # Ventana temporal de 2 días (recomendada para campo)

# Sensores NRT exclusivos (Near Real-Time para detección inmediata)
SOURCES = ["MODIS_NRT", "VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"]

# Rutas de archivos espaciales y de base de datos
AOI_GEOJSON_PATH = "aoi_leoncio_prado.geojson"
HISTORICAL_CSV_PATH = "historico_leoncio_prado_2026.csv"


# ---------------------------------------------------------------------------
# 2. DESCARGA DE DATOS DESDE FIRMS API (MODO NRT)
# ---------------------------------------------------------------------------
def fetch_firms_data(source: str, api_key: str, bbox: str, day_range: str, start_date: str = None) -> pd.DataFrame:
    """Descarga los focos de calor NRT en formato CSV para un sensor específico."""
    if start_date:
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{api_key}/{source}/{bbox}/{day_range}/{start_date}"
    else:
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{api_key}/{source}/{bbox}/{day_range}"
    
    print(f"[FIRMS API NRT] Consultando sensor: {source} (Rango: {day_range} días{f' desde {start_date}' if start_date else ''})...")
    
    try:
        response = requests.get(url, timeout=35)
        response.raise_for_status()
        
        content = response.text.strip()
        if not content or "Invalid MAP_KEY" in content or "Error" in content:
            print(f"[FIRMS Warning] Respuesta no válida para {source}: {content[:120]}")
            return pd.DataFrame()
            
        df = pd.read_csv(io.StringIO(content))
        if not df.empty:
            df["source_sensor"] = source
            print(f"[FIRMS API] ✓ {len(df)} registros crudos descargados de {source}.")
        else:
            print(f"[FIRMS API] 0 registros para {source}.")
        return df

    except Exception as e:
        print(f"[FIRMS Error] Error al descargar datos de {source}: {e}", file=sys.stderr)
        return pd.DataFrame()


def download_all_sources(day_range: str = DAY_RANGE, start_date: str = None) -> pd.DataFrame:
    """Descarga y unifica las detecciones NRT de todos los sensores configurados."""
    dfs = []
    for source in SOURCES:
        df_source = fetch_firms_data(source, FIRMS_API_KEY, BBOX, day_range, start_date)
        if not df_source.empty:
            dfs.append(df_source)
            
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


# ---------------------------------------------------------------------------
# 3. FILTRADO ESPACIAL ESTRICTO (Point in Polygon Exacto)
# ---------------------------------------------------------------------------
def _point_in_polygon(x: float, y: float, poly: list) -> bool:
    """Algoritmo de Ray Casting de alta velocidad para Point-in-Polygon."""
    n = len(poly)
    inside = False
    p1x, p1y = poly[0]
    for i in range(n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def apply_spatial_filter(df: pd.DataFrame, geojson_path: str) -> pd.DataFrame:
    """Conserva únicamente las coordenadas que caen dentro del límite oficial de Leoncio Prado."""
    if df.empty:
        return df

    if not os.path.exists(geojson_path):
        print(f"[Filtro Espacial Warning] No se encontró {geojson_path}. Omitiendo recorte estricto.")
        return df

    try:
        with open(geojson_path, "r", encoding="utf-8") as f:
            aoi_data = json.load(f)

        features = aoi_data.get("features", [])
        if not features:
            return df

        # Extraer coordenadas del polígono
        geom = features[0].get("geometry", {})
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])

        rings = []
        if gtype == "Polygon":
            rings.append(coords[0])
        elif gtype == "MultiPolygon":
            for poly in coords:
                rings.append(poly[0])

        valid_rows = []
        for idx, row in df.iterrows():
            lon = float(row["longitude"])
            lat = float(row["latitude"])
            is_inside = False
            for ring in rings:
                if _point_in_polygon(lon, lat, ring):
                    is_inside = True
                    break
            if is_inside:
                valid_rows.append(idx)

        filtered_df = df.loc[valid_rows].copy()
        print(f"[Filtro Espacial] De {len(df)} detecciones en BBOX, {len(filtered_df)} caen ESTRICTAMENTE dentro de Leoncio Prado.")
        return filtered_df

    except Exception as e:
        print(f"[Filtro Espacial Error] Error durante la intersección espacial: {e}")
        return df


# ---------------------------------------------------------------------------
# 4. FILTRADO ESTADÍSTICO POR CONFIANZA DE SENSOR
# ---------------------------------------------------------------------------
def apply_confidence_filter(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica umbrales estadísticos de calidad según el tipo de sensor:
    - MODIS: confidence >= 60
    - VIIRS: confidence in ['n', 'h', 'nominal', 'high']
    """
    if df.empty:
        return df

    valid_mask = []
    for _, row in df.iterrows():
        source = str(row.get("source_sensor", "")).upper()
        confidence = str(row.get("confidence", "")).strip().lower()
        
        if "MODIS" in source:
            try:
                conf_val = float(confidence)
                valid_mask.append(conf_val >= 60.0)
            except (ValueError, TypeError):
                valid_mask.append(False)
        elif "VIIRS" in source:
            valid_mask.append(confidence in ["n", "h", "nominal", "high"])
        else:
            valid_mask.append(True)
            
    filtered_df = df[valid_mask].copy()
    print(f"[Filtro Estadístico] {len(filtered_df)} anomalías superaron los umbrales de confianza requeridos.")
    return filtered_df


# ---------------------------------------------------------------------------
# 5. CÁLCULO DE ACCESIBILIDAD VIAL, COSTOS Y TIEMPO ESTIMADO A CAMPO
# ---------------------------------------------------------------------------
def _haversine_distance_km(lat1, lon1, lat2, lon2):
    """Calcula la distancia geodésica exacta en kilómetros entre dos puntos."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _point_to_segment_distance_km(plat, plon, lat1, lon1, lat2, lon2):
    """Calcula la distancia perpendicular mínima en km desde un punto a un segmento de carretera."""
    # Convertir a coordenadas planas locales centradas
    cos_lat = math.cos(math.radians(plat))
    px = plon * 111.32 * cos_lat
    py = plat * 110.57
    x1 = lon1 * 111.32 * cos_lat
    y1 = lat1 * 110.57
    x2 = lon2 * 111.32 * cos_lat
    y2 = lat2 * 110.57

    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.sqrt((px - x1)**2 + (py - y1)**2)

    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.sqrt((px - proj_x)**2 + (py - proj_y)**2)


def calculate_road_accessibility_and_costs(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula la distancia a la carretera más cercana, tiempo de marcha y costo en Soles."""
    if df.empty:
        return df

    # Definición de los ejes viales estructurados de Leoncio Prado
    road_segments = [
        # PE-5N: Eje Longitudinal de la Selva Norte (Fernando Belaúnde Terry)
        {"code": "PE-5N", "name": "Longitudinal Selva Norte (Tingo María - Aucayacu - Pucayacu)", "base_cost": 5, "coords": [
            (-9.5500, -75.8900), (-9.4500, -75.9200), (-9.3800, -75.9450), (-9.3250, -75.9720),
            (-9.2950, -75.9960), (-9.2800, -75.9750), (-9.1820, -75.9320), (-9.0800, -75.9650),
            (-9.0100, -76.0050), (-8.9240, -76.0410), (-8.8400, -76.0850), (-8.7510, -76.1240),
            (-8.6900, -76.1550), (-8.6200, -76.1950)
        ]},
        # PE-18A: Carretera Federico Basadre (Tingo María - Pumahuasi - Pucallpa)
        {"code": "PE-18A", "name": "Federico Basadre (Tingo María - Pumahuasi - San Alejandro)", "base_cost": 15, "coords": [
            (-9.2950, -75.9960), (-9.2850, -75.9500), (-9.2600, -75.8900), (-9.2550, -75.8210),
            (-9.2100, -75.7610), (-9.1500, -75.6800), (-9.0500, -75.5800)
        ]},
        # HU-104: Carretera Departamental Tingo María - Monzón
        {"code": "HU-104", "name": "Carretera Departamental Tingo María - Valle del Monzón", "base_cost": 25, "coords": [
            (-9.2950, -75.9960), (-9.2700, -76.0250), (-9.2400, -76.0700), (-9.2000, -76.1200),
            (-9.1400, -76.1850), (-9.0800, -76.2500)
        ]}
    ]

    min_distances = []
    nearest_names = []
    access_levels = []
    travel_times = []
    travel_costs = []
    gmaps_links = []

    for _, row in df.iterrows():
        lat = float(row["latitude"])
        lon = float(row["longitude"])

        best_dist = 999.0
        best_road = "PE-5N"

        for road in road_segments:
            pts = road["coords"]
            for i in range(len(pts) - 1):
                d = _point_to_segment_distance_km(lat, lon, pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])
                if d < best_dist:
                    best_dist = d
                    best_road = f"{road['code']} ({road['name']})"

        dist_km = round(best_dist, 2)
        min_distances.append(dist_km)
        nearest_names.append(best_road)

        if dist_km <= 1.0:
            access_levels.append("ALTA")
            travel_times.append("< 20 min (A pie / Mototaxi)")
            travel_costs.append("S/. 5 - 10")
        elif dist_km <= 3.0:
            access_levels.append("MEDIA")
            travel_times.append("30 - 60 min (Trocha / Caminata)")
            travel_costs.append("S/. 15 - 30")
        else:
            access_levels.append("BAJA / REMOTA")
            travel_times.append("> 1.5 horas (Selva adentro / Bote)")
            travel_costs.append("S/. 40 - 80+")

        gmaps_links.append(f"https://www.google.com/maps/dir/?api=1&destination={lat:.5f},{lon:.5f}")

    df["dist_carretera_km"] = min_distances
    df["carretera_cercana"] = nearest_names
    df["accesibilidad"] = access_levels
    df["tiempo_estimado"] = travel_times
    df["costo_estimado_pen"] = travel_costs
    df["google_maps_url"] = gmaps_links

    print(f"[Accesibilidad Vial] Distancias calculadas a la red de carreteras (Distancia mín: {min(min_distances)} km, máx: {max(min_distances)} km).")
    return df


# ---------------------------------------------------------------------------
# 6. VERIFICACIÓN METEOROLÓGICA (Precipitación Reciente - Open-Meteo API)
# ---------------------------------------------------------------------------
def check_recent_rainfall(df: pd.DataFrame) -> pd.DataFrame:
    """Verifica si llovió en las últimas 24-48h para advertir si la ceniza pudo ser lavada."""
    if df.empty:
        return df

    rain_values = []
    rain_alerts = []

    print("[Meteorología] Verificando precipitación reciente en los puntos...")
    for _, row in df.iterrows():
        lat = float(row["latitude"])
        lon = float(row["longitude"])
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat:.4f}&longitude={lon:.4f}&daily=precipitation_sum&past_days=1&forecast_days=1&timezone=America%2FLima"
        
        try:
            res = requests.get(url, timeout=6)
            if res.status_code == 200:
                data = res.json()
                precip_list = data.get("daily", {}).get("precipitation_sum", [0.0])
                precip_24h = float(precip_list[0]) if precip_list else 0.0
                rain_values.append(precip_24h)
                
                if precip_24h >= 8.0:
                    rain_alerts.append("🌧️ Lluvia fuerte (>8mm): Ceniza probablemente lavada")
                elif precip_24h >= 2.0:
                    rain_alerts.append("🌦️ Lluvia leve (2-8mm): Carbón visible, ceniza dispersa")
                else:
                    rain_alerts.append("☀️ Seco (<2mm): Evidencia intacta para muestreo")
            else:
                rain_values.append(0.0)
                rain_alerts.append("Sin datos meteorológicos")
        except Exception:
            rain_values.append(0.0)
            rain_alerts.append("Sin datos meteorológicos")

    df["lluvia_24h_mm"] = rain_values
    df["alerta_clima_campo"] = rain_alerts
    return df


# ---------------------------------------------------------------------------
# 7. GENERACIÓN DE MAPA INTERACTIVO HTML (Leaflet Nativo de Alta Resolución)
# ---------------------------------------------------------------------------
def generate_interactive_map(df: pd.DataFrame, aoi_path: str, output_html_path: str):
    """Genera un mapa HTML interactivo moderno con imagen satelital, límites y focos."""
    geojson_str = "{}"
    if os.path.exists(aoi_path):
        with open(aoi_path, "r", encoding="utf-8") as f:
            geojson_str = f.read()

    fires_json = df.to_json(orient="records")

    html_template = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Mapa de Focos de Calor - Leoncio Prado</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    body, html {{ margin: 0; padding: 0; height: 100%; width: 100%; font-family: sans-serif; }}
    #map {{ height: 100%; width: 100%; }}
    .legend {{ background: white; padding: 10px; border-radius: 8px; box-shadow: 0 0 15px rgba(0,0,0,0.2); font-size: 12px; line-height: 1.5; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script>
    const map = L.map('map').setView([-9.29, -75.99], 10);

    const esriSatellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      attribution: 'Esri World Imagery'
    }}).addTo(map);

    const osm = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      attribution: 'OpenStreetMap'
    }});

    const esriLabels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      attribution: 'Esri Places'
    }}).addTo(map);

    L.control.layers({{
      "🛰️ Satelital Híbrido": esriSatellite,
      "🗺️ OpenStreetMap": osm
    }}, {{
      "🏷️ Nombres de Poblados": esriLabels
    }}).addTo(map);

    const aoiData = {geojson_str};
    if (aoiData && aoiData.features) {{
      const aoiLayer = L.geoJSON(aoiData, {{
        style: {{ color: '#22c55e', weight: 3.5, opacity: 0.9, fillColor: '#22c55e', fillOpacity: 0.08, dashArray: '5, 5' }}
      }}).addTo(map);
      map.fitBounds(aoiLayer.getBounds(), {{ padding: [20, 20] }});
    }}

    const fires = {fires_json};
    fires.forEach(f => {{
      const isModis = (f.source_sensor || '').includes('MODIS');
      const color = isModis ? '#dc2626' : '#ea580c';
      const marker = L.circleMarker([f.latitude, f.longitude], {{
        radius: isModis ? 8 : 6,
        color: '#ffffff',
        fillColor: color,
        fillOpacity: 0.9,
        weight: 2
      }}).addTo(map);

      marker.bindPopup(`
        <div style="font-size:12px; width:240px; line-height:1.4;">
          <h4 style="margin:0 0 4px 0; color:${{color}};">🔥 Foco de Calor (${{f.source_sensor}})</h4>
          <b>Fecha:</b> ${{f.acq_date}} (${{f.acq_time}} UTC)<br>
          <b>Potencia (FRP):</b> ${{f.frp || 'N/A'}} MW<br>
          <b>Vía cercana:</b> ${{f.carretera_cercana}}<br>
          <b>Distancia:</b> ${{f.dist_carretera_km}} km (${{f.accesibilidad}})<br>
          <b>Costo Est.:</b> ${{f.costo_estimado_pen}}<br>
          <b>Clima 24h:</b> ${{f.alerta_clima_campo || 'Sin lluvia'}}<br>
          <div style="margin-top:8px; text-align:center;">
            <a href="${{f.google_maps_url}}" target="_blank" style="background:#2563eb; color:white; padding:4px 8px; border-radius:4px; text-decoration:none; font-weight:bold; font-size:11px;">
              📍 Navegar en Google Maps
            </a>
          </div>
        </div>
      `);
    }});
  </script>
</body>
</html>"""

    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html_template)
    print(f"[Mapa Interactivo HTML] Guardado en: {output_html_path}")


# ---------------------------------------------------------------------------
# 8. GENERACIÓN DE ARCHIVO KML (Para GPS Offline en Celular / Google Earth)
# ---------------------------------------------------------------------------
def generate_kml(df: pd.DataFrame, output_kml_path: str):
    """Genera un archivo KML estándar para abrir en Google Earth, OruxMaps o Locus Map sin internet."""
    kml_header = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>Focos de Calor NRT - Leoncio Prado</name>
  <description>Detecciones satelitales NASA FIRMS para salida a campo</description>
  <Style id="fire_modis">
    <IconStyle>
      <scale>1.2</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/shapes/firedept.png</href></Icon>
    </IconStyle>
  </Style>
  <Style id="fire_viirs">
    <IconStyle>
      <scale>1.0</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/orange-circle.png</href></Icon>
    </IconStyle>
  </Style>
"""
    kml_footer = """</Document>
</kml>"""

    placemarks = []
    for idx, row in df.iterrows():
        lat = row["latitude"]
        lon = row["longitude"]
        source = str(row.get("source_sensor", "FIRMS"))
        is_modis = "MODIS" in source.upper()
        style = "fire_modis" if is_modis else "fire_viirs"
        
        name = f"Foco #{idx+1} - {row.get('distrito', 'Leoncio Prado')} ({row.get('acq_date', '')})"
        desc = (
            f"Sensor: {source}\n"
            f"Fecha: {row.get('acq_date', '')} {row.get('acq_time', '')} UTC\n"
            f"Confianza: {row.get('confidence', '')}\n"
            f"FRP: {row.get('frp', '')} MW\n"
            f"Vía cercana: {row.get('carretera_cercana', '')} ({row.get('dist_carretera_km', '')} km)\n"
            f"Accesibilidad: {row.get('accesibilidad', '')}\n"
            f"Costo estimado: {row.get('costo_estimado_pen', '')}\n"
            f"Clima 24h: {row.get('alerta_clima_campo', '')}"
        )
        
        pm = f"""  <Placemark>
    <name>{name}</name>
    <description><![CDATA[{desc}]]></description>
    <styleUrl>#{style}</styleUrl>
    <Point>
      <coordinates>{lon},{lat},0</coordinates>
    </Point>
  </Placemark>"""
        placemarks.append(pm)

    full_kml = kml_header + "\n".join(placemarks) + "\n" + kml_footer
    with open(output_kml_path, "w", encoding="utf-8") as f:
        f.write(full_kml)
    print(f"[Archivo KML] Generado para navegación GPS offline: {output_kml_path}")


# ---------------------------------------------------------------------------
# 9. GESTIÓN DEL REGISTRO HISTÓRICO PERSISTENTE
# ---------------------------------------------------------------------------
def update_historical_database(daily_df: pd.DataFrame, historical_path: str):
    """Concatena detecciones al histórico maestro y elimina registros duplicados."""
    if daily_df.empty:
        return

    clean_daily = daily_df.copy()

    if os.path.exists(historical_path):
        try:
            hist_df = pd.read_csv(historical_path)
            combined_df = pd.concat([hist_df, clean_daily], ignore_index=True)
        except Exception as e:
            print(f"[Histórico Warning] Error al leer CSV existente ({e}). Creando nuevo.")
            combined_df = clean_daily.copy()
    else:
        combined_df = clean_daily.copy()

    dedup_cols = ["latitude", "longitude", "acq_date", "acq_time"]
    existing_dedup_cols = [c for c in dedup_cols if c in combined_df.columns]

    initial_len = len(combined_df)
    if existing_dedup_cols:
        combined_df.drop_duplicates(subset=existing_dedup_cols, keep="first", inplace=True)
    
    final_len = len(combined_df)
    combined_df.to_csv(historical_path, index=False)
    print(f"[Histórico Actualizado] {final_len} registros totales guardados ({initial_len - final_len} duplicados removidos).")


# ---------------------------------------------------------------------------
# 10. MÓDULO DE ALERTAS TELEGRAM
# ---------------------------------------------------------------------------
def send_telegram_alert(df: pd.DataFrame, csv_path: str, html_path: str, kml_path: str, date_str: str):
    """Envía un mensaje formateado con accesibilidad, enlaces GPS directos y adjunta CSV, HTML y KML."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram Warning] TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados. Omitiendo envío.")
        return

    total_anomalies = len(df)
    breakdown = df["source_sensor"].value_counts().to_dict()
    breakdown_text = "\n".join([f"  • <b>{sensor}:</b> {count} anomalías" for sensor, count in breakdown.items()])
    
    acc_counts = df["accesibilidad"].value_counts().to_dict() if "accesibilidad" in df.columns else {}
    acc_text = (
        f"  • 🟢 <b>Alta (&lt;1 km):</b> {acc_counts.get('ALTA', 0)} focos (~S/. 5-10)\n"
        f"  • 🟡 <b>Media (1-3 km):</b> {acc_counts.get('MEDIA', 0)} focos (~S/. 15-30)\n"
        f"  • 🔴 <b>Remota (&gt;3 km):</b> {acc_counts.get('BAJA / REMOTA', 0)} focos (>1h caminata)"
    )

    # Enlaces directos a los primeros 3 focos más urgentes/accesibles
    links_text = ""
    top_points = df.head(3)
    for i, (_, r) in enumerate(top_points.iterrows()):
        distr = r.get("distrito", "Leoncio Prado")
        lat, lon = r["latitude"], r["longitude"]
        frp = r.get("frp", "N/A")
        links_text += f"\n  👉 <b>Foco #{i+1} ({distr} - {frp} MW):</b> <a href='https://www.google.com/maps/dir/?api=1&destination={lat:.5f},{lon:.5f}'>Navegar en Google Maps</a>"

    message_text = (
        f"🚨 <b>ALERTA DE FOCOS DE CALOR NRT - LEONCIO PRADO</b> 🚨\n\n"
        f"📅 <b>Fecha del reporte:</b> {date_str}\n"
        f"📍 <b>Área de Tesis:</b> Provincia de Leoncio Prado (Huánuco)\n"
        f"🔥 <b>Total anomalías NRT validadas:</b> <code>{total_anomalies}</code>\n\n"
        f"📊 <b>Desglose por Sensor:</b>\n{breakdown_text}\n\n"
        f"🛣️ <b>Accesibilidad y Costos Estimados de Campo:</b>\n{acc_text}\n"
        f"{links_text}\n\n"
        f"<i>💡 Adjuntos: CSV tabular, Mapa HTML interactivo y archivo KML para GPS offline en celular.</i>"
    )

    base_api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    # 1. Enviar mensaje de texto enriquecido
    try:
        msg_payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message_text, "parse_mode": "HTML", "disable_web_page_preview": True}
        res_msg = requests.post(f"{base_api}/sendMessage", data=msg_payload, timeout=20)
        res_msg.raise_for_status()
        print("[Telegram] Mensaje de alerta enviado exitosamente.")
    except Exception as e:
        print(f"[Telegram Error] Falló el envío del mensaje de texto: {e}", file=sys.stderr)

    # 2. Enviar archivo CSV
    if os.path.exists(csv_path):
        try:
            with open(csv_path, "rb") as f_csv:
                requests.post(
                    f"{base_api}/sendDocument",
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": f"📄 Tabla de coordenadas y accesibilidad: {os.path.basename(csv_path)}"},
                    files={"document": (os.path.basename(csv_path), f_csv, "text/csv")},
                    timeout=30
                ).raise_for_status()
                print(f"[Telegram] CSV {csv_path} enviado.")
        except Exception as e:
            print(f"[Telegram Error] Falló el envío del CSV: {e}", file=sys.stderr)

    # 3. Enviar Mapa interactivo HTML
    if os.path.exists(html_path):
        try:
            with open(html_path, "rb") as f_html:
                requests.post(
                    f"{base_api}/sendDocument",
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": f"🗺️ Mapa interactivo satelital con vías: {os.path.basename(html_path)}"},
                    files={"document": (os.path.basename(html_path), f_html, "text/html")},
                    timeout=30
                ).raise_for_status()
                print(f"[Telegram] HTML {html_path} enviado.")
        except Exception as e:
            print(f"[Telegram Error] Falló el envío del HTML: {e}", file=sys.stderr)

    # 4. Enviar archivo KML para celular
    if os.path.exists(kml_path):
        try:
            with open(kml_path, "rb") as f_kml:
                requests.post(
                    f"{base_api}/sendDocument",
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": f"📍 Archivo KML para Google Earth / GPS Offline: {os.path.basename(kml_path)}"},
                    files={"document": (os.path.basename(kml_path), f_kml, "application/vnd.google-earth.kml+xml")},
                    timeout=30
                ).raise_for_status()
                print(f"[Telegram] KML {kml_path} enviado.")
        except Exception as e:
            print(f"[Telegram Error] Falló el envío del KML: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 11. FUNCIÓN PRINCIPAL / ORQUESTACIÓN
# ---------------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Monitoreo Automatizado FIRMS NRT - Leoncio Prado")
    parser.add_argument("--days", type=str, default=DAY_RANGE, help="Rango de días NRT a consultar (1 a 10). Por defecto: 2")
    parser.add_argument("--date", type=str, default=None, help="Fecha específica de inicio (formato YYYY-MM-DD). Opcional.")
    args = parser.parse_args()

    print("=" * 70)
    print("INICIANDO SISTEMA DE MONITOREO DE QUEMAS NRT - LEONCIO PRADO")
    today_str = datetime.datetime.utcnow().strftime("%Y%m%d")
    print(f"Fecha de ejecución UTC: {today_str}")
    print(f"Ventana NRT: {args.days} días{f' desde {args.date}' if args.date else ' (últimos días)'}")
    print(f"Sensores NRT activos: {', '.join(SOURCES)}")
    print("=" * 70)

    if not FIRMS_API_KEY:
        print("[CRITICAL ERROR] Variable de entorno 'FIRMS_API_KEY' no configurada.", file=sys.stderr)
        sys.exit(1)

    raw_df = download_all_sources(day_range=args.days, start_date=args.date)
    if raw_df.empty:
        print("[Fin] No se obtuvieron registros de la API FIRMS en el área consultada.")
        sys.exit(0)

    # 1. Filtro espacial Point-in-Polygon contra el polígono oficial
    spatial_df = apply_spatial_filter(raw_df, AOI_GEOJSON_PATH)
    if spatial_df.empty:
        print("[Fin] No se detectaron anomalías térmicas dentro de los límites de Leoncio Prado.")
        sys.exit(0)

    # 2. Filtro estadístico de calidad (MODIS >= 60, VIIRS nominal/alta)
    final_df = apply_confidence_filter(spatial_df)
    if final_df.empty:
        print("[Fin] Ninguna anomalía superó los umbrales de confianza del proyecto.")
        sys.exit(0)

    # 3. Cálculo de accesibilidad vial métrica y estimación de costos
    final_df = calculate_road_accessibility_and_costs(final_df)

    # 4. Verificación de lluvia reciente (Open-Meteo API)
    final_df = check_recent_rainfall(final_df)

    print(f"\n>>> ¡ALERTA ACTIVADA! {len(final_df)} focos de calor válidos identificados. <<<\n")

    daily_csv_path = f"alertas_{today_str}.csv"
    daily_html_path = f"mapa_{today_str}.html"
    daily_kml_path = f"alertas_{today_str}.kml"

    export_df = final_df.copy()
    export_df.to_csv(daily_csv_path, index=False)
    print(f"[Archivos Diarios] CSV generado: {daily_csv_path}")

    generate_interactive_map(final_df, AOI_GEOJSON_PATH, daily_html_path)
    generate_kml(final_df, daily_kml_path)
    update_historical_database(export_df, HISTORICAL_CSV_PATH)
    send_telegram_alert(final_df, daily_csv_path, daily_html_path, daily_kml_path, today_str)

    print("=" * 70)
    print("PROCESO COMPLETADO EXITOSAMENTE.")
    print("=" * 70)


if __name__ == "__main__":
    main()
