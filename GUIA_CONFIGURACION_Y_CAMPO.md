# 📘 Guía Maestra de Configuración, Alertas Telegram y Salidas a Campo

Este documento contiene la guía paso a paso para poner a funcionar el sistema en la nube (GitHub Actions) o en tu computadora local, configurar Telegram y sacarle el máximo provecho para tu trabajo de tesis en Leoncio Prado.

---

## 🔑 1. Configuración de Telegram (Paso a Paso en 3 Minutos)

Telegram es la mejor opción para este proyecto porque:
1. Es **100% gratuito e ilimitado**.
2. Permite enviar archivos adjuntos pesados (Mapas HTML, CSV y KML).
3. Llega como notificación instantánea a tu celular con enlaces directos a Google Maps.

### Paso 1.1: Crear tu Bot de Telegram
1. Abre tu aplicación de **Telegram** en el celular o PC.
2. En el buscador de Telegram, busca el usuario oficial **`@BotFather`** (fíjate que tenga la insignia azul de verificación).
3. Entra al chat y presiona **Iniciar** (o envía `/start`).
4. Escribe el comando: `/newbot`
5. El bot te pedirá un nombre público (ejemplo: `Monitoreo Quemas Leoncio Prado`).
6. Luego te pedirá un nombre de usuario que termine en `bot` (ejemplo: `LeoncioPradoQuemas_bot` o `TesisQuemasTingo_bot`).
7. BotFather te responderá con un mensaje de felicitaciones y tu **Token de Acceso**.
   * Se verá algo así: `7182938491:AAFlkW9X8Z_xxxxxxxxxxxxxxxxxxxx`
   * 👉 **Este es tu `TELEGRAM_BOT_TOKEN`.**

### Paso 1.2: Obtener tu Chat ID (Tu ID personal de Telegram)
1. En el buscador de Telegram, busca el bot **`@userinfobot`** o **`@raw_data_bot`**.
2. Presiona **Iniciar** (`/start`).
3. Te responderá inmediatamente con tu información. Busca la línea que dice **`Id:`** (un número de 9 o 10 dígitos, ejemplo: `123456789`).
   * 👉 **Este número es tu `TELEGRAM_CHAT_ID`.**

### Paso 1.3: Iniciar conversación con tu propio Bot
* Busca el nombre de usuario de tu bot que creaste en el paso 1.1 (ejemplo: `@LeoncioPradoQuemas_bot`).
* Entra al chat y presiona **INICIAR** (`/start`).  
*(¡Es obligatorio darle "Iniciar" para que el bot tenga permiso de enviarte mensajes y archivos!).*

---

## ☁️ 2. ¿Dónde poner tus claves en GitHub? (GitHub Secrets)

Nunca pongas tus claves directamente en el código público de GitHub. Se configuran de manera segura y encriptada así:

1. Entra a tu repositorio en **GitHub** desde tu navegador.
2. Ve a la pestaña **`Settings`** (la rueda de engranaje arriba a la derecha).
3. En el menú lateral izquierdo, haz clic en **`Secrets and variables`** y luego en **`Actions`**.
4. Haz clic en el botón verde **`New repository secret`**.
5. Agrega los siguientes 3 secretos uno por uno:

| Nombre del Secreto (`Name`) | Valor (`Secret`) |
| :--- | :--- |
| **`FIRMS_API_KEY`** | *(Tu MAP_KEY de FIRMS — ver paso 0 abajo)* |
| **`TELEGRAM_BOT_TOKEN`** | *(El token provisto por @BotFather)* |
| **`TELEGRAM_CHAT_ID`** | *(Tu número de ID provisto por @userinfobot)* |

> ⚠️ **Paso 0 — Obtén una MAP_KEY nueva.**
> La clave que se usó antes quedó escrita en este documento y en copias del repositorio,
> así que debe considerarse **comprometida**. Solicita una nueva (es gratis e inmediata) en
> <https://firms.modaps.eosdis.nasa.gov/api/map_key/> e ingrésala como secreto.
> **Nunca escribas la clave en el código ni en esta guía.** El sistema la lee siempre de la
> variable de entorno `FIRMS_API_KEY`.

6. **Permisos de Escritura del Workflow:**
   * En `Settings > Actions > General > Workflow permissions`, selecciona **"Read and write permissions"** y haz clic en **Save**. Esto permite que GitHub Actions guarde el histórico automáticamente.

---

## 🗺️ 3. El Área de Estudio (`aoi_leoncio_prado.geojson`)

