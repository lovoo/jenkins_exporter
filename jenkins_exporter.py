#!/usr/bin/python

import re
import time
import requests
import argparse
from pprint import pprint
import json
import os
from sys import exit
from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, REGISTRY

DEBUG = int(os.environ.get('DEBUG', '0'))


class JenkinsCollector(object):
    # The build statuses we want to export about.
    statuses = ["healthReport", "lastBuild", "lastCompletedBuild", "lastFailedBuild",
                "lastStableBuild", "lastSuccessfulBuild", "lastUnstableBuild",
                "lastUnsuccessfulBuild", "color"]

    def __init__(self, target, user, password, verify_tls, job_list=[]):
        self._target = target.rstrip("/")
        self._user = user
        self._password = password
        self._verify_tls = verify_tls
        self._job_list=job_list

    def collect(self):
        # Request data from Jenkins
        jobs = self._request_data()

        self._setup_empty_prometheus_metrics()

        for job in jobs:
            name = job['name']
            if DEBUG:
                print "Found Job: %s" % name
                pprint(job)
            self._get_metrics(name, job)

        for status in self.statuses:
            for metric in self._prometheus_metrics[status].values():
                yield metric

    def job_in_list(self, job_to_search):
            if self._job_list == []:
                return True
            for job in self._job_list['jobs']:
                if job['name'] == job_to_search:
                    return True
            return False

    
    def _request_data(self):
        # Request exactly the information we need from Jenkins
        url = '{0}/api/json'.format(self._target)
        jobs = "[color,score,number,timestamp,duration,actions[queuingDurationMillis,totalDurationMillis," \
               "skipCount,failCount,totalCount,passCount]]"
        tree = 'jobs[name,url,color,{0}]'.format(','.join([s + jobs for s in self.statuses]))
        params = {
            'tree': tree,
        }


        def parsejobs(myurl):
            # params = tree: jobs[name,lastBuild[number,timestamp,duration,actions[queuingDurationMillis...
            response = requests.get(myurl, params=params, verify=self._verify_tls, auth=(self._user, self._password))
            if response.status_code != requests.codes.ok:
                return[]
            result = response.json()
            if DEBUG:
                pprint(result)
                pprint(response.headers['X-Jenkins'])

            jobs = []
            for job in result['jobs']:
                if re.match('^2',response.headers['X-Jenkins']):
                    if job['_class'] == 'com.cloudbees.hudson.plugins.folder.Folder' or \
                    job['_class'] == 'org.jenkinsci.plugins.workflow.multibranch.WorkflowMultiBranchProject':
                        jobs += parsejobs(job['url'] + '/api/json')
                    else:
                        if self.job_in_list(job['name']):
                            jobs.append(job)
            return jobs

        return parsejobs(url)

    def _setup_empty_prometheus_metrics(self):
        # The metrics we want to export.
        self._prometheus_metrics = {}
        for status in self.statuses:
            snake_case = re.sub('([A-Z])', '_\\1', status).lower()
            labels = ["jobname", "agent"]
            self._prometheus_metrics[status] = {
                'number':
                    GaugeMetricFamily('jenkins_job_{0}'.format(snake_case),
                                      'Jenkins build number for {0}'.format(status), labels=labels),
                'duration':
                    GaugeMetricFamily('jenkins_job_{0}_duration_seconds'.format(snake_case),
                                      'Jenkins build duration in seconds for {0}'.format(status), labels=labels),
                'timestamp':
                    GaugeMetricFamily('jenkins_job_{0}_timestamp_seconds'.format(snake_case),
                                      'Jenkins build timestamp in unixtime for {0}'.format(status), labels=labels),
                'queuingDurationMillis':
                    GaugeMetricFamily('jenkins_job_{0}_queuing_duration_seconds'.format(snake_case),
                                      'Jenkins build queuing duration in seconds for {0}'.format(status),
                                      labels=labels),
                'totalDurationMillis':
                    GaugeMetricFamily('jenkins_job_{0}_total_duration_seconds'.format(snake_case),
                                      'Jenkins build total duration in seconds for {0}'.format(status), labels=labels),
                'skipCount':
                    GaugeMetricFamily('jenkins_job_{0}_skip_count'.format(snake_case),
                                      'Jenkins build skip counts for {0}'.format(status), labels=labels),
                'failCount':
                    GaugeMetricFamily('jenkins_job_{0}_fail_count'.format(snake_case),
                                      'Jenkins build fail counts for {0}'.format(status), labels=labels),
                'totalCount':
                    GaugeMetricFamily('jenkins_job_{0}_total_count'.format(snake_case),
                                      'Jenkins build total counts for {0}'.format(status), labels=labels),
                'passCount':
                    GaugeMetricFamily('jenkins_job_{0}_pass_count'.format(snake_case),
                                      'Jenkins build pass counts for {0}'.format(status), labels=["jobname"]),
                'health':
                    GaugeMetricFamily('jenkins_job_{0}_health'.format(snake_case),
                                      'Jenkins health for {0}'.format(status), labels=["jobname"]),
                'status':
                    GaugeMetricFamily('jenkins_job_{0}_status'.format(snake_case),
                                      'Jenkins status for {0}'.format(status), labels=["jobname"])
            }
        self._prometheus_metrics['lastBuild']['is_running'] = GaugeMetricFamily('jenkins_job_last_build_is_running',
                                                                                'Jenkins build is running now for lastBuild', labels=["jobname"])

    def _get_metrics(self, name, job):
        for status in self.statuses:
            if status in job.keys():
                status_data = job[status] or {}
                if isinstance(status_data, basestring):
                    status_data = {status: status_data}
                if type(status_data) is list:
                    for status_datum in status_data:
                        self._add_data_to_prometheus_structure(status, status_datum, job, name)
                else:
                    self._add_data_to_prometheus_structure(status, status_data, job, name)

    def _add_data_to_prometheus_structure(self, status, status_data, name):
        agent = status_data.get('builtOn', '')
        label_values = [name, agent]
        # If there's a null result, we want to pass.
        if status_data.get('duration', 0):
            self._prometheus_metrics[status]['duration'].add_metric(label_values, status_data.get('duration') / 1000.0)
        if status_data.get('timestamp', 0):
            self._prometheus_metrics[status]['timestamp'].add_metric(label_values, status_data.get('timestamp') / 1000.0)
        if status_data.get('number', 0):
            self._prometheus_metrics[status]['number'].add_metric([name], status_data.get('number'))
        if status_data.get('score') is not None:
            self._prometheus_metrics[status]['health'].add_metric([name], status_data.get('score'))
        if status_data.get('color') is not None:
            self._prometheus_metrics[status]['status'].add_metric([name], 1 if (status_data.get('color').startswith('blue')) else 0)
        actions_metrics = status_data.get('actions', [{}])
        for metric in actions_metrics:
            if metric.get('queuingDurationMillis', False):
                self._prometheus_metrics[status]['queuingDurationMillis'].add_metric(label_values, metric.get('queuingDurationMillis') / 1000.0)
            if metric.get('totalDurationMillis', False):
                self._prometheus_metrics[status]['totalDurationMillis'].add_metric(label_values, metric.get('totalDurationMillis') / 1000.0)
            if metric.get('skipCount', False):
                self._prometheus_metrics[status]['skipCount'].add_metric(label_values, metric.get('skipCount'))
            if metric.get('failCount', False):
                self._prometheus_metrics[status]['failCount'].add_metric(label_values, metric.get('failCount'))
            if metric.get('totalCount', False):
                self._prometheus_metrics[status]['totalCount'].add_metric(label_values, metric.get('totalCount'))
                # Calculate passCount by subtracting fails and skips from totalCount
                passcount = metric.get('totalCount') - metric.get('failCount') - metric.get('skipCount')
                self._prometheus_metrics[status]['passCount'].add_metric(label_values, passcount)


