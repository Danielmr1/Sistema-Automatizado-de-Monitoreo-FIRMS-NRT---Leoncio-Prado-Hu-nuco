#!/usr/bin/env python3
"""
=============================================================================
Incrusta el histórico verificado y la red vial en el dashboard index.html.
=============================================================================
El dashboard NO debe contener focos escritos a mano: los 10 focos que tenía
en INITIAL_FIRES no coincidían con ninguna detección de NASA FIRMS.

Este script reemplaza los dos bloques marcados en index.html:
  - const HISTORICO_CSV = `...`;                  -> histórico real
  - const ROADS_GEOJSON = /*ROADS_GEOJSON*/...;   -> red vial oficial

Uso:
    python generar_dashboard.py
    python generar_dashboard.py --historico historico_leoncio_prado_2026.csv
"""

import os
import re
import sys
import json
import argparse
import datetime
import pandas as pd

MARCA_CSV = re.compile(r"const HISTORICO_CSV = `.*?`;", re.DOTALL)
MARCA_ROADS = re.compile(r"const ROADS_GEOJSON = /\*ROADS_GEOJSON\*/.*?/\*ROADS_GEOJSON\*/;", re.DOTALL)


def cargar_historico(path):
    if not os.path.exists(path):
        raise SystemExit(f"[Error] No existe {path}. Ejecuta main.py o fusionar_historico.py primero.")
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            df = pd.read_csv(path, encoding=enc)
            print(f"[Histórico] {len(df)} registros, {len(df.columns)} columnas desde {path}.")
            return df
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"[Error] No se pudo leer {path}.")


def csv_a_texto(df):
    """Serializa el DataFrame a CSV sin índice, tal como lo leerá el navegador."""
    return df.to_csv(index=False, encoding=None, lineterminator="\n")


def escapar_para_template(texto):
    """
    El CSV se inserta dentro de un template literal de JavaScript (backticks).

    Solo hay que escapar la barra invertida y el backtick. NO se debe tocar
    '${': dentro de un template literal la secuencia '\\$' no es un escape
    valido, JS elimina la barra y '${' volveria a interpolar. Por eso las
    secuencias peligrosas se rechazan de forma explicita.
    """
    for peligroso, motivo in (("`", "backtick"), ("${", "interpolacion ${")):
        if peligroso in texto:
            raise SystemExit(
                f"[Error] El contenido a incrustar contiene '{peligroso}' ({motivo}), "
                f"que rompería el template literal del dashboard. Revisa el histórico."
            )
    return texto.replace("\\", "\\\\")


def main():
    parser = argparse.ArgumentParser(description="Incrusta datos reales en index.html")
    parser.add_argument("--dashboard", default="index.html")
    parser.add_argument("--historico", default="historico_leoncio_prado_2026.csv")
    parser.add_argument("--carreteras", default="aoi_carreteras_leoncio_prado.geojson")
    parser.add_argument("--max-registros", type=int, default=0,
                        help="Limitar a los N registros más recientes (0 = todos).")
    args = parser.parse_args()

    if not os.path.exists(args.dashboard):
        raise SystemExit(f"[Error] No existe {args.dashboard}.")

    with open(args.dashboard, "r", encoding="utf-8") as f:
        html = f.read()

    # --- 1. Histórico ---
    df = cargar_historico(args.historico)
    if args.max_registros and len(df) > args.max_registros:
        df = df.sort_values(["acq_date", "acq_time"]).tail(args.max_registros)
        print(f"[Histórico] Limitado a los {len(df)} registros más recientes.")

    csv_txt = escapar_para_template(csv_a_texto(df))
    nuevo_csv = f"const HISTORICO_CSV = `{csv_txt}`;"
    html, n_csv = MARCA_CSV.subn(lambda _: nuevo_csv, html, count=1)

    # --- 2. Red vial ---
    if os.path.exists(args.carreteras):
        with open(args.carreteras, "r", encoding="utf-8") as f:
            roads = json.load(f)
        roads_txt = json.dumps(roads, ensure_ascii=False).replace("</", "<\\/")
        n_tramos = len(roads.get("features", []))
        print(f"[Red Vial] {n_tramos} tramos incrustados desde {args.carreteras}.")
    else:
        roads_txt = "null"
        print(f"[Red Vial Warning] No existe {args.carreteras}; se incrusta null.")

    nuevo_roads = f"const ROADS_GEOJSON = /*ROADS_GEOJSON*/{roads_txt}/*ROADS_GEOJSON*/;"
    html, n_roads = MARCA_ROADS.subn(lambda _: nuevo_roads, html, count=1)

    if n_csv != 1:
        raise SystemExit("[Error] No se encontró el bloque 'const HISTORICO_CSV' en el dashboard.")
    if n_roads != 1:
        raise SystemExit("[Error] No se encontró el bloque 'const ROADS_GEOJSON' en el dashboard.")

    respaldo = f"{args.dashboard}.bak_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.replace(args.dashboard, respaldo)
    with open(args.dashboard, "w", encoding="utf-8") as f:
        f.write(html)

    tamano = os.path.getsize(args.dashboard) / 1024
    print(f"\n[Respaldo] Dashboard anterior guardado en {respaldo}")
    print("=" * 62)
    print("DASHBOARD ACTUALIZADO")
    print("=" * 62)
    print(f"  Archivo    : {args.dashboard} ({tamano:.0f} KB)")
    print(f"  Registros  : {len(df)}")
    print(f"  Fechas     : {df['acq_date'].min()} .. {df['acq_date'].max()}")
    print(f"  Días       : {df['acq_date'].nunique()}")
    print(f"  Sin distrito asignado: {(df['distrito'].astype(str).str.startswith('Leoncio Prado (distrito')).sum()}")
    print("=" * 62)
    print("\nAbre index.html en el navegador: los focos y la red vial son datos reales.")


if __name__ == "__main__":
    main()
