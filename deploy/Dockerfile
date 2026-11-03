# ZeroState product image. No capabilities at runtime; networking is owned by zerostate-net.
FROM python:3.13-slim
# iproute2/iptables only so the "can't change routes or rules" test fails on permission, not "not found".
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 iptables \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home zs
WORKDIR /app
RUN pip install --no-cache-dir \
    pydantic==2.14.2 pydantic_core==2.50.2 annotated-types==0.8.0 typing_extensions==4.16.0 \
    typing-inspection==0.4.4 PyYAML==6.0.3 pymodbus==3.9.2 networkx==3.5 pypdfium2==4.30.0 Pillow==11.3.0 \
    asyncua==1.1.6 aiofiles==25.1.0 aiosqlite==0.22.1 cryptography==50.0.2 cffi==2.1.1 pycparser==3.12 \
    pyOpenSSL==26.4.0 python-dateutil==4.0.0 pytz==2026.6 sortedcontainers==2.4.0 \
    fastapi==0.162.0 starlette==1.10.0 annotated-doc==0.0.5 opentelemetry-api==1.45.2 anyio==4.16.0 idna==3.20 \
    uvicorn==0.54.0 click==8.5.0 h11==0.16.0 python-multipart==0.0.33 \
    pytest==9.2.0 iniconfig==2.3.1 packaging==26.3 pluggy==1.7.0 Pygments==2.21.0
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
COPY scripts ./scripts
COPY tests/net ./tests/net
# Only plant data the product needs; never truth or fault code.
# Globs so an owner-made confirmed.yaml is included when it exists (YAML data only, never .py truth/fault code).
COPY plants/p1_grfics/*.yaml ./config/p1_grfics/
COPY plants/p2_gasline/*.yaml ./config/p2_gasline/
ENV ZS_CONFIG=/app/config ZS_MAP=/app/config/p1_grfics/modbus_map.yaml ZS_THRESHOLDS=/app/config/p1_grfics/thresholds.yaml ZS_DATA=/data
# /audit/audit.sqlite (ZS_AUDIT; core rw, zs-api ro), /data: inbox.sqlite (human/operator actions), runs/<session>/signals.jsonl
RUN mkdir -p /data /audit && chown zs:zs /data /audit
USER zs
CMD ["sleep", "infinity"]