* El archivo `aoi_leoncio_prado.geojson` que ya está en tu carpeta contiene el polígono georreferenciado oficial de la provincia de **Leoncio Prado** con sus 10 distritos (Rupa-Rupa, José Crespo y Castillo, Castillo Grande, Luyando, Daniel Alomía Robles, Mariano Dámaso Beraún, Hermilio Valdizán, Pucayacu, Pueblo Nuevo y Santo Domingo de Anda).
* Si en el futuro deseas cambiar el área de estudio (por ejemplo a un distrito específico como Castillo Grande o a toda la región Huánuco), simplemente reemplazas el archivo `aoi_leoncio_prado.geojson` con el nuevo polígono y el sistema se adaptará automáticamente.

---

## 💻 4. ¿Cómo probarlo en tu computadora local ahora mismo?

Si quieres ejecutar el script en tu computadora antes de subirlo a GitHub:

1. Abre tu terminal de **PowerShell** en la carpeta del proyecto.
2. Define temporalmente tus variables de entorno ejecutando:
   ```powershell
   $env:FIRMS_API_KEY="TU_MAP_KEY_DE_FIRMS"
   $env:TELEGRAM_BOT_TOKEN="TU_TOKEN_DE_BOTFATHER"
   $env:TELEGRAM_CHAT_ID="TU_CHAT_ID"
   ```
3. Ejecuta el ciclo completo (recomendado):
   ```powershell
   python sincronizar_datos.py
   ```
   O bien el pipeline solo:
   ```powershell
   python main.py --incluir-baja-confianza
   ```
4. El sistema descargará las anomalías reales de las últimas 48 h, calculará las distancias a
   la red vial oficial, verificará la lluvia y te enviará la alerta a Telegram con el mapa HTML,
   CSV y KML. Además registrará la ejecución en `registro_ejecuciones.csv`, incluso si ese día
   no hubo detecciones.

### Comprobar que los datos son reales

Si alguna vez necesitas demostrar que el histórico no contiene datos simulados:

```powershell
python verificar_historico.py --informe reporte_verificacion.md
```

Descarga la respuesta cruda de NASA FIRMS y contrasta registro por registro las coordenadas,
la fecha, la hora y los campos físicos (FRP, confianza, temperaturas de brillo). El informe
indica cuántos coinciden exactamente y cuántos quedan fuera de la ventana verificable
(la API solo conserva 5 días hacia atrás).

### Si el proceso no encuentra la clave

El sistema falla de forma explícita con `estado=error, detalle=FIRMS_API_KEY no configurada`
en lugar de reportar "sin detecciones". Si ves ese mensaje, la variable de entorno no está
definida en esa sesión de terminal.

---

## 💡 5. Sugerencias Clave para tu Tesis y Salidas a Campo

### A. Uso del archivo `.KML` sin Internet en la Selva
En muchas zonas de Leoncio Prado (Monzón, Anda, Pucayacu selva adentro) no hay señal 4G.
* El bot de Telegram te enviará el archivo `alertas_YYYYMMDD.kml`.
* Instala en tu celular la app gratuita **Organic Maps**, **OruxMaps** o **Google Earth**.
* Toca el archivo `.kml` recibido en Telegram y ábrelo con la app de mapas. Verás todos los puntos de quema sobre el mapa satelital offline con navegación GPS en tiempo real.

### B. Análisis de Costo y Accesibilidad Incorporado
El script calcula automáticamente:
* **Distancia métrica a la carretera más cercana** (PE-5N Fernando Belaúnde Terry, PE-18A Federico Basadre, HU-104 o caminos vecinales).
* **Costo estimado de transporte local** (Mototaxi S/. 5-10, Colectivo rural S/. 15-30, Transporte especial > S/. 40).
* **Tiempo estimado de caminata** según la distancia.

### C. Sensor de Lluvia Automático (Protección de Evidencia)
* El script consulta automáticamente el servicio meteorológico `Open-Meteo` para cada coordenada.
* Si llovió más de 8 mm en las últimas 24 horas, te alertará: `🌧️ Lluvia fuerte: Ceniza probablemente lavada`. Así sabrás de antemano si conviene priorizar otros puntos con evidencia intacta.

### D. Enlaces de Navegación de un Toque
Cada alerta en Telegram y cada registro en el CSV incluye un enlace directo:
`https://www.google.com/maps/dir/?api=1&destination=LAT,LON`
Al tocarlo en tu celular, Google Maps abrirá la ruta guiada paso a paso hasta el punto de la quema.
