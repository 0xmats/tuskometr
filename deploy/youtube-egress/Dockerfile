FROM debian:trixie-slim
RUN apt-get update \
    && apt-get install --no-install-recommends -y tinyproxy-bin \
    && rm -rf /var/lib/apt/lists/*
COPY domains /etc/tinyproxy/domains
COPY start.sh /usr/local/bin/start-egress
USER 10001:10001
ENTRYPOINT ["sh", "/usr/local/bin/start-egress"]
