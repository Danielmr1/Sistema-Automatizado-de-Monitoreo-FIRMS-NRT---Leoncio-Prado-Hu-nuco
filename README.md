# Sistema Automatizado de Monitoreo FIRMS NRT - Provincia de Leoncio Prado, Huánuco

Proyecto de investigación y monitoreo automatizado de anomalías térmicas y quemas agrícolas en Leoncio Prado (Huánuco, Perú).

## 🚀 Despliegue Rápido en GitHub Actions

1. Crea un repositorio en GitHub y sube todos los archivos de esta carpeta.
2. Configura los **Secrets** en `Settings > Secrets and variables > Actions`:
   - `FIRMS_API_KEY`: Tu clave de NASA FIRMS ([Obtener aquí](https://firms.modaps.eosdis.nasa.gov/api/map_key/))
   - `TELEGRAM_BOT_TOKEN`: Token de tu bot de Telegram provisto por @BotFather
   - `TELEGRAM_CHAT_ID`: Tu ID de chat provisto por @userinfobot
3. Habilita permisos de escritura en `Settings > Actions > General > Workflow permissions > Read and write permissions`.
4. El sistema se ejecutará diariamente a las **12:00 UTC (07:00 AM hora de Perú)** y te enviará alertas con CSV y mapa HTML interactivo cuando se detecten quemas.
