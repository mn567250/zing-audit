# zing web UI in a container.
#
#   docker build -t zing .
#   docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
#
# Always publish to the host's loopback (127.0.0.1:…): the UI has no login and
# is meant for this machine only. Inside the container it has to listen on all
# of the container's interfaces for the published port to reach it; that is
# what ZING_CONTAINER=1 allows (zing refuses a non-loopback bind otherwise).
# See docs/DOCKER.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ZING_CONTAINER=1 \
    ZING_HOST=0.0.0.0 \
    ZING_PORT=8000 \
    ZING_DATA_DIR=/data

WORKDIR /src
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY zing ./zing
RUN pip install '.[web]' && rm -rf /src

RUN useradd --create-home --uid 10001 zing \
    && mkdir -p /data && chown zing:zing /data && chmod 700 /data
USER zing
WORKDIR /home/zing
VOLUME ["/data"]
EXPOSE 8000

CMD ["zing", "serve", "--no-open"]
