FROM python:3.12-alpine

RUN apk add --no-cache ca-certificates curl iproute2 iputils

COPY requirements.txt /tmp/client-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/client-requirements.txt
