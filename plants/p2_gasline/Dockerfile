# P2 gas line OPC UA server (SPEC.md). Built from the repo root:
#   docker build -f plants/p2_gasline/Dockerfile -t zerostate/p2-gasline:p2-1 .
# Runs as zs-p2 at 192.168.95.50 on b-ics-net (compose service p2, profile p2); P2_PASSWORD_ZEROSTATE /
# P2_PASSWORD_OPERATOR come from the environment.
FROM python:3.13-slim
# procps: pkill ends truth loops left by a killed docker exec (truth.py); iproute2: the route back to the DMZ
RUN apt-get update && apt-get install -y --no-install-recommends procps iproute2 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    asyncua==1.1.6 aiofiles==25.1.0 aiosqlite==0.22.1 cryptography==50.0.2 cffi==2.1.1 pycparser==3.12 \
    pyOpenSSL==26.4.0 python-dateutil==4.0.0 pytz==2026.6 sortedcontainers==2.4.0 typing_extensions==4.16.0
WORKDIR /app
COPY plants/p2_gasline/model.py plants/p2_gasline/server.py ./
ENV ZS_TIME_SCALE=30 P2_WRITE_LOG=/var/log/p2_writes.jsonl P2_CONTROL=/run/p2/control.sock PYTHONUNBUFFERED=1
EXPOSE 4840
CMD ["python", "server.py"]
