#!/usr/bin/env python3
"""
=============================================================================
Genera la matriz de salidas a campo desde el histórico verificado.
=============================================================================
Reemplaza el documento EVENTOS_QUEMAS_CAMPO_TESIS.md, que hasta ahora contenía
12 eventos con coordenadas, horas y FRP que NO existen en el archivo de NASA
FIRMS. Todo lo que produce este script sale del histórico consolidado, que fue
contrastado registro por registro contra la respuesta cruda de FIRMS.

Uso:
    python generar_matriz_campo.py                 # ventana de 30 días
    python generar_matriz_campo.py --dias 3        # plan corto de campaña
    python generar_matriz_campo.py --salida plan.md
    python generar_matriz_campo.py --solo-accesibles
"""

import os
import sys
import argparse
import datetime
import pandas as pd

HIST_PATH = "historico_leoncio_prado_2026.csv"
OUT_PATH = "EVENTOS_QUEMAS_CAMPO_TESIS.md"

ORDEN_ACCESIBILIDAD = {"ALTA": 0, "MEDIA": 1, "BAJA / REMOTA": 2}

TITULOS_GRUPO = {
    0: ("URGENCIA MAXIMA", "Detecciones de hoy. Ceniza fresca, limites nitidos de la cicatriz."),
    1: ("URGENCIA ALTA", "Ventana de 24 horas. Evidencia aun intacta."),
    2: ("PRIORIDAD MEDIA", "2 a 3 dias. Evidencia visible, posible carbon y afectacion de fuste."),
    3: ("SEGUIMIENTO", "4 a 6 dias. Validacion de cicatriz y calculo de severidad retrospectiva."),
}


def cargar_historico(path):
    if not os.path.exists(path):
        raise SystemExit(f"[Error] No existe {path}. Ejecuta primero main.py o fusionar_historico.py")
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"[Error] No se pudo leer {path}.")


def antiguedad_dias(fecha_acq, fecha_ref):
    try:
        return (fecha_ref - datetime.date.fromisoformat(str(fecha_acq))).days
    except (ValueError, TypeError):
        return None


def hora_local(hora_utc):
    """Convierte HHMM UTC a HH:MM local de Peru (UTC-5). Devuelve '' si no es valido."""
    s = str(hora_utc).strip().zfill(4)
    if not s.isdigit():
        return ""
    h, m = int(s[:2]), int(s[2:4])
    return f"{(h - 5) % 24:02d}:{m:02d} hora local Peru"


def formatear_foco(idx, fila, es_ultimo_del_grupo):
    lat, lon = float(fila["latitude"]), float(fila["longitude"])
    distrito = str(fila.get("distrito", "") or "Leoncio Prado")
    sensor = str(fila.get("source_sensor", ""))
    frp = fila.get("frp", "")
    conf = fila.get("confianza_cruda", "") or fila.get("confidence", "")
    dist_km = fila.get("dist_carretera_km", "")
    via = fila.get("carretera_cercana", "")
    acc = fila.get("accesibilidad", "")
    costo = fila.get("costo_estimado_pen", "")
    lluvia = fila.get("alerta_clima_campo", "")
    tipo = str(fila.get("tipo_registro", "validado"))

    lineas = [
        f"#### {idx}. Foco ({distrito})",
        f"* **Distrito:** {distrito}",
        f"* **Coordenadas:** `{lat:.5f}, {lon:.5f}` \u27a1\ufe0f "
        f"[Abrir en Google Maps](https://www.google.com/maps?q={lat:.5f},{lon:.5f})",
        f"* **Fecha y Hora:** {fila.get('acq_date', '')} | {fila.get('acq_time', '')} UTC "
        f"({hora_local(fila.get('acq_time', ''))})",
        f"* **Sensor:** {sensor} | Confianza: **{conf}**",
        f"* **Potencia Radiativa (FRP):** {frp} MW",
        f"* **Acceso:** {via} a {dist_km} km ({acc}) | Costo estimado: {costo}",
        f"* **Clima 24 h:** {lluvia}",
    ]
    if tipo == "baja_confianza":
        lineas.append("* **Aviso:** deteccion de baja confianza. Verificar en campo antes de "
                      "usarla como evidencia; sirve para analisis de omision.")
    lineas.append("")
    return "\n".join(lineas)


