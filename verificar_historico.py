#!/usr/bin/env python3
"""
=============================================================================
Verifica que el histórico local sean datos REALES de NASA FIRMS.
=============================================================================
Este script es la prueba de trazabilidad del proyecto: descarga la respuesta
cruda de la API de FIRMS y comprueba, registro por registro, si cada fila del
histórico coincide con una detección satelital real.

Compara la clave única de una detección FIRMS:
    latitude + longitude + acq_date + acq_time
y, cuando hay coincidencia, contrasta además los campos físicos
(FRP, confidence, bright_ti4/t31, scan, daynight).

Limitación importante: la API de FIRMS solo permite consultar 5 días hacia
atrás (days=6 devuelve "Invalid day range. Expects [1..5]"). Los registros más
antiguos no son verificables por esta vía y se reportan como tales.

Uso:
    python verificar_historico.py
    python verificar_historico.py --desde 2026-08-26 --dias 5
    python verificar_historico.py --informe reporte_verificacion.md
    python verificar_historico.py --sellar     # actualiza verificado_firms
"""

import os
import io
import csv
import sys
import json
import argparse
import datetime
import requests
import pandas as pd

from main import FIRMS_API_KEY, BBOX, SOURCES, MAX_DAY_RANGE, normalize_confidence_label

HIST_PATH = "historico_leoncio_prado_2026.csv"
CLAVE = ["latitude", "longitude", "acq_date", "acq_time"]
CAMPOS_FISICOS = [
    ("frp", "frp"),
    ("confidence", "confidence"),
    ("bright_ti4", "bright_ti4"),
    ("bright_ti31", "bright_t31"),
    ("scan", "scan"),
    ("track", "track"),
    ("daynight", "daynight"),
]


def descargar_referencia(desde, dias, api_key):
    """
    Descarga las detecciones reales del BBOX para una ventana de fechas.
    Devuelve {clave: registro_firms}.
    """
    referencia = {}
    errores = []
    for source in SOURCES:
        url = (f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
               f"{api_key}/{source}/{BBOX}/{dias}/{desde}")
        try:
            r = requests.get(url, timeout=90)
            texto = r.text.strip()
            if r.status_code != 200 or texto.startswith(("Invalid", "Error")):
                errores.append(f"{source}: HTTP {r.status_code} {texto[:60]}")
                print(f"  [Aviso] {source}: {texto[:70]}")
                continue
            filas = list(csv.DictReader(io.StringIO(texto)))
            for fila in filas:
                k = clave_de(fila)
                if k:
                    referencia[k] = fila
            print(f"  [FIRMS] {source}: {len(filas)} detecciones reales")
        except Exception as e:
            errores.append(f"{source}: {e}")
            print(f"  [Error] {source}: {e}", file=sys.stderr)
    return referencia, errores


def clave_de(registro):
    try:
        lat = round(float(registro["latitude"]), 5)
        lon = round(float(registro["longitude"]), 5)
        return (lat, lon, str(registro["acq_date"]).strip(), str(registro["acq_time"]).strip().zfill(4))
    except (KeyError, ValueError, TypeError):
        return None


def leer_historico(path):
    if not os.path.exists(path):
        raise SystemExit(f"[Error] No existe {path}. Ejecuta main.py o fusionar_historico.py primero.")
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"[Error] No se pudo leer {path}.")


