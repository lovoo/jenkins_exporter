FROM alpine:3.10 AS builder

RUN apk add --update \
    binutils \
    python3 \
    python3-dev \
    git \
    gcc \
    musl-dev \
    libc-dev \
    libffi-dev \
    zlib-dev

# Build bootloader for alpine
RUN git clone https://github.com/pyinstaller/pyinstaller.git /tmp/pyinstaller \
    && cd /tmp/pyinstaller/bootloader \
    && CFLAGS="-Wno-stringop-overflow" python3 ./waf configure --no-lsb all \
    && pip3 install .. \
    && rm -Rf /tmp/pyinstaller

COPY . /tmp

WORKDIR /tmp

RUN pip3 install -r requirements.txt && \
    pyinstaller \
    --noconfirm \
    --onefile \
    --log-level DEBUG \
    --clean \
    jenkins_exporter.py

FROM alpine

ENV JENKINS_SERVER=http://localhost
ENV VIRTUAL_PORT=9118
ENV DEBUG=0

COPY --from=builder /tmp/dist/jenkins_exporter /bin/jenkins_exporter

RUN chown root:root /bin/jenkins_exporter && \
    chmod a+x /bin/jenkins_exporter

EXPOSE 9118
USER nobody
ENTRYPOINT  [ "/bin/jenkins_exporter" ]
