# Jenkins Exporter

[![Build Status](https://travis-ci.org/AbletonDevTools/jenkins_exporter.svg?branch=master)](https://travis-ci.org/AbletonDevTools/jenkins_exporter)

Jenkins exporter for prometheus.io, written in python.

This exporter is forked from Lovoo's [jenkins_exporter](
https://github.com/lovoo/jenkins_exporter), which is based on Robust
Perception's python exporter example:
For more information see
(http://www.robustperception.io/writing-a-jenkins-exporter-in-python)

## Usage

    jenkins_exporter.py [-h] [-j jenkins] [--user user]
                        [--password password] [-p port]

    optional arguments:
      -h, --help            show this help message and exit
      -j jenkins, --jenkins jenkins
                            server url from the jenkins api
      --user user           jenkins api user
      --password password   jenkins api password
      -p port, --port port  Listen to this port

#### Example

    docker run -d -p 9118:9118 AbletonDevTools/jenkins_exporter:latest -j http://jenkins:8080 -p 9118


## Installation

    git clone git@github.com:AbletonDevTools/jenkins_exporter.git
    cd jenkins_exporter
    pip install -r requirements.txt

## Contributing

1. Fork it!
2. Create your feature branch: `git checkout -b my-new-feature`
3. Commit your changes: `git commit -am 'Add some feature'`
4. Push to the branch: `git push origin my-new-feature`
5. Submit a pull request

## Maintainers

* [@ala-ableton](https://github.com/ala-ableton)
* [@mst-ableton](https://github.com/mst-ableton)
* [@nre-ableton](https://github.com/nre-ableton)
* [@rco-ableton](https://github.com/rco-ableton)
