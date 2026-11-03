# zs-proxy: the only route from ZeroState to the Meta API. CONNECT to api.meta.ai:443 only; TLS stays
# end to end, so the proxy never sees the API key or the content.
FROM alpine:3.22
RUN apk add --no-cache tinyproxy
COPY deploy/proxy/tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY deploy/proxy/filter /etc/tinyproxy/filter
USER tinyproxy
EXPOSE 8888
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
