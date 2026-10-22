# KEEL image server. Build from backend/:
#   docker build -f image_server/Dockerfile -t keel-image-server .
#   docker run -p 7860:7860 -v /path/to/models:/models keel-image-server
# The model is NOT baked in (6.5 GB); fetch it once with scripts/fetch_image_model.sh /path/to/models.
# CPU image. For an NVIDIA GPU use a CUDA torch build and run with --gpus all.
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.4,<3.0"
COPY image_server/requirements.txt image_server/requirements.txt
RUN pip install --no-cache-dir -r image_server/requirements.txt
COPY image_server image_server
ENV KEEL_IMAGE_MODEL_DIR=/models/sdxl-base-1.0
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:7860/health')"
CMD ["uvicorn", "image_server.server:app", "--host", "0.0.0.0", "--port", "7860"]
