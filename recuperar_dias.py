#!/usr/bin/env python3
"""
=============================================================================
Recupera detecciones de FIRMS de una ventana de fechas y las añade al histórico.
=============================================================================
Motivo: la API de FIRMS solo conserva 5 días. Si una corrida falló o el
workflow no registró un día, esos datos se pierden para siempre salvo que se
recuperen dentro de esa ventana.

Este script consulta FIRMS por fecha de inicio, aplica los mismos filtros del
pipeline (AOI + confianza) y añade al histórico los registros que falten.
Después hay que ejecutar reparar_distritos.py para completar los metadatos.

Uso:
    python recuperar_dias.py --desde 2026-09-04 --dias 5
    python recuperar_dias.py --desde 2026-09-04 --dias 5 --simular
"""

import os
import sys
import argparse
import datetime
import importlib.util

import pandas as pd

HIST_PATH = "historico_leoncio_prado_2026.csv"


def cargar_main():
    spec = importlib.util.spec_from_file_location("main", "main.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def main():
    parser = argparse.ArgumentParser(description="Recupera días faltantes desde FIRMS")
    parser.add_argument("--desde", required=True, help="Fecha de inicio YYYY-MM-DD")
    parser.add_argument("--dias", default="5", help="Días a consultar (1 a 5)")
    parser.add_argument("--historico", default=HIST_PATH)
    parser.add_argument("--simular", action="store_true", help="Solo mostrar, no escribir")
    args = parser.parse_args()

    m = cargar_main()

    if not m.FIRMS_API_KEY:
        raise SystemExit("[Error] Falta FIRMS_API_KEY. Defínela antes de ejecutar.")

    if not os.path.exists(args.historico):
        raise SystemExit(f"[Error] No existe {args.historico}.")
    hist = pd.read_csv(args.historico, encoding="utf-8-sig")
    print(f"[Histórico] {len(hist)} registros antes de recuperar")
    print(f"[Histórico] Fechas presentes: {sorted(hist['acq_date'].unique())}")

    print(f"\n[FIRMS] Consultando {args.dias} días desde {args.desde}...")
    raw = m.download_all_sources(day_range=args.dias, start_date=args.desde)
    print(f"[FIRMS] {len(raw)} detecciones crudas en el BBOX")
    if raw.empty:
        print("[Fin] No se obtuvieron datos. Nada que recuperar.")
        return 0

    espacial = m.apply_spatial_filter(raw, m.AOI_GEOJSON_PATH)
    if espacial.empty:
        print("[Fin] Ninguna detección cayó dentro de Leoncio Prado.")
        return 0

    validos, baja = m.apply_confidence_filter(espacial)

    # Añadir las columnas de trazabilidad que espera el histórico
    hoy = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    for df in (validos, baja):
        if df.empty:
            continue
        df["verificado_firms"] = hoy
        df["tipo_registro"] = df.apply(
            lambda r: "baja_confianza" if r.name in baja.index else "validado", axis=1)
        df["confianza_cruda"] = [
            m.normalize_confidence_label(r.get("source_sensor", ""), r.get("confidence", ""))
            for _, r in df.iterrows()
        ]
        if "distrito" not in df.columns:
            df["distrito"] = ""

    nuevos = pd.concat([validos, baja], ignore_index=True)
    print(f"[Filtros] {len(validos)} validados + {len(baja)} de baja confianza = {len(nuevos)}")

    # Detectar cuáles faltan realmente en el histórico
    def clave(d):
        return list(zip(
            d["latitude"].round(5).astype(str),
            d["longitude"].round(5).astype(str),
            d["acq_date"].astype(str),
            d["acq_time"].astype(str),
            d["source_sensor"].astype(str),
        ))

    claves_hist = set(clave(hist))
    claves_nuevas = clave(nuevos)
    faltantes = [i for i, k in enumerate(claves_nuevas) if k not in claves_hist]

    print(f"\n[Comparación] Registros ya presentes: {len(nuevos) - len(faltantes)}")
    print(f"[Comparación] Registros FALTANTES por recuperar: {len(faltantes)}")

    if not faltantes:
        print("\n[Fin] No hay nada que recuperar; el histórico ya los tiene.")
        return 0

    recuperar = nuevos.iloc[faltantes].copy()
    print("\n--- Registros a recuperar ---")
    for _, r in recuperar.iterrows():
        print(f"   {r['acq_date']} {r['acq_time']} | {r['latitude']},{r['longitude']} | "
              f"{r['source_sensor']} | conf={r['confidence']} | frp={r['frp']}")

    if args.simular:
        print("\n[Simulación] No se escribió nada (--simular).")
        return 0

    # Alinear columnas y unir
    combinado = pd.concat([hist, recuperar], ignore_index=True)
    for col in ["distrito", "confianza_cruda", "verificado_firms", "tipo_registro"]:
        if col not in combinado.columns:
            combinado[col] = ""
        combinado[col] = combinado[col].fillna("")

    dedup = ["latitude", "longitude", "acq_date", "acq_time", "source_sensor"]
    antes = len(combinado)
    combinado = combinado.drop_duplicates(subset=dedup, keep="last")
    combinado = combinado.sort_values(["acq_date", "acq_time"]).reset_index(drop=True)

    respaldo = f"{args.historico}.bak_recuperacion_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.replace(args.historico, respaldo)
    combinado.to_csv(args.historico, index=False, encoding="utf-8-sig")

    print(f"\n[Respaldo] {respaldo}")
    print(f"[Guardado] {args.historico}: {antes} -> {len(combinado)} registros")
    print("\nSiguiente paso obligatorio (asigna distrito y recalcula vías):")
    print("   python reparar_distritos.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
