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

Uso:
    python reparar_distritos.py
    python reparar_distritos.py --historico historico_leoncio_prado_2026.csv
"""

import os
import sys
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
    parser = argparse.ArgumentParser(description="Repara el distrito de los registros antiguos")
    parser.add_argument("--historico", default=HIST_PATH)
    parser.add_argument("--distritos", default="distritos_leoncio_prado.geojson")
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

    distrito_txt = hist["distrito"].astype(str).str.strip()
    pendientes = (distrito_txt == "") | (distrito_txt == ETIQUETA_PROVISIONAL)
    print(f"[Reparación] Registros con distrito pendiente: {pendientes.sum()}")

    if pendientes.sum() == 0:
        print("[Reparación] Nada que reparar. El distrito ya está completo.")
        return 0

    asignados = {}
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

    respaldo = f"{args.historico}.bak_distritos_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
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
