FROM python:3.11-slim

# System deps: GStreamer, ffmpeg, libusb (for flirpy on Linux)
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential pkg-config \
      ffmpeg \
      libgl1 libglib2.0-0 \
      gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
      gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
      python3-gi gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
      libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY camera_dash ./camera_dash
RUN pip install --no-cache-dir -e '.[inference,thermal]'

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["camera_dash", "run", "--config", "/app/configs/deploy.mac.yml"]
