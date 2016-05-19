#!/usr/bin/python

import re
import time
import requests
import argparse

from sys import exit
from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, REGISTRY


class JenkinsCollector(object):
    # The build statuses we want to export about.
    statuses = ["lastBuild", "lastCompletedBuild", "lastFailedBuild",
                "lastStableBuild", "lastSuccessfulBuild", "lastUnstableBuild",
                "lastUnsuccessfulBuild"]

    def __init__(self, target):
        self._target = target.rstrip("/")

    def collect(self):
        # Request data from Jenkins
        jenkins_data = self._request_data()

        self._setup_empty_prometheus_metrics()

        for job in jenkins_data['jobs']:
            name = job['name']
            self._get_metrics(name, job)

        for status in self.statuses:
            for metric in self._prometheus_metrics[status].values():
                yield metric

    def _request_data(self):
        # Request exactly the information we need from Jenkins
        url = '{0}/api/json'.format(self._target)
        jobs = "[number,timestamp,duration,actions[queuingDurationMillis,totalDurationMillis," \
               "skipCount,failCount,totalCount,passCount]]"
        tree = 'jobs[name,{0}]'.format(','.join([s + jobs for s in self.statuses]))
        params = {
            'tree': tree,
        }
        response = requests.get(url, params=params)
        if response.status_code != requests.codes.ok:
            raise Exception('Response Status ({0}): {1}'.format(response.status_code, response.text))
        result = response.json()
        return result

    def _setup_empty_prometheus_metrics(self):
        # The metrics we want to export.
        self._prometheus_metrics = {}
        for status in self.statuses:
            snake_case = re.sub('([A-Z])', '_\\1', status).lower()
            self._prometheus_metrics[status] = {
                'number':
                    GaugeMetricFamily('jenkins_job_{0}'.format(snake_case),
                                      'Jenkins build number for {0}'.format(status), labels=["jobname"]),
                'duration':
                    GaugeMetricFamily('jenkins_job_{0}_duration_seconds'.format(snake_case),
                                      'Jenkins build duration in seconds for {0}'.format(status), labels=["jobname"]),
                'timestamp':
                    GaugeMetricFamily('jenkins_job_{0}_timestamp_seconds'.format(snake_case),
                                      'Jenkins build timestamp in unixtime for {0}'.format(status), labels=["jobname"]),
                'queuingDurationMillis':
                    GaugeMetricFamily('jenkins_job_{0}_queuing_duration_seconds'.format(snake_case),
                                      'Jenkins build queuing duration in seconds for {0}'.format(status),
                                      labels=["jobname"]),
                'totalDurationMillis':
                    GaugeMetricFamily('jenkins_job_{0}_total_duration_seconds'.format(snake_case),
                                      'Jenkins build total duration in seconds for {0}'.format(status), labels=["jobname"]),
                'skipCount':
                    GaugeMetricFamily('jenkins_job_{0}_skip_count'.format(snake_case),
                                      'Jenkins build skip counts for {0}'.format(status), labels=["jobname"]),
                'failCount':
                    GaugeMetricFamily('jenkins_job_{0}_fail_count'.format(snake_case),
                                      'Jenkins build fail counts for {0}'.format(status), labels=["jobname"]),
                'totalCount':
                    GaugeMetricFamily('jenkins_job_{0}_total_count'.format(snake_case),
                                      'Jenkins build total counts for {0}'.format(status), labels=["jobname"]),
                'passCount':
                    GaugeMetricFamily('jenkins_job_{0}_pass_count'.format(snake_case),
                                      'Jenkins build pass counts for {0}'.format(status), labels=["jobname"]),
            }

    def _get_metrics(self, name, job):
        for status in self.statuses:
            status_data = job[status] or {}
            self._add_data_to_prometheus_structure(status, status_data, job, name)

    def _add_data_to_prometheus_structure(self, status, status_data, job, name):
        # If there's a null result, we want to pass.
        if status_data.get('duration'):
            self._prometheus_metrics[status]['duration'].add_metric([name], status_data.get('duration') / 1000.0)
        if status_data.get('timestamp'):
            self._prometheus_metrics[status]['timestamp'].add_metric([name], status_data.get('timestamp') / 1000.0)
        if status_data.get('number'):
            self._prometheus_metrics[status]['number'].add_metric([name], status_data.get('number'))
        actions_metrics = status_data.get('actions', [{}])
        for metric in actions_metrics:
            if metric.has_key('queuingDurationMillis') and metric.get('queuingDurationMillis'):
                self._prometheus_metrics[status]['queuingDurationMillis'].add_metric([name], metric.get('queuingDurationMillis') / 1000.0)
            if metric.has_key('totalDurationMillis') and metric.get('totalDurationMillis'):
                self._prometheus_metrics[status]['totalDurationMillis'].add_metric([name], metric.get('totalDurationMillis') / 1000.0)
            if metric.has_key('skipCount') and metric.get('skipCount'):
                self._prometheus_metrics[status]['skipCount'].add_metric([name], metric.get('skipCount'))
            if metric.has_key('failCount') and metric.get('failCount'):
                self._prometheus_metrics[status]['failCount'].add_metric([name], metric.get('failCount'))
            if metric.has_key('totalCount') and metric.get('totalCount'):
                self._prometheus_metrics[status]['totalCount'].add_metric([name], metric.get('totalCount'))
                # Calculate passCount by subtracting fails and skips from totalCount
                passcount = metric.get('totalCount') - metric.get('failCount') - metric.get('skipCount')
                self._prometheus_metrics[status]['passCount'].add_metric([name], passcount)

def parse_args():
    parser = argparse.ArgumentParser(
        description='jenkins exporter args jenkins address and port'
    )
    parser.add_argument(
        '-j', '--jenkins',
        metavar='jenkins',
        required=False,
        help='server url from the jenkins api',
        default='http://jenkins:8080'
    )
    parser.add_argument(
        '-p', '--port',
        metavar='port',
        required=False,
        type=int,
        help='Listen to this port',
        default=9118
    )
    return parser.parse_args()

if __name__ == "__main__":
    try:
        args = parse_args()
        port = int(args.port)
        REGISTRY.register(JenkinsCollector(args.jenkins))
        start_http_server(port)
        print "Serving at port: ", port
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print(" Interrupted")
        exit(0)
