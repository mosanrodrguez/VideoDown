FROM python:3.11-slim

# Instalar FFmpeg y dependencias del sistema
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar requirements primero para caché
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto de la aplicación
COPY . .

# Crear directorio temporal
RUN mkdir -p temp

# Variable de entorno para producción
ENV PYTHONUNBUFFERED=1

# Comando para ejecutar
CMD ["python", "bot.py"]