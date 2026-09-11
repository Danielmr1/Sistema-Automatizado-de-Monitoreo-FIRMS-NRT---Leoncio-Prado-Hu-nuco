# Sistema Automatizado de Monitoreo FIRMS NRT — Provincia de Leoncio Prado (Huánuco)

Monitoreo de anomalías térmicas y quemas agrícolas a partir de datos satelitales de
**NASA FIRMS** (MODIS y VIIRS, modo NRT), con cálculo de accesibilidad vial para
salidas a campo y alertas por Telegram.

---

## Fuente de datos y trazabilidad

Todas las detecciones provienen de la API **NASA FIRMS** (Near Real-Time). El proyecto
**no usa datos simulados**: cada registro del histórico puede contrastarse contra la
respuesta cruda de la API con `verificar_historico.py`, que compara la clave única de una
detección (`latitude`, `longitude`, `acq_date`, `acq_time`) y sus campos físicos
(FRP, confidence, temperaturas de brillo).

La columna `verificado_firms` del histórico indica la fecha en que cada registro fue
respaldado contra la respuesta de NASA.

> **Límite de la API:** el parámetro de días acepta 1 a 5. No es posible reconstruir
> retroactivamente períodos anteriores, por lo que el histórico local es la fuente
> permanente de datos.

---

## Estructura

### Pipeline
| Archivo | Función |
|---|---|
| `main.py` | Descarga FIRMS, filtra por AOI y confianza, calcula accesibilidad y lluvia, genera CSV/KML/HTML y envía Telegram. |
| `sincronizar_datos.py` | Ejecuta el ciclo completo en orden (pipeline → fusión → verificación → integridad → distritos → matriz → dashboard). |
| `fusionar_historico.py` | Une el histórico local con el del repositorio sin perder registros. |
| `verificar_historico.py` | Contrasta el histórico contra NASA FIRMS y emite un informe. |
| `verificar_integridad.py` | **Detecta y recupera días perdidos.** La API solo conserva 5 días: sin este paso, una detección no guardada es irrecuperable. Distingue "día sin quemas" de "día no registrado". |
| `recuperar_dias.py` | Recupera manualmente una ventana de fechas concreta desde FIRMS. |
| `fusionar_registro.py` | Une el registro de ejecuciones local con el del repositorio (evita perder entradas). |
| `descargar_vias_osm.py` | Descarga la red vial **real** desde OpenStreetMap (259 tramos dentro del AOI, frente a los 3-14 vértices del archivo original). |
| `generar_matriz_campo.py` | Genera la matriz de salidas a campo desde el histórico verificado. |
| `generar_dashboard.py` | Incrusta el histórico y la red vial reales en `index.html`. |
| `reparar_distritos.py` | Asigna distrito y recalcula distancias viales en los registros ya guardados. |

### Datos
| Archivo | Función |
|---|---|
| `historico_leoncio_prado_2026.csv` | Histórico maestro acumulativo (29 columnas). |
| `registro_ejecuciones.csv` | Una línea por ejecución, incluso con 0 focos, con el estado y su causa. |
| `aoi_leoncio_prado.geojson` | Límite provincial oficial (filtro espacial). |
| `aoi_carreteras_leoncio_prado.geojson` | Red vial (PE-5N, PE-18A, HU-104 y trochas). |
| `distritos_leoncio_prado.geojson` | Los 10 distritos de la provincia con ubigeo INEI: permite asignar distrito y desglosar resultados. |

### Documentos y visor
| Archivo | Función |
|---|---|
| `index.html` | Dashboard **de solo visualización**: panel de estado, mapa, mapa de calor, filtros por fecha/distrito/año, gráficos, descargas y botón "Actualizar datos". |
| `EVENTOS_QUEMAS_CAMPO_TESIS.md` | Matriz de salidas a campo (generada, no editada a mano). |
| `README.md`, `GUIA_CONFIGURACION_Y_CAMPO.md` | Documentación. |

### Cómo se actualiza el dashboard

El dashboard **no ejecuta nada**: solo muestra lo que el workflow ya recogió.

* **Al abrirlo**: usa los datos incrustados por `generar_dashboard.py` (últimos 12 meses).
* **Botón "Actualizar datos"**: descarga el histórico más reciente desde GitHub. Es manual
  a propósito, para no consumir datos móviles sin que el usuario lo pida.
* **Botón "Cargar histórico"**: abre un CSV de tu equipo, útil sin conexión.
* **Sin internet**: sigue funcionando con los datos incrustados.

Si el dashboard no incluye todos los eventos del histórico, muestra un aviso indicando
cuántos quedaron fuera y cómo verlos.

### Automatización
`.github/workflows/firms_scouting.yml` ejecuta el pipeline a diario a las 12:00 UTC
(07:00 en Perú) y versiona el histórico y el registro de ejecuciones.

---

## Instalación y uso

```bash
pip install -r requirements.txt
```

La API key se lee **siempre** de una variable de entorno (nunca del código):

```powershell
# PowerShell (Windows)
$env:FIRMS_API_KEY="tu_map_key"
python main.py
```

```bash
# bash (Linux/macOS)
export FIRMS_API_KEY="tu_map_key"
python main.py
```

Obtén tu MAP_KEY gratuita en <https://firms.modaps.eosdis.nasa.gov/api/map_key/>.

### Ciclo completo

```bash
python sincronizar_datos.py
```

Ejecuta los 5 pasos y muestra un resumen. Opciones útiles:

```bash
python sincronizar_datos.py --dias 3          # ventana NRT de 3 días
python sincronizar_datos.py --sin-verificar   # omite el contraste contra FIRMS
```

### Comandos individuales

```bash
python main.py --incluir-baja-confianza   # guarda también las detecciones débiles (marcadas)
python verificar_historico.py --informe reporte.md --sellar
python generar_matriz_campo.py --dias 3 --solo-accesibles
python generar_dashboard.py
```

---

## Campos del histórico

Columnas originales de FIRMS más las de trazabilidad del proyecto:

| Campo | Descripción |
|---|---|
| `distrito` | Distrito del foco. Requiere `distritos_leoncio_prado.geojson`; sin él, etiqueta provincial. |
| `confianza_cruda` | `alta` / `nominal` / `baja`, normalizado entre MODIS y VIIRS. |
| `verificado_firms` | Fecha del contraste contra la respuesta de NASA. |
| `tipo_registro` | `validado` o `baja_confianza` (conservadas para análisis de omisión). |

Los campos `dist_carretera_km`, `tiempo_estimado` y `costo_estimado_pen` son
**estimaciones calculadas** a partir de la red vial, no mediciones de campo.

---

## Despliegue en GitHub Actions

1. Sube los archivos al repositorio.
2. En `Settings > Secrets and variables > Actions` configura:
   - `FIRMS_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. En `Settings > Actions > General > Workflow permissions` activa
   **Read and write permissions** para que el workflow pueda versionar los datos.

---

## Limitaciones conocidas

- La API de FIRMS solo permite consultar **5 días** hacia atrás.
- Sin un GeoJSON de distritos, la columna `distrito` no se puede desglosar.
- Las alertas de Telegram solo se envían si `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`
  están configurados; en caso contrario el pipeline lo informa y continúa.
- `index.html` lleva los datos incrustados (≈200 KB) porque un navegador no puede leer
  archivos locales por seguridad. Ejecuta `generar_dashboard.py` para actualizarlo.
