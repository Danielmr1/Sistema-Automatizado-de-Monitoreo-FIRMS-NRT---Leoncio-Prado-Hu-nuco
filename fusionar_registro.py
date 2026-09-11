#!/usr/bin/env python3
"""
=============================================================================
Fusiona el registro de ejecuciones local con el del repositorio.
=============================================================================
El registro de ejecuciones es un acumulativo: cada corrida añade una línea.
Si el workflow corre en GitHub y además ejecutas el pipeline en local, cada
uno escribe su propio archivo. Sobrescribir uno con el otro borra entradas.

Este script une ambos, elimina duplicados y ordena cronológicamente.

Uso:
    python fusionar_registro.py
    python fusionar_registro.py --descargar   # trae el del repo desde GitHub
"""

import io
import os
import sys
import csv
import shutil
import argparse
import datetime
import requests

import pandas as pd

ARCHIVO = "registro_ejecuciones.csv"
REPO = "Danielmr1/Sistema-Automatizado-de-Monitoreo-FIRMS-NRT---Leoncio-Prado-Hu-nuco"
CLAVE = ["fecha_utc", "hora_utc", "sensores_consultados", "registros_crudos_bbox"]


def leer(path):
    if not os.path.exists(path):
        return None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"[Error] No se pudo leer {path}.")


def main():
    parser = argparse.ArgumentParser(description="Fusiona el registro de ejecuciones")
    parser.add_argument("--local", default=ARCHIVO)
    parser.add_argument("--repo", default="_gh_registro.csv",
                        help="Copia local del registro del repositorio")
    parser.add_argument("--descargar", action="store_true",
                        help="Descargar el registro del repositorio desde GitHub")
    args = parser.parse_args()

    if args.descargar:
        url = f"https://raw.githubusercontent.com/{REPO}/main/{ARCHIVO}"
        print(f"[GitHub] Descargando {url}")
        r = requests.get(url, timeout=120)
        if r.status_code != 200:
            raise SystemExit(f"[Error] HTTP {r.status_code} al descargar el registro.")
        with open(args.repo, "wb") as f:
            f.write(r.content)
        print(f"[GitHub] Guardado en {args.repo}")

    df_local = leer(args.local)
    df_repo = leer(args.repo)

    if df_local is None and df_repo is None:
        raise SystemExit("[Error] No hay ningún registro que fusionar.")
    if df_repo is None:
        print(f"[Aviso] No existe {args.repo}; nada con qué fusionar. Usa --descargar.")
        return 0
    if df_local is None:
        shutil.copy2(args.repo, args.local)
        print(f"[Copiado] {args.repo} -> {args.local}")
        return 0

    print(f"  Local: {len(df_local)} entradas")
    print(f"  Repo : {len(df_repo)} entradas")

    todas = list(df_local.columns)
    for c in df_repo.columns:
        if c not in todas:
            todas.append(c)
    df_local = df_local.reindex(columns=todas)
    df_repo = df_repo.reindex(columns=todas)

    combinado = pd.concat([df_repo, df_local], ignore_index=True)
    claves = [c for c in CLAVE if c in combinado.columns]

    antes = len(combinado)
    combinado = combinado.drop_duplicates(subset=claves, keep="first")
    combinado = combinado.sort_values(["fecha_utc", "hora_utc"]).reset_index(drop=True)

    respaldo = f"{args.local}.bak_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(args.local, respaldo)
    combinado.to_csv(args.local, index=False, encoding="utf-8-sig")

    print(f"\n[Fusión] {antes} -> {len(combinado)} entradas "
          f"({antes - len(combinado)} duplicadas removidas)")
    print(f"[Respaldo] {respaldo}")
    print(f"[Guardado] {args.local}")
    print(f"\nRango: {combinado['fecha_utc'].min()} a {combinado['fecha_utc'].max()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