def parse_args():
    parser = argparse.ArgumentParser(
        description='jenkins exporter args jenkins address and port'
    )
    parser.add_argument(
        '-j', '--jenkins',
        metavar='jenkins',
        required=False,
        help='server url from the jenkins api',
        default=os.environ.get('JENKINS_SERVER', 'http://jenkins:8080')
    )
    parser.add_argument(
        '--user',
        metavar='user',
        required=False,
        help='jenkins api user',
        default=os.environ.get('JENKINS_USER')
    )
    parser.add_argument(
        '--password',
        metavar='password',
        required=False,
        help='jenkins api password',
        default=os.environ.get('JENKINS_PASSWORD')
    )
    parser.add_argument(
        '-p', '--port',
        metavar='port',
        required=False,
        type=int,
        help='Listen to this port',
        default=int(os.environ.get('VIRTUAL_PORT', '9118'))
    )

    parser.add_argument(
        '--disable-cert-verification',
        required=False,
        action="store_true",
        help='Disable TLS Cert Verification',
        default=False
    )

    parser.add_argument(
        '-d', '--domain',
        metavar='domain',
        required=False,
        help='Listen to this domain',
        default=''
    )

    parser.add_argument(
        '-f', '--jobsfile',
        metavar='jobsfile',
        required=False,
        help='json file with the jobs to monitor',
        default=os.environ.get('JOBS_FILE','')
    )

    return parser.parse_args()

def set_args():
    os.environ['JENKINS_SERVER']='http://mydtbld0181.hpeswlab.net:8080'
#    os.environ['JOBS_FILE']='jobs.json'

def get_filter_jobs(jobs_file):
    if jobs_file != '':
        try:
            with open(jobs_file, 'r') as jFile:
                jString=jFile.read()
                return json.loads(jString)
        except IOError as e:
            print("WARNING: cannot open jobs file \"{0}\". I/O error({1}): {2}. Ignoring filter file.".format(jobs_file,e.errno, e.strerror))
    return[]

def main():
    try:
        set_args()
        args = parse_args()
        port = int(args.port)
        domain = args.domain
        jobs_filter = get_filter_jobs(str(args.jobsfile))
        verify_tls = not args.disable_cert_verification
        REGISTRY.register(JenkinsCollector(args.jenkins, args.user, args.password, verify_tls, jobs_filter))
        start_http_server(port)
        if domain != '':
            start_http_server(port, domain)
        else:
            start_http_server(port)
        print "Polling %s. Serving at port: %s" % (args.jenkins, port)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(" Interrupted")
        exit(0)


if __name__ == "__main__":
    main()
