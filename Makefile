IMAGENAME?=lovoo/jenkins_exporter
TAG?=latest
JENKINS_SERVER?=https://myjenkins

debug: image
	docker run --rm -p 9118:9118 -e DEBUG=1 -e JENKINS_SERVER=$(JENKINS_SERVER) -e VIRTUAL_PORT=9118 $(IMAGENAME):$(TAG)

image:
	docker build -t $(IMAGENAME):$(TAG) .

push: image
	docker push $(IMAGENAME):$(TAG)


.PHONY: image push debug
