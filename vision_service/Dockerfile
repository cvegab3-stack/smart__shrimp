# Imagen del servicio de visión (FastAPI + YOLO) para Linux. Se construye desde la raíz del proyecto:
#   docker build -f vision_service/Dockerfile -t smart-shrimp-vision .
# Por defecto instala PyTorch con CUDA (las ruedas traen CUDA; el equipo solo necesita el controlador NVIDIA y
# NVIDIA Container Toolkit). Para una imagen solo CPU (más pequeña y lenta), ver docker-compose.cpu.yml.
FROM python:3.12-slim

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu132
ARG TORCH_PACKAGES="torch==2.15.0+cu132 torchvision==0.29.2+cu132"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/vision_service:/app/contracts YOLO_CONFIG_DIR=/tmp/ultralytics

# Bibliotecas del sistema que OpenCV y PyTorch cargan en tiempo de ejecución.
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# PyTorch antes que ultralytics: así ultralytics no instala la versión solo CPU.
RUN pip install ${TORCH_PACKAGES} --index-url ${TORCH_INDEX_URL}
COPY contracts/ contracts/
COPY vision_service/requirements.txt vision_service/requirements-inference.txt vision_service/
RUN pip install ./contracts -r vision_service/requirements-inference.txt

COPY vision_service/app/ vision_service/app/
# Modelo que usa la aplicación (models/detector/best.pt). DETECTOR_WEIGHTS permite usar otro montado como volumen.
COPY models/detector/best.pt models/detector/model_info.json models/detector/
RUN useradd --system --uid 10001 --create-home smartshrimp
USER smartshrimp

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=5)"]
CMD ["uvicorn", "app.main:app", "--app-dir", "/app/vision_service", "--host", "0.0.0.0", "--port", "8001"]
