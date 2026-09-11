#!/usr/bin/env python3
"""
=============================================================================
Verifica la integridad del histórico y repara los huecos automáticamente.
=============================================================================
EL PROBLEMA QUE RESUELVE
El pipeline consulta una ventana de 1 a 5 días. Si una corrida falla, o si el
workflow no registra un día, ese día se pierde PARA SIEMPRE: la API de FIRMS
solo conserva 5 días hacia atrás.

Ya ocurrió una vez: el 4 y 5 de septiembre de 2026 hubo 15 detecciones dentro
de Leoncio Prado que no llegaron al histórico. Se recuperaron casi al límite
de la ventana.

QUÉ HACE ESTE SCRIPT
  1. Lee el histórico y obtiene su rango de fechas.
  2. Consulta FIRMS para la ventana recuperable (5 días atrás).
  3. Compara: ¿hay detecciones dentro del AOI que no estén en el histórico?
  4. Si hay huecos, los recupera (salvo en --simular).
  5. Informa del estado para que el workflow pueda avisar.

Uso:
    python verificar_integridad.py              # detecta y repara
    python verificar_integridad.py --simular    # solo detecta
    python verificar_integridad.py --solo-estado # no consulta la API, solo revisa el archivo
"""

import os
import sys
import argparse
import datetime

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd

HIST_PATH = "historico_leoncio_prado_2026.csv"
VENTANA_FIRMS = 5  # límite real de la API


def leer(path):
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"[Error] No se pudo leer {path}.")


def clave_fila(d):
    """Clave única de una detección FIRMS."""
    return set(zip(
        d["latitude"].round(5).astype(str),
        d["longitude"].round(5).astype(str),
        d["acq_date"].astype(str),
        d["acq_time"].astype(str),
        d["source_sensor"].astype(str),
    ))


def revisar_archivo(hist):
    """
    Comprobaciones internas que no requieren la API.

    Distingue dos tipos de día sin detecciones, porque significan cosas muy
    distintas:
      - CUBIERTO    : está dentro de la ventana de 5 días que la API permite
                      consultar, y la consulta no aporta nada nuevo. Es decir,
                      ese día FIRMS realmente no detectó nada en la provincia.
      - NO CUBIERTO : es más antiguo que la ventana. No se puede comprobar si
                      fue un día sin quemas o una corrida que falló.
    """
    problemas = []
    informativos = []

    if hist.empty:
        problemas.append("El histórico está vacío.")
        return problemas, informativos

    # Fechas duplicadas exactas (misma lat/lon/fecha/hora/sensor)
    dup = hist.duplicated(
        subset=["latitude", "longitude", "acq_date", "acq_time", "source_sensor"]
    ).sum()
    if dup:
        problemas.append(f"{dup} registros duplicados.")

    # Distritos sin asignar
    if "distrito" in hist.columns:
        dist = hist["distrito"]
        sin_dist = (dist.isna() | dist.astype(str).str.strip().isin(["", "nan"])
                    | dist.astype(str).str.startswith("Leoncio Prado (distrito")).sum()
        if sin_dist:
            problemas.append(f"{sin_dist} registros sin distrito asignado.")

    # Fechas en el futuro
    hoy = datetime.datetime.now(datetime.timezone.utc).date()
    futuras = (hist["acq_date"].astype(str) > hoy.isoformat()).sum()
    if futuras:
        problemas.append(f"{futuras} registros con fecha futura.")

    # Huecos internos de la serie
    fechas = sorted(hist["acq_date"].astype(str).unique())
    if len(fechas) >= 2:
        d0 = datetime.date.fromisoformat(fechas[0])
        d1 = datetime.date.fromisoformat(fechas[-1])
        limite_api = hoy - datetime.timedelta(days=VENTANA_FIRMS - 1)

        esperados, d = [], d0
        while d <= d1:
            esperados.append(d.isoformat())
            d += datetime.timedelta(days=1)

        cubiertos, no_cubiertos = [], []
        for f in esperados:
            if f in fechas:
                continue
            (cubiertos if datetime.date.fromisoformat(f) >= limite_api else no_cubiertos).append(f)

        if cubiertos:
            informativos.append(
                f"{len(cubiertos)} días sin detecciones DENTRO de la ventana consultable "
                f"(FIRMS confirma que no hubo focos): {', '.join(cubiertos)}")
        if no_cubiertos:
            informativos.append(
                f"{len(no_cubiertos)} días sin detecciones FUERA de la ventana consultable "
                f"(no se puede comprobar si fue día sin quemas o corrida fallida): "
                f"{', '.join(no_cubiertos)}")

    return problemas, informativos


