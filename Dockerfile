FROM python:2-slim

RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app

COPY requirements.txt /usr/src/app
COPY jenkins_exporter.py /usr/src/app
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 9118

ENTRYPOINT [ "python", "./jenkins_exporter.py" ]
CMD ["-j", "http://jenkins:8080", "-p", "9118"]