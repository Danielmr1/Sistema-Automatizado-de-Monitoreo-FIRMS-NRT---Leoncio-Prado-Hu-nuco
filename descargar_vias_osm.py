#!/usr/bin/env python3
"""
=============================================================================
Descarga la red vial REAL desde OpenStreetMap y construye el GeoJSON del AOI.
=============================================================================
El archivo aoi_carreteras_leoncio_prado.geojson del proyecto tenia solo 33
vertices en total, con separaciones de 3 a 16 km entre puntos. Eso no puede
seguir el trazado real de una carretera: las rectas cortan curvas y quebradas,
por eso las lineas no coinciden con la imagen satelital.

Este script consulta la API Overpass de OpenStreetMap, que tiene la geometria
real, recorta las vias al limite provincial y simplifica lo justo para que el
archivo siga siendo manejable en el dashboard.

Uso:
    python descargar_vias_osm.py
    python descargar_vias_osm.py --tolerancia 0.0008   # mas detalle
    python descargar_vias_osm.py --incluir-tracks      # anade caminos rurales
"""

import os
import sys
import json
import time
import argparse
import datetime

import requests

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OVERPASS = "https://overpass-api.de/api/interpreter"
CABECERAS = {
    "User-Agent": "MonitoreoQuemasLeoncioPrado/1.0 (tesis academica)",
    "Accept": "application/json",
}
SALIDA = "aoi_carreteras_leoncio_prado.geojson"
AOI = "aoi_leoncio_prado.geojson"

# Bounding box ampliado de la provincia
BBOX = (-9.65, -76.55, -8.30, -75.55)

TIPOS_BASE = "trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link"
TIPOS_CON_TRACKS = TIPOS_BASE + "|unclassified|track"


def consultar_overpass(tipos):
    query = f"""
[out:json][timeout:300];
(
  way["highway"~"^({tipos})$"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out geom;
"""
    print(f"[OSM] Consultando Overpass ({tipos.split('|')[0]}...)")
    for intento in range(1, 4):
        try:
            r = requests.post(OVERPASS, data={"data": query}, headers=CABECERAS, timeout=320)
            if r.status_code == 200:
                return r.json().get("elements", [])
            print(f"  intento {intento}: HTTP {r.status_code}")
        except Exception as e:
            print(f"  intento {intento}: {e}")
        time.sleep(5)
    raise SystemExit("[Error] No se pudo consultar Overpass tras 3 intentos.")


def cargar_aoi():
    with open(AOI, "r", encoding="utf-8") as f:
        aoi = json.load(f)
    geom = aoi["features"][0]["geometry"]
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    return [poly[0] for poly in geom["coordinates"]]


def dentro(lon, lat, anillos):
    """Point-in-polygon (ray casting) contra el limite provincial."""
    for ring in anillos:
        n = len(ring)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        if inside:
            return True
    return False


def douglas_peucker(puntos, tol):
    """Simplificacion de linea: conserva la forma quitando puntos redundantes."""
    if len(puntos) < 3:
        return puntos
    # Distancia perpendicular al segmento inicio-fin
    (x1, y1), (x2, y2) = puntos[0], puntos[-1]
    dmax, idx = 0.0, 0
    dx, dy = x2 - x1, y2 - y1
    norm = (dx * dx + dy * dy) ** 0.5
    for i in range(1, len(puntos) - 1):
        px, py = puntos[i]
        if norm == 0:
            d = ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
        else:
            d = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / norm
        if d > dmax:
            dmax, idx = d, i
    if dmax > tol:
        izq = douglas_peucker(puntos[:idx + 1], tol)
        der = douglas_peucker(puntos[idx:], tol)
        return izq[:-1] + der
    return [puntos[0], puntos[-1]]


def nombre_via(tags):
    ref = (tags.get("ref") or "").strip()
    nombre = (tags.get("name") or "").strip()
    if ref and nombre:
        return ref, nombre
    if nombre:
        return "", nombre
    return ref, ref or "Vía sin nombre"


def main():
    parser = argparse.ArgumentParser(description="Descarga la red vial real desde OSM")
    parser.add_argument("--salida", default=SALIDA)
    parser.add_argument("--tolerancia", type=float, default=0.0006,
                        help="Tolerancia de simplificacion en grados (~60 m). Menor = mas detalle.")
    parser.add_argument("--incluir-tracks", action="store_true",
                        help="Incluir caminos rurales (unclassified y track)")
    parser.add_argument("--solo-aoi", action="store_true", default=True,
                        help="Recortar al limite provincial (por defecto)")
    args = parser.parse_args()

    if not os.path.exists(AOI):
        raise SystemExit(f"[Error] No existe {AOI}, necesario para recortar.")

    anillos = cargar_aoi()
    elementos = consultar_overpass(TIPOS_CON_TRACKS if args.incluir_tracks else TIPOS_BASE)
    print(f"[OSM] {len(elementos)} vías recibidas")

    features = []
    vertices_orig, vertices_simpl = 0, 0
    por_tipo = {}

    for el in elementos:
        tags = el.get("tags", {}) or {}
        geom = el.get("geometry", []) or []
        if len(geom) < 2:
            continue

        pts = [(g["lon"], g["lat"]) for g in geom]

        # Recortar al AOI: conservar solo los puntos dentro del limite
        dentro_pts = [p for p in pts if dentro(p[0], p[1], anillos)]
        if len(dentro_pts) < 2:
            continue

        vertices_orig += len(dentro_pts)
        simp = douglas_peucker(dentro_pts, args.tolerancia)
        vertices_simpl += len(simp)

        tipo = tags.get("highway", "?")
        por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
        ref, nombre = nombre_via(tags)

        features.append({
            "type": "Feature",
            "properties": {
                "codigo": ref or "SIN-REF",
                "nombre": nombre,
                "categoria": tags.get("highway"),
                "tipo": tags.get("surface") or tags.get("highway"),
                "fuente": "OpenStreetMap (Overpass API)",
            },
            "geometry": {"type": "LineString", "coordinates": simp},
        })

    print(f"[Recorte] {len(features)} tramos dentro de Leoncio Prado")
    print(f"[Detalle] vertices originales: {vertices_orig} -> simplificados: {vertices_simpl} "
          f"({vertices_simpl/vertices_orig*100:.0f} %)")
    print(f"[Tipos] {por_tipo}")

    salida = {
        "type": "FeatureCollection",
        "name": "aoi_carreteras_leoncio_prado",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "metadata": {
            "fuente": "OpenStreetMap, consultado vía Overpass API",
            "fecha_descarga": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
            "licencia": "OpenStreetMap contributors, ODbL",
            "tolerancia_simplificacion": args.tolerancia,
            "incluye_caminos_rurales": args.incluir_tracks,
            "tramos": len(features),
        },
        "features": features,
    }

    if os.path.exists(args.salida):
        respaldo = f"{args.salida}.bak_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.replace(args.salida, respaldo)
        print(f"[Respaldo] {respaldo}")

    with open(args.salida, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False)

    kb = os.path.getsize(args.salida) / 1024
    print(f"\n[Guardado] {args.salida} ({kb:.0f} KB)")
    print(f"\nComparación con el archivo anterior: 33 vertices en total")
    print(f"Archivo nuevo: {vertices_simpl} vertices en {len(features)} tramos")
    print("\nSiguiente paso: recalcular distancias y regenerar el dashboard")
    print("   python reparar_distritos.py")
    print("   python generar_dashboard.py")


if __name__ == "__main__":
    main()
