ARG BUILD_FROM
FROM $BUILD_FROM

ENV PYTHONUNBUFFERED=1 \
    CONFIG=/data/config.yaml \
    CHROMIUM_PATH=/usr/bin/chromium \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# Chromium aus den Debian-Paketquellen: existiert fuer ARM64, deutlich
# kleiner und stabiler auf dem Pi als der Playwright-Download.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        chromium \
        fonts-liberation \
        ca-certificates \
        openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY run.sh /
COPY agent.py router.py portal.py /app/

RUN chmod a+x /run.sh

WORKDIR /app

CMD [ "/run.sh" ]
