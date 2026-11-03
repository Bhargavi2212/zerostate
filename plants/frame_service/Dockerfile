# zs-frames: headless Chromium (software GL) on the simulator's 3D page; serves GET /frame only.
# Build context: the zerostate repo (compose: context ./zerostate).
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
RUN pip install --no-cache-dir playwright==1.55.0 Pillow==11.3.0 PyYAML==6.0.3
WORKDIR /app
COPY plants/frame_service/server.py plants/frame_service/views.yaml ./
# /truth: eval-only sidecars; the named volume zs-frames-truth takes this owner on first mount.
RUN mkdir /truth && chown pwuser /truth
USER pwuser
CMD ["python", "-u", "server.py"]
