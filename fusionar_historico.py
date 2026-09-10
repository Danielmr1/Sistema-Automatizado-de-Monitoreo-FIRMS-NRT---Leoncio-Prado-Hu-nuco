#!/usr/bin/env python3
"""
=============================================================================
Fusiona el histórico del repositorio GitHub con el histórico local.
=============================================================================
El histórico del repositorio (277 registros verificados) NO puede perderse:
la API de FIRMS solo permite consultar 5 días hacia atrás, así que lo que no
esté guardado es irrecuperable.

Este script:
  1. Lee ambos históricos (el de GitHub descargado y el local).
  2. Los une por la clave única de una detección FIRMS
     (latitude, longitude, acq_date, acq_time, source_sensor).
  3. Añade las columnas nuevas de trazabilidad a los registros antiguos.
  4. Escribe el histórico maestro consolidado.

Uso:
    python fusionar_historico.py --repo _gh_historico.csv --local historico_leoncio_prado_2026.csv
"""

import os
import sys
import argparse
import datetime
import pandas as pd

EXTRA_COLS = ["distrito", "confianza_cruda", "verificado_firms", "tipo_registro"]
DEDUP_KEY = ["latitude", "longitude", "acq_date", "acq_time", "source_sensor"]
ETIQUETA_SIN_DISTRITO = "Leoncio Prado (distrito no determinado)"


def normalize_confidence_label(source, confidence):
    """Misma normalización que usa main.py."""
    source = str(source).upper()
    conf = str(confidence).strip().lower()
    if "MODIS" in source:
        try:
            v = float(conf)
        except (ValueError, TypeError):
            return "baja"
        return "alta" if v >= 80 else ("nominal" if v >= 60 else "baja")
    if conf in ("h", "high"):
        return "alta"
    if conf in ("n", "nominal"):
        return "nominal"
    return "baja"


def leer_csv(path):
    if not os.path.exists(path):
        print(f"[Aviso] No existe {path}; se omite.")
        return None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            df = pd.read_csv(path, encoding=enc)
            print(f"[Lectura] {path}: {len(df)} registros, {len(df.columns)} columnas (encoding {enc}).")
            return df
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"No se pudo leer {path} con ninguna codificación conocida.")


def completar_columnas(df, fecha_sello):
    """Añade las columnas de trazabilidad a los registros que no las tienen."""
    for col in EXTRA_COLS:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype("object").where(df[col].notna(), "")

    # distrito: la etiqueta provisional NO debe tener prioridad sobre un
    # distrito real. Se trata como vacío para que el valor definitivo gane.
    provisional = df["distrito"].astype(str).str.strip() == ETIQUETA_SIN_DISTRITO
    df.loc[provisional, "distrito"] = ""

    # distrito: nunca dejar vacío
    vacios = df["distrito"].astype(str).str.strip() == ""
    df.loc[vacios, "distrito"] = ETIQUETA_SIN_DISTRITO

    # confianza_cruda: derivar de la columna original de FIRMS
    faltan = df["confianza_cruda"].astype(str).str.strip() == ""
    if faltan.any():
        df.loc[faltan, "confianza_cruda"] = [
            normalize_confidence_label(s, c)
            for s, c in zip(df.loc[faltan, "source_sensor"], df.loc[faltan, "confidence"])
        ]

    # verificado_firms: sellar los que vengan del repo si no lo tienen
    sin_sello = df["verificado_firms"].astype(str).str.strip() == ""
    df.loc[sin_sello, "verificado_firms"] = fecha_sello

    # tipo_registro
    sin_tipo = df["tipo_registro"].astype(str).str.strip() == ""
    df.loc[sin_tipo, "tipo_registro"] = "validado"
    return df


def main():
    parser = argparse.ArgumentParser(description="Fusiona histórico del repo con el local")
    parser.add_argument("--repo", default="_gh_historico.csv", help="Histórico descargado del repositorio")
    parser.add_argument("--local", default="historico_leoncio_prado_2026.csv", help="Histórico local")
    parser.add_argument("--salida", default="historico_leoncio_prado_2026.csv", help="Archivo consolidado de salida")
    parser.add_argument("--fecha-sello", default=None, help="Fecha de verificación para registros antiguos (YYYY-MM-DD)")
    args = parser.parse_args()

    fecha_sello = args.fecha_sello or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    df_repo = leer_csv(args.repo)
    df_local = leer_csv(args.local)

    partes = [d for d in (df_repo, df_local) if d is not None and len(d)]
    if not partes:
        raise SystemExit("[Error] No hay ningún histórico que fusionar.")

    print(f"\n[Fusión] Registros de entrada: " +
          " + ".join(str(len(d)) for d in partes) + f" = {sum(len(d) for d in partes)}")

    # Alinear columnas antes de concatenar
    todas_cols = []
    for d in partes:
        for c in d.columns:
            if c not in todas_cols:
                todas_cols.append(c)
    for i, d in enumerate(partes):
        partes[i] = d.reindex(columns=todas_cols)
    combinado = pd.concat(partes, ignore_index=True)

    # Preferir los registros que ya traen las columnas nuevas: se ordena para
    # que, al deduplicar con keep="last", gane el registro más completo.
    combinado["_prioridad"] = (combinado["tipo_registro"].astype(str).str.strip() != "").astype(int)
    combinado = combinado.sort_values("_prioridad", kind="stable").drop(columns="_prioridad")

    combinado = completar_columnas(combinado, fecha_sello)

    claves = [c for c in DEDUP_KEY if c in combinado.columns]
    antes = len(combinado)
    combinado = combinado.drop_duplicates(subset=claves, keep="last").reset_index(drop=True)
    print(f"[Deduplicación] {antes} -> {len(combinado)} registros ({antes - len(combinado)} duplicados removidos).")

    # Orden cronológico para que el archivo sea legible
    combinado = combinado.sort_values(["acq_date", "acq_time"], kind="stable").reset_index(drop=True)

    # Columnas nuevas al final, orden estable
    nucleo = [c for c in combinado.columns if c not in EXTRA_COLS]
    extras = [c for c in EXTRA_COLS if c in combinado.columns]
    combinado = combinado[nucleo + extras]

    if os.path.exists(args.salida):
        respaldo = f"{args.salida}.bak_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.replace(args.salida, respaldo)
        print(f"[Respaldo] El histórico anterior se guardó en {respaldo}")

    combinado.to_csv(args.salida, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 66)
    print("HISTÓRICO CONSOLIDADO")
    print("=" * 66)
    print(f"  Archivo    : {args.salida}")
    print(f"  Registros  : {len(combinado)}")
    print(f"  Columnas   : {len(combinado.columns)}")
    print(f"  Fechas     : {combinado['acq_date'].min()} .. {combinado['acq_date'].max()}")
    print(f"  Días con detecciones: {combinado['acq_date'].nunique()}")
    print(f"  Sin distrito asignado: {(combinado['distrito'] == ETIQUETA_SIN_DISTRITO).sum()}")
    print(f"  Por tipo   : {combinado['tipo_registro'].value_counts().to_dict()}")
    print("=" * 66)


if __name__ == "__main__":
    main()