def detectar_huecos_api(hist):
    """
    Consulta FIRMS la ventana recuperable y devuelve los registros que faltan
    en el histórico. Devuelve (faltantes_df, info).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("main", "main.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    if not m.FIRMS_API_KEY:
        return None, "FIRMS_API_KEY no configurada; no se puede consultar la API."

    hoy = datetime.datetime.now(datetime.timezone.utc).date()
    desde = (hoy - datetime.timedelta(days=VENTANA_FIRMS - 1)).isoformat()

    print(f"[FIRMS] Consultando la ventana recuperable: {VENTANA_FIRMS} días desde {desde}")
    raw = m.download_all_sources(day_range=str(VENTANA_FIRMS), start_date=desde)
    if raw.empty:
        return None, "La API no devolvió detecciones en la ventana; nada que comparar."

    espacial = m.apply_spatial_filter(raw, m.AOI_GEOJSON_PATH)
    if espacial.empty:
        return pd.DataFrame(), "Sin detecciones dentro del AOI en la ventana."

    validos, baja = m.apply_confidence_filter(espacial)
    nuevos = pd.concat([validos, baja], ignore_index=True) if len(baja) else validos
    if nuevos.empty:
        return pd.DataFrame(), "Sin detecciones que superen el filtro de confianza."

    # Sellar los metadatos que espera el histórico
    sello = hoy.isoformat()
    nuevos = nuevos.copy()
    nuevos["verificado_firms"] = sello
    nuevos["tipo_registro"] = "validado"
    nuevos["confianza_cruda"] = [
        m.normalize_confidence_label(r.get("source_sensor", ""), r.get("confidence", ""))
        for _, r in nuevos.iterrows()
    ]
    if "distrito" not in nuevos.columns:
        nuevos["distrito"] = ""

    claves_hist = clave_fila(hist)
    claves_nuevas = clave_fila(nuevos)
    faltan_idx = [i for i, k in enumerate(claves_nuevas) if k not in claves_hist]

    if not faltan_idx:
        return pd.DataFrame(), f"Al día: la API no aporta detecciones nuevas ({len(nuevos)} revisadas)."

    return nuevos.iloc[faltan_idx].copy(), f"{len(faltan_idx)} detecciones por recuperar."


def recuperar(hist, faltantes, path):
    combinado = pd.concat([hist, faltantes], ignore_index=True)
    for col in ["distrito", "confianza_cruda", "verificado_firms", "tipo_registro"]:
        if col not in combinado.columns:
            combinado[col] = ""
        combinado[col] = combinado[col].fillna("")

    combinado = combinado.drop_duplicates(
        subset=["latitude", "longitude", "acq_date", "acq_time", "source_sensor"],
        keep="last")
    combinado = combinado.sort_values(["acq_date", "acq_time"]).reset_index(drop=True)

    respaldo = f"{path}.bak_integridad_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.replace(path, respaldo)
    combinado.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"[Respaldo] {respaldo}")
    return len(combinado)


def main():
    parser = argparse.ArgumentParser(description="Verifica y repara la integridad del histórico")
    parser.add_argument("--historico", default=HIST_PATH)
    parser.add_argument("--simular", action="store_true", help="Detectar sin escribir")
    parser.add_argument("--solo-estado", action="store_true",
                        help="Revisar solo el archivo, sin consultar la API")
    args = parser.parse_args()

    if not os.path.exists(args.historico):
        raise SystemExit(f"[Error] No existe {args.historico}.")

    hist = leer(args.historico)
    print("=" * 72)
    print("VERIFICACIÓN DE INTEGRIDAD DEL HISTÓRICO")
    print("=" * 72)
    print(f"  Registros : {len(hist)}")
    print(f"  Fechas    : {hist['acq_date'].min()} .. {hist['acq_date'].max()}")
    print(f"  Días      : {hist['acq_date'].nunique()}")

    print("\n[1] Revisión interna del archivo")
    problemas, informativos = revisar_archivo(hist)
    if problemas:
        for p in problemas:
            print(f"    PROBLEMA: {p}")
    else:
        print("    Sin problemas internos.")
    for i in informativos:
        print(f"    Nota: {i}")

    if args.solo_estado:
        print("\n[Fin] Modo --solo-estado: no se consultó la API.")
        return 1 if problemas else 0

    print("\n[2] Comparación con el archivo de NASA FIRMS")
    faltantes, info = detectar_huecos_api(hist)
    print(f"    {info}")

    recuperados = 0
    if faltantes is not None and len(faltantes):
        print(f"\n    Detecciones que faltan en el histórico:")
        for _, r in faltantes.head(20).iterrows():
            print(f"      {r['acq_date']} {r['acq_time']} | {r['latitude']},{r['longitude']} | "
                  f"{r['source_sensor']} | frp={r['frp']}")
        if len(faltantes) > 20:
            print(f"      ... y {len(faltantes) - 20} más")

        if args.simular:
            print("\n    [Simulación] No se escribió nada.")
        else:
            total = recuperar(hist, faltantes, args.historico)
            recuperados = len(faltantes)
            print(f"\n    [Recuperado] {recuperados} detecciones añadidas.")
            print(f"    [Histórico] {len(hist)} -> {total} registros")
            print("\n    Siguiente paso obligatorio:")
            print("      python reparar_distritos.py   (asigna distrito y recalcula vías)")

    print("\n" + "=" * 72)
    estado = "OK"
    if problemas or recuperados:
        estado = "REPARADO" if recuperados and not args.simular else "REVISAR"
    print(f"ESTADO: {estado}")
    if recuperados:
        print(f"  Se recuperaron {recuperados} detecciones que se habrían perdido.")
    print("=" * 72)

    # Código de salida: 2 = hubo huecos, para que el workflow pueda avisar
    if faltantes is not None and len(faltantes) and args.simular:
        return 2
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
