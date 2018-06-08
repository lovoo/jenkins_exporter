FROM python:2-slim

RUN apt-get update \
 && apt-get install -y supervisor=3.3.1-1+deb9u1 --no-install-recommends \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app

COPY requirements.txt /usr/src/app
RUN pip install --no-cache-dir -r requirements.txt

COPY jenkins_exporter.py /usr/src/app

EXPOSE 9118
ENV JENKINS_SERVER=http://jenkins:8080 VIRTUAL_PORT=9118 DEBUG=0

# Create a log directory for supervisor
RUN mkdir -p /var/log/supervisor

# Copy the supervisor config file
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Run the app
CMD ["/usr/bin/supervisord"]
