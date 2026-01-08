#!/usr/bin/env python3
import logging
import os
import re
import tempfile
import asyncio
from typing import Dict, List, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import yt_dlp

# Configuración del logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Diccionario para almacenar temporalmente la información de formatos por usuario
user_data = {}

class VideoDownloaderBot:
    def __init__(self, token: str):
        self.token = token
        self.app = Application.builder().token(token).build()
        
        # Configurar manejadores
        self.setup_handlers()
        
    def setup_handlers(self):
        """Configura todos los manejadores de comandos y mensajes"""
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.app.add_handler(CallbackQueryHandler(self.handle_callback_query))
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja el comando /start"""
        welcome_message = (
            "¡Bienvenid@ a VideoDown! 🎬\n\n"
            "Envía el enlace del vídeo a descargar\n\n"
            "📌 Formatos soportados:\n"
            "• YouTube\n"
            "• TikTok\n"
            "• Instagram\n"
            "• Twitter/X\n"
            "• Facebook\n"
            "• Y muchos más..."
        )
        
        await update.message.reply_text(welcome_message)
        
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja los mensajes con enlaces de video"""
        url = update.message.text.strip()
        
        # Verificar si es una URL válida
        if not self.is_valid_url(url):
            await update.message.reply_text("⚠️ Por favor, envía una URL válida.")
            return
        
        # Informar que se está procesando
        processing_msg = await update.message.reply_text("🔍 Analizando el video...")
        
        try:
            # Obtener información del video
            video_info = self.get_video_info(url)
            
            if not video_info:
                await processing_msg.edit_text("❌ No se pudo obtener información del video. Verifica el enlace.")
                return
            
            # Guardar información del usuario
            user_id = update.effective_user.id
            user_data[user_id] = {
                'url': url,
                'title': video_info['title'],
                'formats': video_info['formats'],
                'audio_formats': video_info['audio_formats']
            }
            
            # Crear teclado para seleccionar tipo de descarga
            keyboard = [
                [
                    InlineKeyboardButton("🎬 Video", callback_data='type_video'),
                    InlineKeyboardButton("💽 Audio", callback_data='type_audio')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await processing_msg.edit_text(
                f"📹 **{video_info['title']}**\n\n"
                f"📊 Duración: {video_info['duration']}\n"
                f"👤 Canal: {video_info['uploader']}\n\n"
                "¿Qué deseas descargar?",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Error al procesar el video: {e}")
            await processing_msg.edit_text("❌ Error al procesar el video. Intenta de nuevo.")
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja las selecciones de los botones"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        # Manejar selección de tipo (video/audio)
        if query.data.startswith('type_'):
            await self.handle_type_selection(query, user_id)
            
        # Manejar selección de formato específico
        elif query.data.startswith('format_'):
            await self.handle_format_selection(query, user_id)
            
        # Manejar selección de calidad de audio
        elif query.data.startswith('audio_'):
            await self.handle_audio_selection(query, user_id)
            
        # Manejar botón de volver
        elif query.data == 'back_to_menu':
            await self.handle_back_button(query, user_id)
    
    async def handle_type_selection(self, query, user_id):
        """Maneja la selección de video o audio"""
        download_type = query.data.split('_')[1]
        
        if user_id not in user_data:
            await query.edit_message_text("❌ Sesión expirada. Por favor, envía el enlace nuevamente.")
            return
        
        user_info = user_data[user_id]
        
        if download_type == 'video':
            # Mostrar formatos de video disponibles
            await self.show_video_formats(query, user_info)
        else:
            # Mostrar formatos de audio disponibles
            await self.show_audio_formats(query, user_info)
    
    async def show_video_formats(self, query, user_info):
        """Muestra los formatos de video disponibles"""
        formats = user_info['formats']
        
        if not formats:
            await query.edit_message_text("❌ No hay formatos de video disponibles.")
            return
        
        # Crear botones para cada formato
        keyboard = []
        current_row = []
        
        for i, fmt in enumerate(formats[:8]):  # Limitar a 8 formatos
            if fmt.get('filesize'):
                size_mb = fmt['filesize'] / (1024 * 1024)
                size_text = f"{size_mb:.1f}MB"
            elif fmt.get('filesize_approx'):
                size_mb = fmt['filesize_approx'] / (1024 * 1024)
                size_text = f"~{size_mb:.1f}MB"
            else:
                size_text = "Tamaño desconocido"
            
            # Extraer solo la resolución si está disponible
            resolution = fmt.get('resolution', 'Desconocido')
            if 'x' in str(resolution):
                try:
                    height = resolution.split('x')[1]
                    resolution = f"{height}p"
                except:
                    pass
            
            button_text = f"🎬 {resolution} - {size_text}"
            callback_data = f"format_{fmt['format_id']}"
            
            current_row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
            
            if len(current_row) == 2 or i == len(formats[:8]) - 1:
                keyboard.append(current_row)
                current_row = []
        
        # Agregar botón de volver
        keyboard.append([InlineKeyboardButton("↩️ Volver", callback_data='back_to_menu')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🎬 **{user_info['title']}**\n\n"
            "Selecciona la calidad del video:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def show_audio_formats(self, query, user_info):
        """Muestra los formatos de audio disponibles"""
        audio_formats = user_info['audio_formats']
        
        if not audio_formats:
            await query.edit_message_text("❌ No hay formatos de audio disponibles.")
            return
        
        # Crear botones para cada formato de audio
        keyboard = []
        
        for i, fmt in enumerate(audio_formats[:4]):  # Limitar a 4 formatos de audio
            if fmt.get('filesize'):
                size_mb = fmt['filesize'] / (1024 * 1024)
                size_text = f"{size_mb:.1f}MB"
            else:
                size_text = "Tamaño desconocido"
            
            # Extraer información del códec de audio
            abr = fmt.get('abr', 0)
            
            button_text = f"🎵 {abr}kbps - {size_text}"
            callback_data = f"audio_{fmt['format_id']}"
            
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        # Agregar botón de volver
        keyboard.append([InlineKeyboardButton("↩️ Volver", callback_data='back_to_menu')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"💽 **{user_info['title']}**\n\n"
            "Selecciona la calidad del audio:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_back_button(self, query, user_id):
        """Maneja el botón de volver al menú principal"""
        if user_id not in user_data:
            await query.edit_message_text("❌ Sesión expirada.")
            return
        
        user_info = user_data[user_id]
        
        # Crear teclado para seleccionar tipo de descarga
        keyboard = [
            [
                InlineKeyboardButton("🎬 Video", callback_data='type_video'),
                InlineKeyboardButton("💽 Audio", callback_data='type_audio')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📹 **{user_info['title']}**\n\n"
            "¿Qué deseas descargar?",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_format_selection(self, query, user_id):
        """Maneja la descarga del formato de video seleccionado"""
        format_id = query.data.split('_')[1]
        
        if user_id not in user_data:
            await query.edit_message_text("❌ Sesión expirada.")
            return
        
        user_info = user_data[user_id]
        url = user_info['url']
        
        # Encontrar el formato seleccionado
        selected_format = None
        for fmt in user_info['formats']:
            if fmt['format_id'] == format_id:
                selected_format = fmt
                break
        
        if not selected_format:
            await query.edit_message_text("❌ Formato no disponible.")
            return
        
        # Mostrar mensaje de descarga
        status_msg = await query.edit_message_text(
            f"⬇️ **Descargando video...**\n\n"
            f"📹 {user_info['title']}\n"
            f"📊 Calidad: {selected_format.get('resolution', 'Desconocida')}\n"
            f"⏳ Por favor, espera...\n\n"
            f"🔄 Esto puede tardar unos minutos...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Descargar el video
        success, file_path = self.download_video(url, format_id, user_info['title'])
        
        if success:
            try:
                # Actualizar mensaje
                await status_msg.edit_text("📤 Enviando video...")
                
                # Enviar el video
                with open(file_path, 'rb') as video_file:
                    await query.message.reply_video(
                        video=video_file,
                        caption=f"✅ **{user_info['title']}**\n\n"
                               f"📊 Calidad: {selected_format.get('resolution', 'Desconocida')}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                
                # Eliminar archivo temporal
                os.remove(file_path)
                
                # Limpiar datos del usuario
                if user_id in user_data:
                    del user_data[user_id]
                    
            except Exception as e:
                logger.error(f"Error al enviar video: {e}")
                await query.message.reply_text("❌ Error al enviar el video. El archivo puede ser muy grande.")
        else:
            await status_msg.edit_text("❌ Error al descargar el video. Intenta con otra calidad.")
    
    async def handle_audio_selection(self, query, user_id):
        """Maneja la descarga del formato de audio seleccionado"""
        format_id = query.data.split('_')[1]
        
        if user_id not in user_data:
            await query.edit_message_text("❌ Sesión expirada.")
            return
        
        user_info = user_data[user_id]
        url = user_info['url']
        
        # Mostrar mensaje de descarga
        status_msg = await query.edit_message_text(
            f"⬇️ **Extrayendo audio...**\n\n"
            f"🎵 {user_info['title']}\n"
            f"⏳ Por favor, espera...\n\n"
            f"🔄 Esto puede tardar unos minutos...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Descargar el audio
        success, file_path = self.download_audio(url, format_id, user_info['title'])
        
        if success:
            try:
                # Actualizar mensaje
                await status_msg.edit_text("📤 Enviando audio...")
                
                # Enviar el audio
                with open(file_path, 'rb') as audio_file:
                    await query.message.reply_audio(
                        audio=audio_file,
                        title=user_info['title'][:64],  # Telegram limita a 64 chars
                        caption=f"✅ **{user_info['title']}**\n\n"
                               f"🎵 Audio extraído correctamente",
                        parse_mode=ParseMode.MARKDOWN
                    )
                
                # Eliminar archivo temporal
                os.remove(file_path)
                
                # Limpiar datos del usuario
                if user_id in user_data:
                    del user_data[user_id]
                    
            except Exception as e:
                logger.error(f"Error al enviar audio: {e}")
                await query.message.reply_text("❌ Error al enviar el audio. El archivo puede ser muy grande.")
        else:
            await status_msg.edit_text("❌ Error al extraer el audio. Intenta de nuevo.")
    
    def get_video_info(self, url: str) -> Dict:
        """Obtiene información del video usando yt-dlp"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'extract_flat': False,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Extraer formatos de video (con video y audio)
                video_formats = []
                for fmt in info.get('formats', []):
                    if (fmt.get('vcodec') and fmt.get('vcodec') != 'none' and 
                        fmt.get('acodec') and fmt.get('acodec') != 'none'):
                        
                        # Calcular tamaño aproximado si no está disponible
                        if not fmt.get('filesize') and fmt.get('tbr'):
                            duration = info.get('duration', 0)
                            if duration > 0:
                                fmt['filesize_approx'] = (fmt['tbr'] * 1000 * duration) / 8
                        
                        resolution = fmt.get('resolution', 'audio only')
                        if resolution == 'audio only':
                            continue
                            
                        video_formats.append({
                            'format_id': fmt['format_id'],
                            'resolution': resolution,
                            'ext': fmt.get('ext', 'mp4'),
                            'filesize': fmt.get('filesize'),
                            'filesize_approx': fmt.get('filesize_approx'),
                            'vcodec': fmt.get('vcodec'),
                            'acodec': fmt.get('acodec'),
                            'tbr': fmt.get('tbr', 0)
                        })
                
                # Ordenar por resolución (mayor primero)
                def get_resolution_num(res):
                    if isinstance(res, str) and 'x' in res:
                        try:
                            return int(res.split('x')[1])
                        except:
                            return 0
                    return 0
                
                video_formats.sort(key=lambda x: get_resolution_num(x['resolution']), reverse=True)
                
                # Extraer formatos de audio solo
                audio_formats = []
                for fmt in info.get('formats', []):
                    if (fmt.get('acodec') and fmt.get('acodec') != 'none' and 
                        (not fmt.get('vcodec') or fmt.get('vcodec') == 'none')):
                        
                        audio_formats.append({
                            'format_id': fmt['format_id'],
                            'ext': fmt.get('ext', 'mp3'),
                            'filesize': fmt.get('filesize'),
                            'acodec': fmt.get('acodec'),
                            'abr': fmt.get('abr', 0),
                            'asr': fmt.get('asr', 0)
                        })
                
                # Ordenar audio por calidad (mejor primero)
                audio_formats.sort(key=lambda x: x.get('abr', 0), reverse=True)
                
                # Formatear duración
                duration_seconds = info.get('duration', 0)
                if duration_seconds > 3600:
                    duration = f"{duration_seconds // 3600}:{(duration_seconds % 3600) // 60:02d}:{duration_seconds % 60:02d}"
                else:
                    duration = f"{duration_seconds // 60}:{duration_seconds % 60:02d}"
                
                return {
                    'title': info.get('title', 'Sin título')[:100],  # Limitar longitud
                    'duration': duration,
                    'uploader': info.get('uploader', 'Desconocido')[:50],
                    'formats': video_formats[:8],  # Limitar a 8 formatos
                    'audio_formats': audio_formats[:4]  # Limitar a 4 formatos de audio
                }
                
        except Exception as e:
            logger.error(f"Error al obtener info: {e}")
            return None
    
    def download_video(self, url: str, format_id: str, title: str):
        """Descarga el video en el formato seleccionado"""
        # Crear directorio temporal
        temp_dir = tempfile.gettempdir()
        safe_title = re.sub(r'[^\w\s-]', '', title).strip()[:50]
        
        ydl_opts = {
            'format': format_id,
            'outtmpl': os.path.join(temp_dir, f'{safe_title}.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'socket_timeout': 30,
            'retries': 3,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                # Asegurarse de que el archivo tiene extensión .mp4
                if not filename.endswith('.mp4'):
                    new_filename = os.path.splitext(filename)[0] + '.mp4'
                    if os.path.exists(filename):
                        os.rename(filename, new_filename)
                    filename = new_filename
                
                # Verificar si el archivo existe y tiene tamaño
                if os.path.exists(filename) and os.path.getsize(filename) > 0:
                    return True, filename
                else:
                    return False, None
                
        except Exception as e:
            logger.error(f"Error al descargar video: {e}")
            return False, None
    
    def download_audio(self, url: str, format_id: str, title: str):
        """Extrae y descarga el audio del video"""
        temp_dir = tempfile.gettempdir()
        safe_title = re.sub(r'[^\w\s-]', '', title).strip()[:50]
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(temp_dir, f'{safe_title}.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'ffmpeg_location': '/data/data/com.termux/files/usr/bin/ffmpeg',
            'socket_timeout': 30,
            'retries': 3,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Obtener el nombre del archivo de audio
                filename = ydl.prepare_filename(info)
                audio_filename = os.path.splitext(filename)[0] + '.mp3'
                
                # Verificar si el archivo existe y tiene tamaño
                if os.path.exists(audio_filename) and os.path.getsize(audio_filename) > 0:
                    return True, audio_filename
                else:
                    return False, None
                
        except Exception as e:
            logger.error(f"Error al descargar audio: {e}")
            return False, None
    
    def is_valid_url(self, text: str) -> bool:
        """Verifica si el texto es una URL válida"""
        # Patrón simple para URLs
        url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
        return re.match(url_pattern, text) is not None
    
    def run(self):
        """Inicia el bot"""
        print("🤖 Bot de descarga de videos iniciado...")
        print("Presiona Ctrl+C para detenerlo")
        
        # CORRECCIÓN PRINCIPAL: Cambiar Update.ALL_UPDATES por None
        self.app.run_polling(allowed_updates=None)


if __name__ == '__main__':
    # Reemplaza 'TU_TOKEN_AQUI' con el token de tu bot
    TOKEN = "8260660352:AAFPSK2-GXqGoBm2b3K988B_dadPXHduc5M"
    
    # Verificar que ffmpeg esté instalado
    if not os.path.exists('/data/data/com.termux/files/usr/bin/ffmpeg'):
        print("⚠️ ADVERTENCIA: ffmpeg no está instalado.")
        print("Instálalo con: pkg install ffmpeg")
        print("El bot funcionará pero puede tener problemas con algunos formatos de audio.")
    
    bot = VideoDownloaderBot(TOKEN)
    bot.run()