def main():
    parser = argparse.ArgumentParser(description="Genera la matriz de campo desde el histórico verificado")
    parser.add_argument("--historico", default=HIST_PATH)
    parser.add_argument("--salida", default=OUT_PATH)
    parser.add_argument("--dias", type=int, default=30,
                        help="Antiguedad maxima de las detecciones a incluir. Por defecto 30.")
    parser.add_argument("--solo-accesibles", action="store_true",
                        help="Incluir unicamente accesibilidad ALTA y MEDIA.")
    parser.add_argument("--fecha-ref", default=None,
                        help="Fecha de referencia YYYY-MM-DD (por defecto, hoy).")
    parser.add_argument("--top", type=int, default=0,
                        help="Limitar a los N focos de mayor FRP dentro de cada grupo (0 = sin limite).")
    args = parser.parse_args()

    df = cargar_historico(args.historico)
    print(f"[Matriz] Histórico: {len(df)} registros desde {args.historico}")

    fecha_ref = (datetime.date.fromisoformat(args.fecha_ref) if args.fecha_ref
                 else datetime.datetime.now(datetime.timezone.utc).date())

    df["_antiguedad"] = df["acq_date"].apply(lambda f: antiguedad_dias(f, fecha_ref))
    validos = df[df["_antiguedad"].notna() & (df["_antiguedad"] >= 0)].copy()
    descartados_futuro = len(df) - len(validos)

    seleccion = validos[validos["_antiguedad"] <= args.dias].copy()
    print(f"[Matriz] {len(seleccion)} detecciones dentro de los últimos {args.dias} días "
          f"(referencia {fecha_ref})")

    if args.solo_accesibles:
        antes = len(seleccion)
        seleccion = seleccion[seleccion["accesibilidad"].isin(["ALTA", "MEDIA"])]
        print(f"[Matriz] Filtro de accesibilidad: {antes} -> {len(seleccion)} focos (ALTA/MEDIA)")

    if seleccion.empty:
        print("[Matriz] No hay detecciones en la ventana solicitada. "
              "Amplía con --dias o revisa el histórico.")
        return

    # Orden de urgencia: más reciente primero, luego más accesible, luego más potente
    seleccion["_orden_acc"] = seleccion["accesibilidad"].map(ORDEN_ACCESIBILIDAD).fillna(3)
    seleccion["_frp_num"] = pd.to_numeric(seleccion["frp"], errors="coerce").fillna(0.0)
    seleccion = seleccion.sort_values(
        ["_antiguedad", "_orden_acc", "_frp_num"], ascending=[True, True, False]
    ).reset_index(drop=True)

    por_distrito = seleccion["distrito"].value_counts().to_dict()
    por_sensor = seleccion["source_sensor"].value_counts().to_dict()
    por_acc = seleccion["accesibilidad"].value_counts().to_dict()

    hoy_str = fecha_ref.isoformat()
    md = []
    md.append("# Matriz y Guía de Salidas a Campo: Verificación de Quemas Satelitales (FIRMS)")
    md.append(f"**Proyecto de Tesis:** Monitoreo y Validación de Anomalías Térmicas / Quemas "
              f"Agrícolas en la Provincia de Leoncio Prado (Huánuco)  ")
    md.append(f"**Generado:** {hoy_str} desde `{os.path.basename(args.historico)}`  ")
    md.append(f"**Ventana analizada:** últimos {args.dias} días  ")
    md.append(f"**Total de eventos en esta matriz:** {len(seleccion)}  ")
    md.append(f"**Fuente:** NASA FIRMS (MODIS + VIIRS NRT). Registros contrastados contra la "
              f"respuesta cruda de la API; campo `verificado_firms` del histórico indica la fecha del contraste.")
    md.append("")
    if descartados_futuro:
        md.append(f"> _Se omitieron {descartados_futuro} registros con fecha posterior a la de "
                  f"referencia._")
        md.append("")
    md.append("---")
    md.append("")

    md.append("## 1. Resumen de la ventana")
    md.append("")
    md.append(f"* **Focos:** {len(seleccion)}")
    md.append(f"* **Días con detecciones:** {seleccion['acq_date'].nunique()} "
              f"({seleccion['acq_date'].min()} a {seleccion['acq_date'].max()})")
    md.append(f"* **Por sensor:** " + ", ".join(f"{k}: {v}" for k, v in por_sensor.items()))
    md.append(f"* **Por accesibilidad:** " + ", ".join(f"{k}: {v}" for k, v in por_acc.items()))
    md.append(f"* **FRP máximo:** {seleccion['_frp_num'].max():.2f} MW | "
              f"**FRP medio:** {seleccion['_frp_num'].mean():.2f} MW")
    md.append("")
    md.append("### Distribución por distrito")
    md.append("")
    md.append("| Distrito | Focos |")
    md.append("| :--- | ---: |")
    for dist, n in sorted(por_distrito.items(), key=lambda x: -x[1]):
        md.append(f"| {dist} | {n} |")
    md.append("")
    md.append("---")
    md.append("")

    md.append("## 2. Catálogo de eventos por urgencia")
    md.append("")
    contador = 0
    for dias_ant in sorted(seleccion["_antiguedad"].unique()):
        grupo = seleccion[seleccion["_antiguedad"] == dias_ant]
        if args.top:
            grupo = grupo.head(args.top)
        idx_grupo = min(int(dias_ant), 3)
        titulo, justificacion = TITULOS_GRUPO[idx_grupo]
        etiqueta_dia = "hoy" if dias_ant == 0 else (
            "ayer" if dias_ant == 1 else f"hace {int(dias_ant)} días")
        md.append(f"### {titulo} — {etiqueta_dia} ({grupo['acq_date'].iloc[0]})")
        md.append("")
        md.append(f"_{justificacion} {len(grupo)} focos._")
        md.append("")
        for _, fila in grupo.iterrows():
            contador += 1
            md.append(formatear_foco(contador, fila, False))
        md.append("")

    md.append("---")
    md.append("")
    md.append("## 3. Circuitos logísticos sugeridos")
    md.append("")
    md.append("Agrupa los focos por corredor vial y fecha para minimizar traslados:")
    md.append("")
    md.append("| Corredor | Focos | Distrito(s) |")
    md.append("| :--- | ---: | :--- |")
    for via, grupo in seleccion.groupby("carretera_cercana"):
        vias_cortas = str(via).split(" (")[0]
        dists = ", ".join(sorted(grupo["distrito"].unique())[:3])
        md.append(f"| {vias_cortas} | {len(grupo)} | {dists} |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 4. Ficha de Registro de Campo (Ground Truth Form)")
    md.append("")
    md.append("Imprime una ficha por foco visitado. Estos son los campos que permitirán calcular")
    md.append("Precisión del Usuario, comisión y omisión en la matriz de confusión de la tesis.")
    md.append("")
    md.append("```markdown")
    md.append("=" * 78)
    md.append("FICHA DE VERIFICACIÓN DE QUEMA EN CAMPO (GROUND TRUTHING) - TESIS")
    md.append("=" * 78)
    md.append("N° de Foco / ID: _______________       Fecha de Visita: _____/_____/______")
    md.append("Distrito: ______________________       Hora de Visita:  _____:_____ AM/PM")
    md.append("Coordenadas GPS Satélite: Lat: _______________  Lon: _______________")
    md.append("Coordenadas GPS Campo:    Lat: _______________  Lon: _______________")
    md.append("Altitud: _____ msnm                    Sensor / FRP reportado: _______________")
    md.append("")
    md.append("1. ESTADO ACTUAL DEL EVENTO:")
    md.append("   [ ] Fuego activo visible / llamas")
    md.append("   [ ] Humo / brazas residuales")
    md.append("   [ ] Ceniza reciente (negra/gris fresca)")
    md.append("   [ ] Suelo quemado lixiviado (lluvia reciente)")
    md.append("   [ ] No se observa evidencia (posible falso positivo / techo de calamina caliente)")
    md.append("")
    md.append("2. TIPO DE COBERTURA VEGETAL AFECTADA:")
    md.append("   [ ] Purma o bosque secundario            [ ] Bosque primario / ripario")
    md.append("   [ ] Pastizal para ganadería              [ ] Rastrojo (cacao / café / plátano / maíz)")
    md.append("   [ ] Residuos de tala / desbroce")
    md.append("")
    md.append("3. SEVERIDAD DE LA QUEMA:")
    md.append("   [ ] Baja (hojarasca superficial)   [ ] Moderada (capa orgánica)")
    md.append("   [ ] Alta (biomasa leñosa, suelo mineralizado)")
    md.append("")
    md.append("4. ESTIMACIÓN DE ÁREA Y TOPOGRAFÍA:")
    md.append("   Área aproximada quemada: ____________ m²  o  ____________ ha")
    md.append("   Pendiente: [ ] Plano (0-5%)  [ ] Ondulado (5-25%)  [ ] Escarpado (>25%)")
    md.append("")
    md.append("5. CAUSA ANTRÓPICA APARENTE:")
    md.append("   [ ] Roce y quema para chacra nueva       [ ] Limpieza de maleza en cultivo")
    md.append("   [ ] Quema de pasturas                    [ ] Quema de basura")
    md.append("   [ ] Incendio forestal fuera de control")
    md.append("")
    md.append("6. REGISTRO FOTOGRÁFICO GEORREFERENCIADO:")
    md.append("   Foto N° 1 (Panorámica Norte):  ID: ______________")
    md.append("   Foto N° 2 (Panorámica Sur):    ID: ______________")
    md.append("   Foto N° 3 (Detalle de ceniza): ID: ______________")
    md.append("   Foto N° 4 (Límite no quemado): ID: ______________")
    md.append("")
    md.append("7. NOTAS Y TESTIMONIOS LOCALES:")
    md.append("   ____________________________________________________________________")
    md.append("   ____________________________________________________________________")
    md.append("=" * 78)
    md.append("```")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 5. Notas metodológicas")
    md.append("")
    md.append("1. **Ventana de validez:** en selva alta la evidencia se degrada rápido "
              "(0-48 h: ceniza fresca; 3-7 días: lluvia lixivia; >7 días: perímetro difuso).")
    md.append("2. **Traslape de sensores:** MODIS tiene píxel de 1 km y VIIRS de 375 m. Varios "
              "registros cercanos pueden ser el mismo frente de quema; conviene agruparlos en campo.")
    md.append("3. **Campos estimados:** `dist_carretera_km`, `tiempo_estimado` y "
              "`costo_estimado_pen` son estimaciones calculadas, no mediciones. Úsalos para "
              "planificar, no como dato duro.")
    md.append("4. **Trazabilidad:** el campo `verificado_firms` del histórico indica la fecha en "
              "que el registro se contrastó contra la respuesta cruda de NASA FIRMS.")
    md.append("5. **Nubosidad:** en selva alta es el factor limitante de los sensores ópticos. "
              "Anota la cobertura de nubes del día reportado al calcular omisión.")
    md.append("")

    contenido = "\n".join(md)

    if os.path.exists(args.salida):
        respaldo = f"{args.salida}.bak_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.replace(args.salida, respaldo)
        print(f"[Respaldo] El documento anterior se guardó en {respaldo}")

    with open(args.salida, "w", encoding="utf-8") as f:
        f.write(contenido)

    print(f"[Matriz] Documento generado: {args.salida}")
    print(f"[Matriz] {len(seleccion)} focos | {seleccion['acq_date'].nunique()} días | "
          f"{len(por_distrito)} distrito(s)")


if __name__ == "__main__":
    main()
