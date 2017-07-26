# Jenkins Exporter

[![Build Status](https://api.travis-ci.org/lovoo/jenkins_exporter.svg?branch=travis_setup)](https://travis-ci.org/lovoo/jenkins_exporter)

Jenkins exporter for prometheus.io, written in python.

This exporter is based on Robust Perception's python exporter example:
For more information see (http://www.robustperception.io/writing-a-jenkins-exporter-in-python)

## Fork
@dotanga: This is a fork from lovoo/jenkins_exporter that enables filtering certain jobs, instead of getting all jobs from the jenkins server. it is good when the jenkins server has way too many jobs.

## Usage

    jenkins_exporter.py [-h] [-j jenkins] [--user user]
                        [--password password] [-p port] [--jobsfile file]

    optional arguments:
      -h, --help            show this help message and exit
      -j jenkins, --jenkins jenkins
                            server url from the jenkins api
      --user user           jenkins api user
      --password password   jenkins api password
      -p port, --port port  Listen to this port
      --jobsfile file       Json file with the jobs to monitor

#### Example

    docker run -d -p 9118:9118 jenkins_exporter:latest -j http://jenkins:8080 -p 9118
    docker run -d -p 9118:9118 -v /usr/etc:/opt/data jenkins_exporter:latest -j http://jenkins:8080 -p 9118 --jobsfile /opt/data/jobs.json


## Installation

    git clone git@github.com:dotanga/jenkins_exporter.git
    cd jenkins_exporter
    pip install -r requirements.txt

## Contributing

1. Fork it!
2. Create your feature branch: `git checkout -b my-new-feature`
3. Commit your changes: `git commit -am 'Add some feature'`
4. Push to the branch: `git push origin my-new-feature`
5. Submit a pull request