def comparar(historico, referencia):
    """Clasifica cada fila del histórico y detecta discrepancias de campos."""
    verificados, fuera_ventana, sin_coincidencia = [], [], []
    discrepancias = []

    for idx, fila in historico.iterrows():
        k = clave_de(fila)
        if k is None:
            sin_coincidencia.append((idx, "clave incompleta"))
            continue
        if k not in referencia:
            if str(fila.get("acq_date")) < min((v["acq_date"] for v in referencia.values()), default="9999"):
                fuera_ventana.append(idx)
            else:
                sin_coincidencia.append((idx, "no está en el archivo FIRMS"))
            continue

        ref = referencia[k]
        verificados.append(idx)

        for campo_py, campo_firms in CAMPOS_FISICOS:
            if campo_py not in historico.columns:
                continue
            v_local = str(fila.get(campo_py, "")).strip()
            v_firms = str(ref.get(campo_firms, "")).strip()
            if not v_local or not v_firms:
                continue
            try:
                if abs(float(v_local) - float(v_firms)) > 0.011:
                    discrepancias.append((idx, campo_py, v_local, v_firms))
            except ValueError:
                if v_local.lower() != v_firms.lower():
                    discrepancias.append((idx, campo_py, v_local, v_firms))

    return verificados, fuera_ventana, sin_coincidencia, discrepancias


def escribir_informe(ruta, historico, verificados, fuera_ventana, sin_coincidencia,
                     discrepancias, referencia, desde, dias):
    hoy = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(historico)
    pct = (len(verificados) / total * 100) if total else 0.0

    lineas = [
        "# Reporte de verificación del histórico contra NASA FIRMS",
        "",
        f"**Generado:** {hoy}  ",
        f"**Histórico analizado:** `{HIST_PATH}` ({total} registros)  ",
        f"**Ventana FIRMS consultada:** {dias} días desde {desde}  ",
        f"**Detecciones reales descargadas:** {len(referencia)}  ",
        "",
        "## Resultado",
        "",
        f"* **Coinciden exactamente con NASA FIRMS:** {len(verificados)} / {total} ({pct:.1f} %)",
        f"* **Fuera de la ventana verificable (datos antiguos):** {len(fuera_ventana)}",
        f"* **En ventana pero sin coincidencia:** {len(sin_coincidencia)}",
        f"* **Discrepancias de campos físicos:** {len(discrepancias)}",
        "",
    ]

    if len(verificados) and not discrepancias and not sin_coincidencia:
        lineas.append("> **Conclusión:** todos los registros verificables coinciden exactamente con "
                      "el archivo satelital original. El histórico contiene datos reales, no simulados.")
    elif sin_coincidencia or discrepancias:
        lineas.append("> **Atención:** hay registros que no coinciden. Revisa el detalle antes de "
                      "usar el histórico como evidencia.")
    else:
        lineas.append("> No hay registros dentro de la ventana verificable por la API.")

    lineas.append("")
    lineas.append("## Detalle")
    lineas.append("")

    if discrepancias:
        lineas.append("### Discrepancias de campos")
        lineas.append("")
        lineas.append("| Fila | Campo | Histórico | FIRMS |")
        lineas.append("| ---: | :--- | :--- | :--- |")
        for idx, campo, vl, vf in discrepancias[:50]:
            lineas.append(f"| {idx} | {campo} | {vl} | {vf} |")
        lineas.append("")

    if sin_coincidencia:
        lineas.append("### Registros sin coincidencia")
        lineas.append("")
        lineas.append("| Fila | Fecha | Hora | Lat | Lon | Motivo |")
        lineas.append("| ---: | :--- | :--- | :--- | :--- | :--- |")
        for idx, motivo in sin_coincidencia[:50]:
            f = historico.loc[idx]
            lineas.append(f"| {idx} | {f.get('acq_date','')} | {f.get('acq_time','')} | "
                          f"{f.get('latitude','')} | {f.get('longitude','')} | {motivo} |")
        lineas.append("")

    if fuera_ventana:
        fechas = sorted({str(historico.loc[i, "acq_date"]) for i in fuera_ventana})
        lineas.append("### Fuera de la ventana verificable")
        lineas.append("")
        lineas.append(f"{len(fuera_ventana)} registros de {len(fechas)} fechas no pueden contrastarse "
                      f"porque la API FIRMS solo conserva {MAX_DAY_RANGE} días hacia atrás: "
                      f"{', '.join(fechas[:12])}{'...' if len(fechas) > 12 else ''}.")
        lineas.append("")
        lineas.append("Esto no significa que sean falsos: fueron verificados en la fecha en que se "
                      "descargaron (columna `verificado_firms`).")
        lineas.append("")

    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
    print(f"[Informe] Guardado en {ruta}")


