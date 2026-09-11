# Guía de ejecución local (Windows / PowerShell)

Cómo ejecutar el sistema en tu computadora y qué hacer antes de una salida a campo.

---

## 1. Lo primero: usa `py`, no `python`

Tu equipo tiene **cuatro intérpretes de Python** instalados, y el comando `python` apunta al
equivocado:

```
C:\Program Files\Inkscape\bin\python.exe                            <- sin pandas  (el que usa "python")
D:\proy_python\Streamlit_nuevo\env\Scripts\python.exe               <- con pandas
C:\Users\Daniel\AppData\Local\Programs\Python\Python311\python.exe  <- con pandas  (el que usa "py")
C:\Users\Daniel\AppData\Local\Microsoft\WindowsApps\python.exe
```

Inkscape quedó primero en el PATH, así que si escribes `python` obtienes su intérprete y el
sistema falla con:

```
ModuleNotFoundError: No module named 'pandas'
```

**Solución:** usa el lanzador `py`, que apunta al Python 3.11 correcto.

| En vez de | Escribe |
| :--- | :--- |
| `python script.py` | **`py script.py`** |

### Cómo comprobar que el intérprete es el correcto

```powershell
py -c "import pandas; print('pandas', pandas.__version__)"
```

Debe responder algo como `pandas 2.1.4`. Si dice `ModuleNotFoundError`, estás usando el Python
equivocado.

---

## 2. Ir a la carpeta del proyecto

PowerShell no abre en la carpeta del proyecto, así que el primer comando siempre es:

```powershell
cd "D:\Monitoreo de quemas"
```

Si no lo haces, verás errores del tipo *"no se puede encontrar el archivo"*.

### Prueba rápida de que todo está en su sitio

```powershell
py verificar_integridad.py --solo-estado
```

Este comando no usa internet. Si responde con algo como:

```
Registros : 312
Fechas    : 2026-08-23 .. 2026-09-10
Días      : 12
```

entonces estás en la carpeta correcta y con el Python correcto.

---

## 3. Configurar las claves (solo si descargas datos)

Solo hace falta para las tareas que consultan la API de NASA. **No** se necesita para
regenerar el dashboard ni la matriz de campo.

```powershell
$env:FIRMS_API_KEY="TU_MAP_KEY_DE_FIRMS"
$env:TELEGRAM_BOT_TOKEN="TU_TOKEN_DE_BOTFATHER"
$env:TELEGRAM_CHAT_ID="TU_CHAT_ID"
```

Duran solo mientras esa ventana de PowerShell esté abierta. Si la cierras, hay que volver a
definirlas.

> No escribas las claves en el código ni en documentos. El sistema las lee siempre del entorno.

---

## 4. Los comandos, y para qué sirve cada uno

| Comando | Qué hace | ¿Necesita internet? |
| :--- | :--- | :--- |
| `py sincronizar_datos.py` | Ciclo completo: descarga, fusiona, verifica, repara distritos, genera matriz y dashboard | Sí |
| `py main.py --incluir-baja-confianza` | Solo la descarga de FIRMS y el pipeline principal | Sí |
| `py verificar_integridad.py` | Detecta y recupera días perdidos | Sí |
| `py verificar_historico.py --informe reporte.md` | Contrasta el histórico contra NASA FIRMS | Sí |
| `py generar_matriz_campo.py --dias 3 --solo-accesibles` | Plan de salidas a campo | No |
| `py generar_dashboard.py` | Regenera `index.html` con los datos actuales | No |
| `py descargar_vias_osm.py` | Vuelve a bajar la red vial real desde OpenStreetMap | Sí |

---

## 5. Uso habitual

### Para mantener el sistema al día

```powershell
cd "D:\Monitoreo de quemas"
$env:FIRMS_API_KEY="tu_key"
py sincronizar_datos.py
```

Después hay que **subir el `index.html` y el `historico_...csv`** al repositorio, si quieres que
la página publicada refleje los cambios.

### Antes de una salida a campo

Hay **dos formas** de obtener el plan de campo. La del dashboard es la más cómoda; la de
PowerShell sirve cuando quieres el documento reproducible para la tesis.

#### Opción A — Desde el dashboard (recomendada para el día de campo)

1. Abre el dashboard (el publicado o el `index.html` local).
2. Pulsa **"Actualizar datos"** para traer los focos recientes.
3. Ajusta los filtros: rango de fechas (por ejemplo "Últimos 3 días") y el selector de
   **accesibilidad**.
4. Revisa que los focos que aparecen en el mapa y la tabla son los que esperas.
5. Ve a la pestaña **"Descargar Alertas (CSV/KML)"** y pulsa **"Descargar plan de campo"**.

Se descarga `plan_campo_<fecha>.md` con los focos de tu selección. El panel te dice antes
cuántos focos incluirá, para que no descargues un plan vacío sin darte cuenta.

**Ventaja:** puedes verificar en el mapa antes de descargar, y funciona desde el celular.

#### Opción B — Desde PowerShell (para la tesis)

```powershell
cd "D:\Monitoreo de quemas"

# 1. Traer los datos más recientes
py sincronizar_datos.py

# 2. Regenerar el dashboard (respaldo offline con datos frescos)
py generar_dashboard.py

# 3. Generar el plan de campo de los últimos 3 días
py generar_matriz_campo.py --dias 3 --solo-accesibles

# 4. Subir index.html al repositorio (a mano, con Add file -> Upload files)
```

