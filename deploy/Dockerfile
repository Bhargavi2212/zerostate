# ZeroState product image. No capabilities at runtime; networking is owned by zerostate-net.
FROM python:3.13-slim
# iproute2/iptables only so the "can't change routes or rules" test fails on permission, not "not found".
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 iptables \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home zs
WORKDIR /app
RUN pip install --no-cache-dir \
    pydantic==2.14.2 pydantic_core==2.50.2 annotated-types==0.8.0 typing_extensions==4.16.0 \
    typing-inspection==0.4.4 PyYAML==6.0.3 pymodbus==3.9.2 pypdfium2==4.30.0 Pillow==11.3.0 \
    pytest==9.2.0 iniconfig==2.3.1 packaging==26.3 pluggy==1.7.0 Pygments==2.21.0
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
COPY scripts ./scripts
COPY tests/net ./tests/net
# Only plant data the product needs; never truth or fault code.
COPY plants/p1_grfics/modbus_map.yaml plants/p1_grfics/envelope.yaml plants/p1_grfics/thresholds.yaml ./config/p1_grfics/
ENV ZS_MAP=/app/config/p1_grfics/modbus_map.yaml ZS_THRESHOLDS=/app/config/p1_grfics/thresholds.yaml ZS_DATA=/data
# audit.sqlite (core only), inbox.sqlite (human/operator actions), runs/<session>/signals.jsonl
RUN mkdir -p /data && chown zs:zs /data
USER zs
CMD ["sleep", "infinity"]
