FROM quay.io/keycloak/keycloak:26.8.1 AS keycloak
FROM mcr.microsoft.com/playwright/python:v1.64.1-noble
USER root
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y openjdk-21-jre-headless curl dnsutils procps iproute2 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir playwright==1.64.1 httpx==0.28.1
COPY --from=keycloak /opt/keycloak /opt/keycloak
ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
ENV JAVA_OPTS_KC_HEAP="-Xms128m -Xmx512m -XX:ActiveProcessorCount=2"
RUN /opt/keycloak/bin/kc.sh build --db=dev-file --cache=local --health-enabled=true
RUN useradd --uid 1100 --create-home --shell /bin/bash twin
WORKDIR /opt/callback
COPY services/common/state.py /opt/callback/services/common/state.py
COPY services/twin/entrypoint.py services/twin/server.py services/twin/tools.py /opt/callback/
ENV PATH="/opt/keycloak/bin:${PATH}" HOME=/home/twin
USER 1100:1100
ENTRYPOINT ["python3", "-I", "/opt/callback/entrypoint.py"]
