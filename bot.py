import os
import logging
import json
import tempfile
import subprocess
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import yt_dlp

# Configuración
TOKEN = "8260660352:AAFPSK2-GXqGoBm2b3K988B_dadPXHduc5M"
DOWNLOAD_FOLDER = "downloads"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB en bytes

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Cache para datos de usuario
user_data_cache = {}

# User-Agents para rotación
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
]

# --- FUNCIONES AUXILIARES ---
def format_size(bytes_size):
    """Formatear tamaño en formato legible"""
    if not bytes_size:
        return "Desconocido"
    
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0 or unit == 'GB':
            break
        bytes_size /= 1024.0
    
    if unit == 'B':
        return f"{int(bytes_size)}B"
    else:
        return f"{bytes_size:.2f}{unit}"

def calculate_filesize(tbr, duration):
    """Calcular tamaño aproximado usando bitrate y duración"""
    if tbr and duration:
        # tbr está en kbps, convertir a bytes/segundo
        bytes_per_second = (tbr * 1000) / 8
        return bytes_per_second * duration
    return None

def get_ffprobe_size(file_path):
    """Obtener tamaño exacto con ffprobe"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=size', 
             '-of', 'json', file_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return int(data['format']['size'])
    except Exception as e:
        logger.warning(f"ffprobe error: {e}")
    return None

def parse_format_info(format_dict):
    """Extraer información clara de un formato"""
    format_id = format_dict.get('format_id', 'N/A')
    resolution = f"{format_dict.get('width', '?')}x{format_dict.get('height', '?')}"
    
    # Obtener tamaño
    filesize = format_dict.get('filesize') or format_dict.get('filesize_approx')
    
    # Si no hay tamaño, calcular con tbr
    if not filesize and format_dict.get('tbr') and format_dict.get('duration'):
        filesize = calculate_filesize(format_dict['tbr'], format_dict['duration'])
    
    size_str = format_size(filesize) if filesize else "Desconocido"
    
    # Códecs
    vcodec = format_dict.get('vcodec', 'none')
    acodec = format_dict.get('acodec', 'none')
    
    # Bitrate
    tbr = format_dict.get('tbr', 0)
    tbr_str = f"{tbr:.1f}kbps" if tbr else "N/A"
    
    # Nombre del formato
    format_note = format_dict.get('format_note', '')
    ext = format_dict.get('ext', 'N/A')
    
    # Tipo de formato
    if vcodec != 'none' and acodec != 'none':
        media_type = '🎬 Video+Audio'
    elif vcodec != 'none':
        media_type = '🎥 Solo Video'
    else:
        media_type = '🎵 Solo Audio'
    
    return {
        'format_id': format_id,
        'resolution': resolution,
        'size_str': size_str,
        'size_bytes': filesize,
        'vcodec': vcodec,
        'acodec': acodec,
        'tbr_str': tbr_str,
        'tbr': tbr,
        'format_note': format_note,
        'ext': ext,
        'media_type': media_type
    }

async def get_formats_list(url, max_retries=3):
    """Obtener lista de formatos con yt-dlp -F"""
    for attempt in range(max_retries):
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'user_agent': USER_AGENTS[attempt % len(USER_AGENTS)],
                'socket_timeout': 30,
                'http_headers': {
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    raise Exception("No se pudo extraer información del video")
                
                # Obtener información básica
                title = info.get('title', 'Video sin título')
                duration = info.get('duration', 0)
                duration_str = f"{duration//60}:{duration%60:02d}" if duration else "Desconocida"
                
                # Procesar formatos
                formats = info.get('formats', [])
                parsed_formats = []
                
                for fmt in formats:
                    parsed = parse_format_info(fmt)
                    parsed_formats.append(parsed)
                
                # Ordenar: primero video+audio, luego solo video, luego solo audio
                video_audio = [f for f in parsed_formats if f['vcodec'] != 'none' and f['acodec'] != 'none']
                video_only = [f for f in parsed_formats if f['vcodec'] != 'none' and f['acodec'] == 'none']
                audio_only = [f for f in parsed_formats if f['vcodec'] == 'none' and f['acodec'] != 'none']
                
                sorted_formats = video_audio + video_only + audio_only
                
                return {
                    'success': True,
                    'title': title,
                    'duration': duration,
                    'duration_str': duration_str,
                    'formats': sorted_formats,
                    'url': url,
                    'info': info
                }
                
        except yt_dlp.utils.DownloadError as e:
            if "HTTP Error 474" in str(e) or "geo" in str(e).lower():
                logger.warning(f"Intento {attempt+1}: Error geo-bloqueo, reintentando...")
                if attempt == max_retries - 1:
                    return {
                        'success': False,
                        'error': f"Error de geo-bloqueo: {str(e)[:200]}"
                    }
                await asyncio.sleep(1)
                continue
            else:
                logger.error(f"Error yt-dlp: {e}")
                return {
                    'success': False,
                    'error': f"Error de descarga: {str(e)[:200]}"
                }
        except Exception as e:
            logger.error(f"Error inesperado: {e}")
            return {
                'success': False,
                'error': f"Error inesperado: {str(e)[:200]}"
            }
    
    return {
        'success': False,
        'error': "Máximo de reintentos alcanzado"
    }

async def download_format(url, format_id, download_type="video", max_retries=2):
    """Descargar un formato específico"""
    temp_dir = tempfile.mkdtemp()
    output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')
    
    for attempt in range(max_retries):
        try:
            ydl_opts = {
                'format': format_id,
                'outtmpl': output_template,
                'quiet': True,
                'no_warnings': True,
                'user_agent': USER_AGENTS[attempt % len(USER_AGENTS)],
                'socket_timeout': 30,
                'http_headers': {
                    'Referer': 'https://www.google.com/',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                'retries': 10,
                'fragment_retries': 10,
                'skip_unavailable_fragments': True,
            }
            
            # Opciones específicas para audio
            if download_type == "audio":
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'extractaudio': True,
                    'audioformat': 'mp3',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                })
            
            # Opciones para combinar video+audio
            elif download_type == "combined":
                ydl_opts.update({
                    'format': f'{format_id}+bestaudio',
                    'merge_output_format': 'mp4',
                })
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Primero obtener información para el nombre del archivo
                info = ydl.extract_info(url, download=False)
                result = ydl.download([url])
            
            # Buscar archivo descargado
            files = os.listdir(temp_dir)
            if not files:
                raise Exception("No se encontraron archivos descargados")
            
            file_path = os.path.join(temp_dir, files[0])
            
            # Verificar tamaño real
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                # Usar ffprobe como fallback
                real_size = get_ffprobe_size(file_path)
                if real_size:
                    file_size = real_size
                else:
                    raise Exception("Archivo descargado está vacío")
            
            return {
                'success': True,
                'file_path': file_path,
                'file_size': file_size,
                'title': info.get('title', 'descarga'),
                'temp_dir': temp_dir
            }
            
        except yt_dlp.utils.DownloadError as e:
            if "HTTP Error 474" in str(e) and attempt < max_retries - 1:
                logger.warning(f"Reintentando descarga ({attempt+1}/{max_retries})...")
                await asyncio.sleep(2)
                continue
            else:
                raise
        except Exception as e:
            raise
    
    raise Exception("Máximo de reintentos alcanzado en descarga")

# --- HANDLERS DE TELEGRAM ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start"""
    await update.message.reply_text(
        "🎬 *Bot Descargador Avanzado*\n\n"
        "Envíame cualquier enlace de video y podrás:\n"
        "✅ Ver *todos* los formatos disponibles\n"
        "✅ Elegir por *ID de formato* exacto\n"
        "✅ Ver *metadatos completos* (resolución, códecs, tamaño)\n"
        "✅ Descargar *audio solo* o *video combinado*\n\n"
        "📌 *Comandos:*\n"
        "/start - Iniciar bot\n"
        "/help - Ayuda detallada\n"
        "/update - Actualizar yt-dlp\n"
        "/cancel - Cancelar operación\n\n"
        "🚀 *Envía un enlace para comenzar!*",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /help"""
    help_text = """
📖 *Guía de Uso Completa*

1. *Envíame un enlace* de cualquier plataforma:
   • YouTube, TikTok, Instagram, Twitter/X
   • Facebook, Reddit, Twitch, etc.

2. *El bot analizará* y mostrará:
   • Lista completa de formatos disponibles
   • ID, resolución, tamaño y códecs de cada uno

3. *Selecciona un formato* por su ID (ej: `137+140`)
   • Video+Audio combinados
   • Solo video o solo audio

4. *Elige tipo de descarga:*
   • 🎬 Video completo
   • 🎵 Solo audio (MP3)
   • 🔄 Combinar formatos separados

5. *Obtendrás* el archivo con todos los metadatos

⚠️ *Notas importantes:*
• Límite: 50MB por archivo (Telegram)
• Algunos sitios pueden tener restricciones
• Archivos muy grandes pueden fallar

🛠 *Solución de problemas:*
Si ves error 474 (geo-bloqueo):
• El bot reintentará automáticamente
• Cambiará el user-agent
• Probará formatos alternativos
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def update_ytdlp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actualizar yt-dlp"""
    await update.message.reply_text("🔄 *Actualizando yt-dlp...*", parse_mode='Markdown')
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            await update.message.reply_text(
                "✅ *yt-dlp actualizado exitosamente!*\n\n"
                "Versión actualizada a la más reciente.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"❌ *Error actualizando yt-dlp:*\n\n```\n{result.stderr[:500]}\n```",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        await update.message.reply_text(
            f"❌ *Error inesperado:*\n\n{str(e)}",
            parse_mode='Markdown'
        )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancelar operación actual"""
    user_id = update.effective_user.id
    if user_id in user_data_cache:
        del user_data_cache[user_id]
    
    await update.message.reply_text(
        "❌ *Operación cancelada.*\n\nEnvía otro enlace cuando quieras.",
        parse_mode='Markdown'
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar enlace de video"""
    url = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Verificar URL válida
    if not url.startswith(('http://', 'https://')):
        await update.message.reply_text(
            "❌ *URL inválida.*\n\nEnvía un enlace que comience con http:// o https://",
            parse_mode='Markdown'
        )
        return
    
    await update.message.reply_text(
        "🔍 *Analizando enlace...*\n\n"
        "Obteniendo lista completa de formatos disponibles...",
        parse_mode='Markdown'
    )
    
    # Obtener formatos
    result = await get_formats_list(url)
    
    if not result['success']:
        await update.message.reply_text(
            f"❌ *Error:*\n\n{result['error']}\n\n"
            f"Intenta con otro enlace o verifica que sea público.",
            parse_mode='Markdown'
        )
        return
    
    # Guardar datos en cache
    user_data_cache[user_id] = {
        'url': url,
        'info': result['info'],
        'formats': result['formats'],
        'title': result['title'],
        'duration_str': result['duration_str']
    }
    
    # Preparar mensaje con información general
    title = result['title'][:100]
    duration = result['duration_str']
    total_formats = len(result['formats'])
    
    # Crear teclado con opciones principales
    keyboard = []
    
    # Agrupar formatos por tipo para mostrar opciones principales
    video_audio_count = len([f for f in result['formats'] if f['vcodec'] != 'none' and f['acodec'] != 'none'])
    video_only_count = len([f for f in result['formats'] if f['vcodec'] != 'none' and f['acodec'] == 'none'])
    audio_only_count = len([f for f in result['formats'] if f['vcodec'] == 'none' and f['acodec'] != 'none'])
    
    keyboard.append([
        InlineKeyboardButton(f"🎬 Ver {total_formats} formatos", callback_data="show_all_formats")
    ])
    keyboard.append([
        InlineKeyboardButton(f"📊 Video+Audio ({video_audio_count})", callback_data="filter_va"),
        InlineKeyboardButton(f"🎥 Solo Video ({video_only_count})", callback_data="filter_v")
    ])
    keyboard.append([
        InlineKeyboardButton(f"🎵 Solo Audio ({audio_only_count})", callback_data="filter_a"),
        InlineKeyboardButton("🔄 Combinar", callback_data="combine_options")
    ])
    keyboard.append([
        InlineKeyboardButton("❌ Cancelar", callback_data="cancel")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Enviar mensaje con información
    await update.message.reply_text(
        f"✅ *Video encontrado:*\n\n"
        f"📌 *Título:* {title}\n"
        f"⏱️ *Duración:* {duration}\n"
        f"📊 *Formatos totales:* {total_formats}\n\n"
        f"*Selecciona una opción:*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar botones de callback"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if user_id not in user_data_cache:
        await query.edit_message_text(
            "⚠️ *Sesión expirada.*\n\nEnvía el enlace de nuevo.",
            parse_mode='Markdown'
        )
        return
    
    # Cancelar
    if data == "cancel":
        del user_data_cache[user_id]
        await query.edit_message_text(
            "❌ *Operación cancelada.*\n\nEnvía otro enlace cuando quieras.",
            parse_mode='Markdown'
        )
        return
    
    info = user_data_cache[user_id]
    formats = info['formats']
    
    # Mostrar todos los formatos
    if data == "show_all_formats":
        await show_formats_list(query, formats, "Todos los formatos")
    
    # Filtrar por tipo
    elif data == "filter_va":
        filtered = [f for f in formats if f['vcodec'] != 'none' and f['acodec'] != 'none']
        await show_formats_list(query, filtered, "Formatos Video+Audio")
    
    elif data == "filter_v":
        filtered = [f for f in formats if f['vcodec'] != 'none' and f['acodec'] == 'none']
        await show_formats_list(query, filtered, "Formatos Solo Video")
    
    elif data == "filter_a":
        filtered = [f for f in formats if f['vcodec'] == 'none' and f['acodec'] != 'none']
        await show_formats_list(query, filtered, "Formatos Solo Audio")
    
    # Opciones para combinar
    elif data == "combine_options":
        await show_combine_options(query, formats)
    
    # Seleccionar formato para descarga normal
    elif data.startswith("select_"):
        format_id = data.replace("select_", "")
        await select_format_for_download(query, user_id, format_id)
    
    # Seleccionar video para combinar
    elif data.startswith("combine_video_"):
        format_id = data.replace("combine_video_", "")
        user_data_cache[user_id]['video_format'] = format_id
        await show_audio_formats_for_combine(query, formats, format_id)
    
    # Seleccionar audio para combinar
    elif data.startswith("combine_audio_"):
        audio_format_id = data.replace("combine_audio_", "")
        video_format_id = user_data_cache[user_id].get('video_format')
        
        if not video_format_id:
            await query.edit_message_text("❌ Error: No se seleccionó video.")
            return
        
        # Crear formato combinado (yt-dlp usa formato+formato para combinar)
        combined_format = f"{video_format_id}+{audio_format_id}"
        await select_format_for_download(query, user_id, combined_format, "combined")
    
    # Iniciar descarga
    elif data.startswith("download_"):
        parts = data.split("_")
        if len(parts) >= 3:
            format_id = parts[1]
            download_type = parts[2] if len(parts) > 2 else "video"
            await start_download(query, user_id, format_id, download_type)

async def show_formats_list(query, formats, title):
    """Mostrar lista de formatos"""
    if not formats:
        await query.edit_message_text(
            f"❌ *No hay formatos disponibles* en la categoría: {title}",
            parse_mode='Markdown'
        )
        return
    
    # Crear mensaje con lista de formatos
    message = f"📊 *{title}:*\n\n"
    
    for i, fmt in enumerate(formats[:20], 1):  # Mostrar máximo 20
        message += (
            f"*{i}. ID:* `{fmt['format_id']}`\n"
            f"   📏 *Resolución:* {fmt['resolution']}\n"
            f"   💾 *Tamaño:* {fmt['size_str']}\n"
            f"   🎬 *Video:* {fmt['vcodec']}\n"
            f"   🎵 *Audio:* {fmt['acodec']}\n"
            f"   📈 *Bitrate:* {fmt['tbr_str']}\n"
            f"   📝 *Ext:* {fmt['ext']}\n"
        )
    
    if len(formats) > 20:
        message += f"\n*...y {len(formats) - 20} formatos más*\n"
    
    # Crear teclado con opciones de descarga
    keyboard = []
    for fmt in formats[:10]:  # Mostrar botones para primeros 10 formatos
        btn_text = f"⬇️ {fmt['format_id']} ({fmt['size_str']})"
        callback_data = f"select_{fmt['format_id']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])
    
    # Agregar opción para ver más si hay muchos formatos
    if len(formats) > 10:
        keyboard.append([InlineKeyboardButton("📋 Ver más formatos...", callback_data="show_more_formats")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="back_to_main")])
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_combine_options(query, formats):
    """Mostrar opciones para combinar video y audio"""
    # Filtrar formatos de video sin audio
    video_formats = [f for f in formats if f['vcodec'] != 'none' and f['acodec'] == 'none']
    
    if not video_formats:
        await query.edit_message_text(
            "❌ *No hay formatos de video sin audio* para combinar.\n\n"
            "Selecciona otro tipo de descarga.",
            parse_mode='Markdown'
        )
        return
    
    message = "🔄 *Combinar Video + Audio:*\n\n"
    message += "Selecciona un formato de *video* (sin audio):\n\n"
    
    for i, fmt in enumerate(video_formats[:10], 1):
        message += (
            f"*{i}. ID:* `{fmt['format_id']}`\n"
            f"   📏 *Resolución:* {fmt['resolution']}\n"
            f"   💾 *Tamaño:* {fmt['size_str']}\n"
            f"   🎬 *Codec:* {fmt['vcodec']}\n\n"
        )
    
    # Crear teclado con opciones de video
    keyboard = []
    for fmt in video_formats[:8]:
        btn_text = f"🎥 {fmt['format_id']} ({fmt['resolution']})"
        callback_data = f"combine_video_{fmt['format_id']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="back_to_main")])
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_audio_formats_for_combine(query, formats, video_format_id):
    """Mostrar formatos de audio para combinar con video seleccionado"""
    audio_formats = [f for f in formats if f['vcodec'] == 'none' and f['acodec'] != 'none']
    
    if not audio_formats:
        await query.edit_message_text(
            "❌ *No hay formatos de audio* disponibles para combinar.",
            parse_mode='Markdown'
        )
        return
    
    # Buscar información del video seleccionado
    video_fmt = next((f for f in formats if f['format_id'] == video_format_id), None)
    
    message = f"🔄 *Combinar con Audio:*\n\n"
    message += f"*Video seleccionado:*\n"
    message += f"• ID: `{video_fmt['format_id']}`\n"
    message += f"• Resolución: {video_fmt['resolution']}\n"
    message += f"• Codec: {video_fmt['vcodec']}\n\n"
    message += "*Selecciona formato de audio:*\n\n"
    
    for i, fmt in enumerate(audio_formats[:8], 1):
        message += (
            f"*{i}. ID:* `{fmt['format_id']}`\n"
            f"   🎵 *Codec:* {fmt['acodec']}\n"
            f"   💾 *Tamaño:* {fmt['size_str']}\n"
            f"   📈 *Bitrate:* {fmt['tbr_str']}\n\n"
        )
    
    # Crear teclado con opciones de audio
    keyboard = []
    for fmt in audio_formats[:8]:
        btn_text = f"🎵 {fmt['format_id']} ({fmt['tbr_str']})"
        callback_data = f"combine_audio_{fmt['format_id']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton("⬅️ Elegir otro video", callback_data="combine_options")])
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def select_format_for_download(query, user_id, format_id, download_type="video"):
    """Mostrar opciones de descarga para un formato específico"""
    if user_id not in user_data_cache:
        await query.edit_message_text("⚠️ Sesión expirada.")
        return
    
    formats = user_data_cache[user_id]['formats']
    selected_fmt = next((f for f in formats if f['format_id'] == format_id), None)
    
    if not selected_fmt:
        # Podría ser un formato combinado
        if "+" in format_id:
            parts = format_id.split("+")
            video_fmt = next((f for f in formats if f['format_id'] == parts[0]), None)
            audio_fmt = next((f for f in formats if f['format_id'] == parts[1]), None)
            
            if video_fmt and audio_fmt:
                selected_fmt = {
                    'format_id': format_id,
                    'resolution': video_fmt['resolution'],
                    'size_str': f"Aprox. {format_size((video_fmt.get('size_bytes') or 0) + (audio_fmt.get('size_bytes') or 0))}",
                    'vcodec': video_fmt['vcodec'],
                    'acodec': audio_fmt['acodec'],
                    'tbr_str': f"{video_fmt.get('tbr', 0) + audio_fmt.get('tbr', 0):.1f}kbps",
                    'ext': 'mp4',
                    'media_type': '🎬 Video+Audio Combinado'
                }
    
    if not selected_fmt:
        await query.edit_message_text("❌ Formato no encontrado.")
        return
    
    # Mostrar metadatos completos
    message = (
        f"📋 *Metadatos del Formato:*\n\n"
        f"*ID:* `{selected_fmt['format_id']}`\n"
        f"*Tipo:* {selected_fmt.get('media_type', 'Desconocido')}\n"
        f"*Resolución:* {selected_fmt['resolution']}\n"
        f"*Tamaño estimado:* {selected_fmt['size_str']}\n"
        f"*Codec Video:* {selected_fmt['vcodec']}\n"
        f"*Codec Audio:* {selected_fmt['acodec']}\n"
        f"*Bitrate total:* {selected_fmt['tbr_str']}\n"
        f"*Extensión:* {selected_fmt['ext']}\n\n"
        f"*Selecciona tipo de descarga:*"
    )
    
    # Crear teclado de opciones de descarga
    keyboard = []
    
    if selected_fmt['vcodec'] != 'none':
        keyboard.append([
            InlineKeyboardButton("🎬 Descargar Video", callback_data=f"download_{format_id}_video")
        ])
    
    if selected_fmt['acodec'] != 'none':
        keyboard.append([
            InlineKeyboardButton("🎵 Descargar Solo Audio (MP3)", callback_data=f"download_{format_id}_audio")
        ])
    
    keyboard.append([
        InlineKeyboardButton("⬅️ Volver a formatos", callback_data="show_all_formats"),
        InlineKeyboardButton("❌ Cancelar", callback_data="cancel")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def start_download(query, user_id, format_id, download_type):
    """Iniciar proceso de descarga"""
    if user_id not in user_data_cache:
        await query.edit_message_text("⚠️ Sesión expirada.")
        return
    
    url = user_data_cache[user_id]['url']
    title = user_data_cache[user_id]['title']
    
    # Actualizar mensaje
    await query.edit_message_text(
        f"⬇️ *Iniciando descarga...*\n\n"
        f"📌 *Formato:* `{format_id}`\n"
        f"🎯 *Tipo:* {'Audio' if download_type == 'audio' else 'Video'}\n"
        f"📦 *Video:* {title[:50]}\n\n"
        f"⏳ *Esto puede tardar unos minutos...*",
        parse_mode='Markdown'
    )
    
    try:
        # Descargar el formato
        result = await download_format(url, format_id, download_type)
        
        if result['success']:
            file_path = result['file_path']
            file_size = result['file_size']
            
            # Verificar límite de tamaño
            if file_size > MAX_FILE_SIZE:
                await query.edit_message_text(
                    f"❌ *Archivo demasiado grande:*\n\n"
                    f"📦 *Tamaño:* {format_size(file_size)}\n"
                    f"📊 *Límite:* {format_size(MAX_FILE_SIZE)}\n\n"
                    f"Selecciona un formato con menor calidad.",
                    parse_mode='Markdown'
                )
                # Limpiar archivos temporales
                try:
                    os.remove(file_path)
                    os.rmdir(os.path.dirname(file_path))
                except:
                    pass
                return
            
            # Enviar archivo a Telegram
            with open(file_path, 'rb') as file:
                if download_type == 'audio':
                    await query.message.reply_audio(
                        audio=file,
                        caption=(
                            f"✅ *Audio descargado*\n\n"
                            f"📌 *Título:* {title[:50]}\n"
                            f"🔧 *Formato:* `{format_id}`\n"
                            f"💾 *Tamaño:* {format_size(file_size)}\n"
                            f"🎵 *Codec:* MP3"
                        ),
                        title=title[:30],
                        parse_mode='Markdown'
                    )
                else:
                    await query.message.reply_video(
                        video=file,
                        caption=(
                            f"✅ *Video descargado*\n\n"
                            f"📌 *Título:* {title[:50]}\n"
                            f"🔧 *Formato:* `{format_id}`\n"
                            f"💾 *Tamaño:* {format_size(file_size)}\n"
                            f"🎬 *Tipo:* {'Video+Audio' if '+' in format_id else 'Video'}"
                        ),
                        supports_streaming=True,
                        parse_mode='Markdown'
                    )
            
            # Confirmar finalización
            await query.edit_message_text(
                f"✅ *¡Descarga completada!*\n\n"
                f"📤 *Archivo enviado al chat.*\n\n"
                f"¿Quieres descargar otro video? ¡Envía otro enlace!",
                parse_mode='Markdown'
            )
            
            # Limpiar archivos temporales
            try:
                os.remove(file_path)
                os.rmdir(os.path.dirname(file_path))
            except Exception as e:
                logger.warning(f"Error limpiando archivos: {e}")
            
            # Limpiar cache del usuario
            if user_id in user_data_cache:
                del user_data_cache[user_id]
        
        else:
            await query.edit_message_text(
                f"❌ *Error en la descarga:*\n\n{result.get('error', 'Error desconocido')}",
                parse_mode='Markdown'
            )
    
    except Exception as e:
        logger.error(f"Error en descarga: {e}")
        await query.edit_message_text(
            f"❌ *Error en la descarga:*\n\n```\n{str(e)[:300]}\n```\n\n"
            f"Intenta con otro formato o verifica el enlace.",
            parse_mode='Markdown'
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar errores globales"""
    logger.error(f"Update {update} caused error {context.error}")
    
    try:
        if update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ *Error interno del bot.*\n\n"
                "Por favor, intenta de nuevo en unos momentos.",
                parse_mode='Markdown'
            )
    except:
        pass

# --- FUNCIÓN PRINCIPAL ---
def main():
    """Función principal para ejecutar el bot"""
    # Crear aplicación de Telegram
    application = Application.builder().token(TOKEN).build()
    
    # Añadir handlers de comandos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("update", update_ytdlp))
    application.add_handler(CommandHandler("cancel", cancel_command))
    
    # Handler para URLs (mensajes que contienen enlaces)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    
    # Handler para botones de callback
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Handler de errores
    application.add_error_handler(error_handler)
    
    # Verificar versión de yt-dlp
    try:
        yt_dlp_version = yt_dlp.version.__version__
        logger.info(f"yt-dlp versión: {yt_dlp_version}")
    except:
        logger.warning("No se pudo obtener versión de yt-dlp")
    
    # Iniciar el bot
    logger.info("🤖 Bot iniciado - Esperando enlaces...")
    print("\n" + "="*50)
    print("🎬 BOT DESCARGA AVANZADO ACTIVO")
    print("="*50)
    print(f"📅 Hora de inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📦 Carpeta descargas: {os.path.abspath(DOWNLOAD_FOLDER)}")
    print(f"⚡ Máximo archivo: {format_size(MAX_FILE_SIZE)}")
    print("="*50)
    print("\n📥 Envía /start para comenzar...")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("Bot detenido por el usuario")
    except Exception as e:
        logger.error(f"Error fatal: {e}")

if __name__ == '__main__':
    # Verificar dependencias
    import sys
    try:
        import yt_dlp
    except ImportError:
        print("❌ Error: yt-dlp no está instalado.")
        print("📦 Instala con: pip install yt-dlp")
        sys.exit(1)
    
    main()