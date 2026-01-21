import os
import logging
import tempfile
import requests
from pathlib import Path
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import subprocess
import asyncio
from urllib.parse import urlparse
import json

# Configuración
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("No se encontró TELEGRAM_BOT_TOKEN en las variables de entorno")

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuración de FFmpeg
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB máximo para video de entrada
COMPRESSION_LEVELS = {
    "bajo": {"crf": 28, "preset": "medium", "desc": "Calidad alta, compresión moderada"},
    "medio": {"crf": 32, "preset": "slow", "desc": "Balance calidad/tamaño"},
    "alto": {"crf": 36, "preset": "veryslow", "desc": "Máxima compresión, calidad aceptable"}
}

# Crear directorio temporal si no existe
TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejador del comando /start"""
    welcome_text = """
🤖 *Bot Compresor de Videos*

¡Hola! Soy un bot que puede comprimir videos desde enlaces directos.

📤 *Cómo usarme:*
1. Envíame un enlace directo a un video (http://...)
2. Elige el nivel de compresión
3. Recibe tu video comprimido

⚠️ *Limitaciones:*
- Videos máximo 50MB
- Formatos soportados: MP4, AVI, MOV, MKV, WEBM
- Procesamiento tarda de 30 segundos a 2 minutos

📝 *Comandos disponibles:*
/start - Muestra este mensaje
/help - Ayuda y ejemplos
/compression - Explica niveles de compresión

🎯 *Ejemplo de enlace válido:*
`https://ejemplo.com/video.mp4`
"""
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejador del comando /help"""
    help_text = """
🆘 *Ayuda - Cómo usar el bot*

📤 *Pasos para comprimir:*
1. Envía un enlace directo al video
   Ejemplo: `https://tuservidor.com/video.mp4`
2. Elige el nivel de compresión
   - Bajo: Calidad casi original
   - Medio: Balance recomendado
   - Alto: Máxima reducción
3. Espera el procesamiento
4. Descarga tu video comprimido

⚠️ *Requisitos del enlace:*
- Debe ser acceso directo (no página web)
- El servidor debe permitir descargas
- Sin autenticación requerida

🔧 *Problemas comunes:*
- Enlace no válido: Asegúrate que sea .mp4, .avi, etc.
- Tiempo de espera: Videos grandes tardan más
- Error de formato: Intenta con otro video

📞 *Soporte:* Contacta al desarrollador si hay problemas.
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def compression_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Información sobre niveles de compresión"""
    info_text = """
⚙️ *Niveles de Compresión*

🔵 *BAJO (Calidad Alta)*
- Calidad: Casi idéntica al original
- Reducción: 20-40% del tamaño
- Uso: Cuando la calidad es prioridad
- Config: CRF 28, Preset Medium

🟡 *MEDIO (Balanceado)*
- Calidad: Buena, pequeñas diferencias
- Reducción: 40-60% del tamaño
- Uso: Uso general recomendado
- Config: CRF 32, Preset Slow

🔴 *ALTO (Máxima Compresión)*
- Calidad: Aceptable para móviles
- Reducción: 60-80% del tamaño
- Uso: Cuando el tamaño es crítico
- Config: CRF 36, Preset VerySlow

💡 *Recomendación:* Prueba con MEDIO primero.
"""
    await update.message.reply_text(info_text, parse_mode='Markdown')

def is_valid_video_url(url):
    """Verifica si la URL parece ser un video"""
    try:
        parsed = urlparse(url)
        if not parsed.scheme in ['http', 'https']:
            return False
        
        # Verificar extensión de video común
        path_lower = parsed.path.lower()
        video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.m4v']
        return any(path_lower.endswith(ext) for ext in video_extensions)
    except:
        return False

async def download_video(url, chat_id):
    """Descarga el video desde la URL"""
    try:
        # Verificar URL primero
        if not is_valid_video_url(url):
            return None, "❌ Enlace no válido. Debe ser un enlace directo a video (.mp4, .avi, etc.)"
        
        # Obtener información del archivo
        head_response = requests.head(url, allow_redirects=True, timeout=10)
        content_length = head_response.headers.get('Content-Length')
        
        if content_length:
            file_size = int(content_length)
            if file_size > MAX_FILE_SIZE:
                return None, f"❌ Video demasiado grande ({file_size/1024/1024:.1f}MB). Máximo: {MAX_FILE_SIZE/1024/1024}MB"
        
        content_type = head_response.headers.get('Content-Type', '')
        if 'video' not in content_type and not any(ext in url.lower() for ext in ['.mp4', '.avi', '.mov']):
            return None, "❌ El enlace no parece ser un video válido"
        
        # Descargar el video
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_filename = f"original_{chat_id}_{timestamp}.mp4"
        original_path = TEMP_DIR / original_filename
        
        logger.info(f"Descargando video desde {url}")
        
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        with open(original_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Verificar tamaño del archivo descargado
        actual_size = os.path.getsize(original_path)
        if actual_size > MAX_FILE_SIZE:
            os.remove(original_path)
            return None, f"❌ Video descargado demasiado grande ({actual_size/1024/1024:.1f}MB). Máximo: {MAX_FILE_SIZE/1024/1024}MB"
        
        return original_path, None
    
    except requests.exceptions.Timeout:
        return None, "❌ Tiempo de espera agotado. El servidor no responde."
    except requests.exceptions.RequestException as e:
        return None, f"❌ Error al descargar: {str(e)}"
    except Exception as e:
        return None, f"❌ Error inesperado: {str(e)}"

def compress_video(input_path, compression_level="medio"):
    """Comprime el video usando FFmpeg"""
    try:
        # Obtener configuración de compresión
        config = COMPRESSION_LEVELS.get(compression_level, COMPRESSION_LEVELS["medio"])
        
        # Generar nombre para archivo comprimido
        output_filename = f"compressed_{os.path.basename(input_path).replace('original_', '')}"
        output_path = TEMP_DIR / output_filename
        
        # Comando FFmpeg para compresión
        cmd = [
            'ffmpeg',
            '-i', str(input_path),
            '-vcodec', 'libx264',
            '-crf', str(config['crf']),
            '-preset', config['preset'],
            '-acodec', 'aac',
            '-movflags', '+faststart',
            '-y',  # Sobrescribir si existe
            str(output_path)
        ]
        
        logger.info(f"Ejecutando compresión: {' '.join(cmd)}")
        
        # Ejecutar FFmpeg
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minutos máximo
        )
        
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            return None, f"❌ Error en compresión: {result.stderr[:200]}"
        
        # Verificar si se creó el archivo
        if not os.path.exists(output_path):
            return None, "❌ No se pudo crear el archivo comprimido"
        
        output_size = os.path.getsize(output_path)
        if output_size == 0:
            os.remove(output_path)
            return None, "❌ Archivo comprimido está vacío"
        
        return output_path, None
    
    except subprocess.TimeoutExpired:
        return None, "❌ Tiempo de compresión agotado (5 minutos). Video muy largo."
    except Exception as e:
        return None, f"❌ Error en compresión: {str(e)}"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejador de mensajes de texto (enlaces)"""
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    
    # Verificar si es un enlace
    if message_text.startswith(('http://', 'https://')):
        await update.message.reply_text(
            "📥 *Enlace recibido*\n"
            "Descargando video... Esto puede tardar unos momentos.",
            parse_mode='Markdown'
        )
        
        # Descargar video
        original_path, error = await asyncio.to_thread(
            download_video, message_text, user_id
        )
        
        if error:
            await update.message.reply_text(error)
            return
        
        # Guardar path temporalmente
        context.user_data['original_path'] = str(original_path)
        
        # Enviar opciones de compresión
        keyboard = [
            ["⚡ Baja compresión (Calidad alta)"],
            ["⚖️ Compresión media (Balanceado)"],
            ["🗜️ Alta compresión (Máximo reducción)"]
        ]
        
        reply_markup = {
            "keyboard": keyboard,
            "resize_keyboard": True,
            "one_time_keyboard": True
        }
        
        await update.message.reply_text(
            "✅ *Video descargado correctamente*\n"
            f"Tamaño: {os.path.getsize(original_path)/1024/1024:.1f} MB\n\n"
            "📊 *Elige el nivel de compresión:*\n"
            "• ⚡ Bajo: Calidad casi original\n"
            "• ⚖️ Medio: Balance recomendado\n"
            "• 🗜️ Alto: Máxima reducción de tamaño",
            parse_mode='Markdown',
            reply_markup=json.dumps(reply_markup)
        )
    
    # Manejar selección de compresión
    elif 'original_path' in context.user_data and any(
        keyword in update.message.text.lower() 
        for keyword in ['baja', 'media', 'alta']
    ):
        text = update.message.text.lower()
        
        if 'baja' in text:
            level = "bajo"
        elif 'media' in text:
            level = "medio"
        elif 'alta' in text:
            level = "alto"
        else:
            level = "medio"
        
        original_path = context.user_data['original_path']
        
        await update.message.reply_text(
            f"🔄 *Comprimiendo video...*\n"
            f"Nivel: {level.upper()}\n"
            "Por favor espera. Esto puede tardar varios minutos.",
            parse_mode='Markdown'
        )
        
        # Comprimir video
        compressed_path, error = await asyncio.to_thread(
            compress_video, original_path, level
        )
        
        if error:
            await update.message.reply_text(error)
            # Limpiar archivo original
            if os.path.exists(original_path):
                os.remove(original_path)
            context.user_data.clear()
            return
        
        # Enviar video comprimido
        original_size = os.path.getsize(original_path)
        compressed_size = os.path.getsize(compressed_path)
        reduction = (1 - compressed_size/original_size) * 100
        
        await update.message.reply_text(
            f"✅ *Compresión completada*\n"
            f"📊 Reducción: {reduction:.1f}%\n"
            f"📁 Original: {original_size/1024/1024:.1f} MB\n"
            f"📁 Comprimido: {compressed_size/1024/1024:.1f} MB",
            parse_mode='Markdown'
        )
        
        # Enviar el archivo
        with open(compressed_path, 'rb') as video_file:
            await update.message.reply_video(
                video=video_file,
                caption=f"Video comprimido - Nivel: {level}",
                supports_streaming=True
            )
        
        # Limpiar archivos temporales
        try:
            os.remove(original_path)
            os.remove(compressed_path)
        except:
            pass
        
        # Limpiar estado del usuario
        context.user_data.clear()
        
        # Remover teclado personalizado
        await update.message.reply_text(
            "✅ *Proceso completado*\n"
            "Puedes enviar otro enlace cuando quieras.",
            parse_mode='Markdown',
            reply_markup={'remove_keyboard': True}
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejador de errores global"""
    logger.error(f"Error: {context.error}", exc_info=context.error)
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ *Ocurrió un error inesperado*\n"
            "Por favor, intenta de nuevo o contacta al desarrollador.",
            parse_mode='Markdown'
        )

def main():
    """Función principal para iniciar el bot"""
    # Crear aplicación
    application = Application.builder().token(TOKEN).build()
    
    # Añadir manejadores
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("compression", compression_info))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Añadir manejador de errores
    application.add_error_handler(error_handler)
    
    # Información de inicio
    logger.info("🤖 Bot iniciado")
    print("=" * 50)
    print("Telegram Video Compressor Bot")
    print("Bot iniciado correctamente")
    print("=" * 50)
    
    # Iniciar bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()