#!/usr/bin/env python3
"""
=============================================================================
Repara metadatos del histórico sin volver a descargar detecciones.
=============================================================================
Motivo: el pipeline (main.py) solo asigna distrito a las detecciones que
descarga en cada corrida (ventana de 1 a 5 días). Los registros que ya estaban
en el histórico nunca pasan por ese paso, así que se quedan con la etiqueta
provisional "Leoncio Prado (distrito no determinado)" aunque el GeoJSON de
distritos ya esté disponible.

Este script recorre el histórico y rellena los campos derivados que estén
pendientes, SIN tocar las coordenadas ni ningún dato de FIRMS.

Campos que repara:
  - distrito            (si falta o tiene la etiqueta provisional)
  - dist_carretera_km   (recalculada con la red vial oficial actual, de 5 tramos)
  - accesibilidad, tiempo_estimado, costo_estimado_pen (derivados de la distancia)

Uso:
    python reparar_distritos.py
    python reparar_distritos.py --historico historico_leoncio_prado_2026.csv
"""

import os
import sys
import json
import shutil
import argparse
import datetime
import importlib.util

import pandas as pd

HIST_PATH = "historico_leoncio_prado_2026.csv"
ETIQUETA_PROVISIONAL = "Leoncio Prado (distrito no determinado)"


def cargar_modulo_main():
    """Importa main.py para reutilizar su lógica de point-in-polygon."""
    spec = importlib.util.spec_from_file_location("main", "main.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def leer_csv(path):
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"[Error] No se pudo leer {path}.")


def main():
    parser = argparse.ArgumentParser(
        description="Repara metadatos del histórico: distrito y distancias viales")
    parser.add_argument("--historico", default=HIST_PATH)
    parser.add_argument("--distritos", default="distritos_leoncio_prado.geojson")
    parser.add_argument("--carreteras", default="aoi_carreteras_leoncio_prado.geojson")
    args = parser.parse_args()

    if not os.path.exists(args.historico):
        raise SystemExit(f"[Error] No existe {args.historico}.")
    if not os.path.exists(args.distritos):
        raise SystemExit(
            f"[Error] No existe {args.distritos}.\n"
            "Descárgalo o genera el archivo de distritos antes de reparar."
        )

    m = cargar_modulo_main()
    distritos = m._load_district_polygons()
    if not distritos:
        raise SystemExit("[Error] No se pudieron cargar los polígonos de distrito.")

    hist = leer_csv(args.historico)
    total = len(hist)
    print(f"[Histórico] {total} registros desde {args.historico}")

    if "distrito" not in hist.columns:
        hist["distrito"] = ""

    # Ojo: un valor nulo (NaN) se convierte en la cadena "nan" con astype(str),
    # que no es igual a "" ni a la etiqueta provisional. Por eso se comprueba
    # también con isna() de forma explícita.
    distrito_txt = hist["distrito"].astype(str).str.strip()
    pendientes = (
        hist["distrito"].isna()
        | (distrito_txt == "")
        | (distrito_txt.str.lower() == "nan")
        | (distrito_txt == ETIQUETA_PROVISIONAL)
    )
    print(f"[Reparación] Registros con distrito pendiente: {pendientes.sum()}")

    asignados = {}
    if pendientes.sum() == 0:
        print("[Reparación] El distrito ya está completo; no hay nada que asignar.")
    else:
        for idx in hist.index[pendientes]:
            lon = float(hist.at[idx, "longitude"])
            lat = float(hist.at[idx, "latitude"])
            nombre = None
            for dist, anillos in distritos.items():
                for ring in anillos:
                    if m._point_in_polygon(lon, lat, ring):
                        nombre = dist
                        break
                if nombre:
                    break
            if nombre:
                hist.at[idx, "distrito"] = nombre
                asignados[nombre] = asignados.get(nombre, 0) + 1

    resueltos = sum(asignados.values())
    no_resueltos = int(pendientes.sum()) - resueltos

    print(f"[Reparación] Distrito asignado a {resueltos} registros.")
    if no_resueltos:
        print(f"[Reparación] {no_resueltos} registros quedaron fuera de todos los distritos "
              f"(posible error de límite; se conserva la etiqueta provisional).")
    for nombre, n in sorted(asignados.items(), key=lambda x: -x[1]):
        print(f"   {nombre:28s} {n:4d}")

    # --- Recalcular distancias viales con la red oficial actual ---
    # La red vial del proyecto pasó de 3 ejes a los 5 tramos del GeoJSON del MTC
    # (se añadieron las trochas VEC-ANDA y VEC-NARANJILLO). Los registros
    # antiguos conservan la distancia calculada con la red vieja, así que
    # quedan sobreestimados si el foco está junto a una trocha.
    print("\n[Vías] Recalculando distancias con la red vial oficial...")
    roads = None
    if os.path.exists(args.carreteras):
        with open(args.carreteras, "r", encoding="utf-8") as f:
            roads = json.load(f)
        print(f"[Vías] {len(roads.get('features', []))} tramos cargados desde {args.carreteras}.")
    else:
        print(f"[Vías Warning] No existe {args.carreteras}; se omite el recálculo.")

    if roads:
        recalcular = hist[["latitude", "longitude"]].copy()
        resultado = m.calculate_road_accessibility_and_costs(recalcular, roads)

        cambios = 0
        detalle = []
        for i in range(len(hist)):
            vieja = hist.iloc[i].get("dist_carretera_km")
            nueva = resultado["dist_carretera_km"].iloc[i]
            try:
                cambio = abs(float(vieja) - float(nueva)) > 0.02
            except (TypeError, ValueError):
                cambio = True
            if cambio:
                cambios += 1
                detalle.append((hist.at[hist.index[i], "latitude"],
                                hist.at[hist.index[i], "longitude"],
                                vieja, nueva,
                                str(hist.iloc[i].get("accesibilidad")),
                                resultado["accesibilidad"].iloc[i]))

        hist["dist_carretera_km"] = resultado["dist_carretera_km"].values
        hist["carretera_cercana"] = resultado["carretera_cercana"].values
        hist["accesibilidad"] = resultado["accesibilidad"].values
        hist["tiempo_estimado"] = resultado["tiempo_estimado"].values
        hist["costo_estimado_pen"] = resultado["costo_estimado_pen"].values

        print(f"[Vías] Distancias actualizadas: {cambios} de {len(hist)} cambiaron.")
        for lat, lon, v, n, av, an in detalle[:10]:
            marca = "  <-- cambia de categoría" if av != an else ""
            print(f"   ({lat:.5f},{lon:.5f})  {v} -> {n} km  [{av} -> {an}]{marca}")

    respaldo = f"{args.historico}.bak_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(args.historico, respaldo)
    hist.to_csv(args.historico, index=False, encoding="utf-8-sig")

    print(f"\n[Respaldo] Versión anterior en {respaldo}")
    print(f"[Guardado] {args.historico}")
    print("\nDistribución final por distrito:")
    print(hist["distrito"].value_counts().to_string())
    print("\nSiguiente paso: regenerar matriz y dashboard, o ejecutar")
    print("  python sincronizar_datos.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
