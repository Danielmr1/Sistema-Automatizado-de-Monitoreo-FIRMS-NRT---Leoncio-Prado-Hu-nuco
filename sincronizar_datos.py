#!/usr/bin/env python3
"""
=============================================================================
Ciclo completo de actualización del sistema de monitoreo.
=============================================================================
Ejecuta en orden todos los pasos del flujo de trabajo, para no tener que
recordar la secuencia ni el orden de los argumentos:

    1. main.py                 -> descarga FIRMS y actualiza el histórico
    2. fusionar_historico.py   -> solo si hay un histórico del repo descargado
    3. verificar_historico.py  -> contrasta el histórico contra NASA FIRMS
    4. generar_matriz_campo.py -> regenera la matriz de salidas a campo
    5. generar_dashboard.py    -> reincrusta datos y red vial en index.html

Uso:
    python sincronizar_datos.py
    python sincronizar_datos.py --sin-verificar
    python sincronizar_datos.py --dias 3 --matriz-dias 7
"""

import os
import sys
import argparse
import datetime
import subprocess

# Igual que en main.py: en consola Windows la salida por defecto es cp1252 y
# cualquier carácter no representable rompe el print. Los subprocesos devuelven
# UTF-8, así que forzamos la salida del orquestador a UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HISTORICO = "historico_leoncio_prado_2026.csv"
HISTORICO_REPO = "_gh_historico.csv"