**Ventaja:** el documento queda reproducible y auditable, con el archivo de origen y la fecha
en el encabezado. Un jurado puede verificar cómo se generó.

Ambas opciones producen **los mismos focos**. Se verificó comparando las coordenadas de los
dos métodos con los datos reales: 9 focos, coincidencia total.

**Por qué conviene usar `--dias 3` (o el filtro equivalente):** en selva alta la evidencia se
degrada rápido. Después de 48 horas la ceniza se lava con la lluvia y a los 7 días ya no se
delimita el perímetro de la quema. No tiene sentido viajar a verificar algo de hace un mes.

**Por qué filtrar por accesibilidad:** descarta los focos de acceso "BAJA / REMOTA", que
requieren bote o más de 1,5 horas de caminata. Con pocos días de campo no conviene gastarlos
en un punto remoto.

### Filtros disponibles en el dashboard

En la barra "Filtrar por fecha" puedes combinar libremente:

| Filtro | Opciones |
| :--- | :--- |
| Rango temporal | Todo · 24 h · 3 días · 7 días · 30 días · día concreto · semana ISO · rango a mano |
| Distrito | Los 10 distritos, con el conteo de cada uno |
| Año | Para comparar temporadas entre años |
| **Accesibilidad** | Alta (<1 km) · Media (1-3 km) · Remota (>3 km) |

El **plan de campo se genera con la combinación de filtros que tengas activa**, incluida la
accesibilidad. Por eso el flujo es: filtrar → revisar en el mapa → descargar el plan.

### Dos documentos distintos: catálogo y plan

Hay **dos formas** de obtener el plan, y producen **documentos distintos** a propósito:

| Documento | Quién lo genera | Ventana | Para qué |
| :--- | :--- | :--- | :--- |
| `EVENTOS_QUEMAS_CAMPO_TESIS.md` | Python (PowerShell) | 30 días | **Catálogo** de la temporada, reproducible y auditable |
| `plan_campo_<fecha>.md` | Python **o** el dashboard | 3 días, accesibles | **Plan de viaje** del día |

El script de Python decide solo: si usas `--dias` de 7 o menos, o `--solo-accesibles`, escribe
en `plan_campo_<fecha>.md` y **no toca el catálogo**. Solo sobrescribe el catálogo cuando
generas una ventana larga sin filtro de accesibilidad. También puedes forzarlo con `--plan`, o
elegir el nombre con `--salida archivo.md`.

### Parámetros de la matriz de campo

| Parámetro | Efecto |
| :--- | :--- |
| `--dias N` | Antigüedad máxima de los focos (por defecto 30) |
| `--solo-accesibles` | Solo accesibilidad ALTA y MEDIA |
| `--top N` | Los N focos de mayor FRP por grupo |
| `--plan` | Fuerza la salida a `plan_campo_<fecha>.md` |
| `--salida archivo.md` | Nombre de archivo concreto |
| `--fecha-ref YYYY-MM-DD` | Fecha de referencia (por defecto, hoy) |

---

## 6. Errores frecuentes y qué significan

| Mensaje | Causa | Solución |
| :--- | :--- | :--- |
| `ModuleNotFoundError: No module named 'pandas'` | Usaste `python` en vez de `py` | Cambia a `py` |
| `can't open file '...': [Errno 2] No such file` | No estás en la carpeta del proyecto | `cd "D:\Monitoreo de quemas"` |
| `FIRMS_API_KEY no configurada` en el registro | Falta la variable de entorno | Definir `$env:FIRMS_API_KEY` |
| `Invalid MAP_KEY` | La clave es incorrecta o fue revocada | Generar una nueva en FIRMS |
| `UnicodeEncodeError` | Aparece en versiones antiguas de los scripts | Actualiza los scripts desde el repositorio |
| El comando no hace nada y vuelve al prompt | Normal en algunos pasos si no hay datos nuevos | Revisar el mensaje final |

---

## 7. Reglas prácticas

1. **Siempre `py`, nunca `python`.**
2. **Siempre `cd` a la carpeta del proyecto** antes de ejecutar.
3. **Antes de viajar a campo:** los 4 pasos de la sección 5.
4. **El dashboard publicado se actualiza solo para datos**, con el botón "Actualizar datos".
   Solo hay que volver a subir `index.html` si cambia la interfaz o si quieres refrescar el
   respaldo offline.
5. **No borres eventos antiguos.** El histórico es el activo de la tesis y los datos de FIRMS
   son irrecuperables después de 5 días.

---

## 8. Documentos relacionados

| Documento | Contenido |
| :--- | :--- |
| `README.md` | Visión general del proyecto y estructura de archivos |
| `GUIA_CONFIGURACION_Y_CAMPO.md` | Configurar Telegram, secrets de GitHub y trabajo de campo |
| `GUIA_SUBIDA_AL_REPO.md` | Cómo subir los archivos al repositorio |
| `EVENTOS_QUEMAS_CAMPO_TESIS.md` | La matriz de campo generada (no editar a mano) |
| `reporte_verificacion_*.md` | Informe de contraste del histórico contra NASA FIRMS |