def main():
    parser = argparse.ArgumentParser(description="Verifica el histórico contra NASA FIRMS")
    parser.add_argument("--historico", default=HIST_PATH)
    parser.add_argument("--desde", default=None, help="Fecha de inicio YYYY-MM-DD (por defecto: hace 5 días)")
    parser.add_argument("--dias", type=int, default=MAX_DAY_RANGE,
                        help=f"Días a consultar (máximo {MAX_DAY_RANGE} por límite de la API)")
    parser.add_argument("--informe", default=None, help="Ruta del informe Markdown a generar")
    parser.add_argument("--sellar", action="store_true",
                        help="Actualizar verificado_firms con la fecha de hoy en los registros comprobados")
    args = parser.parse_args()

    if not FIRMS_API_KEY:
        raise SystemExit("[Error] Falta FIRMS_API_KEY. Defínela antes de ejecutar:\n"
                         '  $env:FIRMS_API_KEY="tu_key"   (PowerShell)\n'
                         "  export FIRMS_API_KEY=tu_key   (bash)")

    if args.dias > MAX_DAY_RANGE:
        print(f"[Aviso] La API solo acepta hasta {MAX_DAY_RANGE} días; se ajusta el valor.")
        args.dias = MAX_DAY_RANGE

    desde = args.desde or (datetime.datetime.now(datetime.timezone.utc)
                           - datetime.timedelta(days=args.dias - 1)).strftime("%Y-%m-%d")

    print("=" * 70)
    print("VERIFICACIÓN DEL HISTÓRICO CONTRA NASA FIRMS")
    print("=" * 70)

    historico = leer_historico(args.historico)
    print(f"[Histórico] {len(historico)} registros "
          f"({historico['acq_date'].min()} .. {historico['acq_date'].max()})")

    print(f"\n[FIRMS] Descargando referencia real: {args.dias} días desde {desde}")
    referencia, errores = descargar_referencia(desde, args.dias, FIRMS_API_KEY)
    print(f"[FIRMS] {len(referencia)} detecciones reales de referencia")

    if not referencia:
        raise SystemExit("[Error] La API no devolvió detecciones. No se puede verificar.")

    verificados, fuera_ventana, sin_coincidencia, discrepancias = comparar(historico, referencia)

    total = len(historico)
    pct = (len(verificados) / total * 100) if total else 0.0

    print()
    print("=" * 70)
    print("RESULTADO")
    print("=" * 70)
    print(f"  Coinciden exactamente con NASA FIRMS : {len(verificados)} / {total} ({pct:.1f} %)")
    print(f"  Fuera de la ventana verificable      : {len(fuera_ventana)}")
    print(f"  En ventana pero sin coincidencia     : {len(sin_coincidencia)}")
    print(f"  Discrepancias de campos físicos      : {len(discrepancias)}")
    if errores:
        print(f"  Errores de descarga                  : {len(errores)}")

    if len(verificados) and not discrepancias and not sin_coincidencia:
        print("\n  >>> Los registros verificables coinciden exactamente con el archivo")
        print("  >>> satelital original: el histórico contiene DATOS REALES.")
    print("=" * 70)

    if args.informe:
        escribir_informe(args.informe, historico, verificados, fuera_ventana,
                         sin_coincidencia, discrepancias, referencia, desde, args.dias)

    if args.sellar and verificados:
        hoy = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        historico.loc[verificados, "verificado_firms"] = hoy
        historico.to_csv(args.historico, index=False, encoding="utf-8-sig")
        print(f"[Sello] verificado_firms = {hoy} en {len(verificados)} registros.")
        print("[Sello] Copia el histórico al repositorio para conservar la trazabilidad.")


if __name__ == "__main__":
    main()