def ejecutar(nombre, comando):
    """Ejecuta un paso y devuelve (ok, salida)."""
    print("\n" + "=" * 72)
    print(f"PASO: {nombre}")
    print("=" * 72)
    try:
        res = subprocess.run(
            comando, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError as e:
        print(f"[Error] No se pudo ejecutar {comando[0]}: {e}")
        return False, str(e)

    salida = (res.stdout or "") + (res.stderr or "")
    # Mostrar solo las líneas relevantes para no saturar
    for linea in salida.splitlines():
        limpio = linea.replace("\ufffd", "?")
        if limpio.strip() and not limpio.strip().startswith(("FutureWarning", "  ")):
            print("   " + limpio)

    ok = res.returncode == 0
    print(f"   -> {'OK' if ok else f'FALLO (codigo {res.returncode})'}")
    return ok, salida


def contar_historico(path=HISTORICO):
    import pandas as pd
    if not os.path.exists(path):
        return 0, "", 0
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
        return len(df), f"{df['acq_date'].min()} .. {df['acq_date'].max()}", df["acq_date"].nunique()
    except Exception:
        return 0, "", 0


def main():
    parser = argparse.ArgumentParser(description="Ciclo completo de actualización")
    parser.add_argument("--dias", default="2", help="Ventana NRT a consultar (1 a 5). Por defecto 2")
    parser.add_argument("--matriz-dias", type=int, default=30, help="Ventana de la matriz de campo")
    parser.add_argument("--sin-verificar", action="store_true", help="Omitir el contraste contra FIRMS")
    parser.add_argument("--sin-integridad", action="store_true",
                        help="Omitir la comprobación de huecos y la recuperación de días perdidos")
    parser.add_argument("--sin-dashboard", action="store_true", help="Omitir la regeneración del dashboard")
    args = parser.parse_args()

    inicio = datetime.datetime.now()
    py = sys.executable

    print("#" * 72)
    print("# CICLO COMPLETO DE ACTUALIZACION - MONITOREO DE QUEMAS LEONCIO PRADO")
    print(f"# Inicio: {inicio.strftime('%Y-%m-%d %H:%M:%S')}")
    print("#" * 72)

    resultados = {}

    # --- 1. Pipeline principal ---
    ok, _ = ejecutar(
        "1. Descarga FIRMS NRT y actualización del histórico",
        [py, "main.py", "--days", str(args.dias), "--incluir-baja-confianza"],
    )
    resultados["pipeline"] = ok
    if not ok:
        print("\n[Fin] El pipeline principal falló. Revisa la salida anterior.")
        print("      Pista: si el error es 'FIRMS_API_KEY no configurada', define la variable:")
        print('      $env:FIRMS_API_KEY="tu_key"')
        return 1

    # --- 2. Fusión con el histórico del repositorio (si existe) ---
    if os.path.exists(HISTORICO_REPO):
        ok, _ = ejecutar(
            "2. Fusión con el histórico del repositorio",
            [py, "fusionar_historico.py", "--repo", HISTORICO_REPO, "--local", HISTORICO],
        )
        resultados["fusion"] = ok
    else:
        print("\n" + "=" * 72)
        print("PASO: 2. Fusión con el histórico del repositorio")
        print("=" * 72)
        print(f"   Omitido: no existe {HISTORICO_REPO}.")
        print("   Para traerlo desde GitHub:")
        print(f'   curl -o {HISTORICO_REPO} "https://raw.githubusercontent.com/Danielmr1/'
              "Sistema-Automatizado-de-Monitoreo-FIRMS-NRT---Leoncio-Prado-Hu-nuco/main/"
              f'{HISTORICO}"')
        resultados["fusion"] = None

    # --- 2b. Fusión del registro de ejecuciones ---
    # El workflow y las corridas locales escriben cada uno su propio registro.
    # Sin fusionarlos, subir el local borraría las entradas del repositorio.
    if os.path.exists("_gh_registro.csv"):
        ok, _ = ejecutar(
            "2b. Fusión del registro de ejecuciones",
            [py, "fusionar_registro.py", "--repo", "_gh_registro.csv"],
        )
        resultados["registro"] = ok
    else:
        print("\n" + "=" * 72)
        print("PASO: 2b. Fusión del registro de ejecuciones")
        print("=" * 72)
        print("   Omitido: no existe _gh_registro.csv.")
        print("   Para traerlo desde GitHub:")
        print('   python fusionar_registro.py --descargar')
        resultados["registro"] = None

    # --- 3. Verificación contra NASA FIRMS ---
    if not args.sin_verificar:
        hoy = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        ok, _ = ejecutar(
            "3. Verificación del histórico contra NASA FIRMS",
            [py, "verificar_historico.py", "--informe", f"reporte_verificacion_{hoy}.md"],
        )
        resultados["verificacion"] = ok
    else:
        resultados["verificacion"] = None

    # --- 4. Integridad: detectar y recuperar días perdidos ---
    # La API de FIRMS solo conserva 5 días. Este paso compara el histórico con
    # la ventana recuperable y repara cualquier detección no guardada ANTES de
    # que sea irrecuperable.
    if not args.sin_integridad:
        ok, salida = ejecutar(
            "4. Integridad del histórico (recuperación de días perdidos)",
            [py, "verificar_integridad.py"],
        )
        resultados["integridad"] = ok
        if ok and "Recuperado]" in salida:
            print("\n   Se recuperaron detecciones: se reasignan distrito y vías.")
            ejecutar(
                "4b. Reparación de metadatos tras la recuperación",
                [py, "reparar_distritos.py", "--historico", HISTORICO],
            )
    else:
        resultados["integridad"] = None

    # --- 5. Reparación de metadatos derivados (distrito) ---
    # Los registros que ya estaban en el histórico no pasan por el pipeline,
    # así que su distrito se rellena aquí, sin volver a descargar detecciones.
    if os.path.exists("distritos_leoncio_prado.geojson"):
        ok, _ = ejecutar(
            "5. Reparación de distrito en registros antiguos",
            [py, "reparar_distritos.py", "--historico", HISTORICO],
        )
        resultados["reparacion"] = ok
    else:
        print("\n" + "=" * 72)
        print("PASO: 5. Reparación de distrito en registros antiguos")
        print("=" * 72)
        print("   Omitido: falta distritos_leoncio_prado.geojson.")
        resultados["reparacion"] = None

    # --- 6. Matriz de campo ---
    ok, _ = ejecutar(
        "6. Matriz de salidas a campo",
        [py, "generar_matriz_campo.py", "--dias", str(args.matriz_dias)],
    )
    resultados["matriz"] = ok

    # --- 7. Dashboard ---
    if not args.sin_dashboard:
        ok, _ = ejecutar("7. Dashboard con datos reales", [py, "generar_dashboard.py"])
        resultados["dashboard"] = ok
    else:
        resultados["dashboard"] = None

    # --- Resumen ---
    total, rango, dias = contar_historico()
    duracion = (datetime.datetime.now() - inicio).total_seconds()

    print("\n" + "#" * 72)
    print("# RESUMEN DEL CICLO")
    print("#" * 72)
    etiquetas = {
        "pipeline": "Descarga FIRMS y pipeline",
        "fusion": "Fusión con repo",
        "registro": "Fusión del registro de ejecuciones",
        "verificacion": "Verificación contra FIRMS",
        "integridad": "Integridad y recuperación",
        "reparacion": "Reparación de distrito",
        "matriz": "Matriz de campo",
        "dashboard": "Dashboard",
    }
    for clave, etiqueta in etiquetas.items():
        estado = resultados.get(clave)
        simbolo = "OK" if estado else ("OMITIDO" if estado is None else "FALLO")
        print(f"  {etiqueta:32s} {simbolo}")

    print()
    print(f"  Histórico            : {total} registros")
    print(f"  Rango de fechas      : {rango}")
    print(f"  Días con detecciones : {dias}")
    print(f"  Duración del ciclo   : {duracion:.1f} s")
    print("#" * 72)

    fallos = [k for k, v in resultados.items() if v is False]
    if fallos:
        print(f"\n[Fin] Ciclo completado con fallos en: {', '.join(fallos)}")
        return 1

    print("\n[Fin] Ciclo completado correctamente.")
    print("      Recuerda subir al repositorio: historico_leoncio_prado_2026.csv,")
    print("      registro_ejecuciones.csv, main.py, verificar_historico.py,")
    print("      generar_matriz_campo.py, generar_dashboard.py y index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
