#!/usr/bin/python


from HTMLParser import HTMLParser
from itertools import izip
from pprint import pprint
import argparse
import collections
import re
import requests
import time
import urlparse

import os
from sys import exit
from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, REGISTRY

DEBUG = int(os.environ.get('DEBUG', '0'))


# Use '__none__' to signify jobs without multiple configurations.
NULL_CONFIGURATION_NAME = '__none__'


def map_url_to_job_config(url, config_mapping):
    """Return job name and config of the longest matching URL in the config mapping."""
    job_name, job_config = (None, None)
    match_length = 0
    for candidate_url, match in config_mapping.iteritems():
        if url.startswith(candidate_url) and len(candidate_url) > match_length:
            job_name, job_config = match
            match_length = len(candidate_url)
    return job_name, job_config


def convert_timestring_to_secs(timestring):
    """Convert a Jenkins-style duration string into floating point seconds."""
    tokens = timestring.split(' ')

    if (len(tokens) % 2) != 0:
        # We don't have pairs, so something went wrong in the parsing.
        return None
    pairs = izip(tokens[0::2], tokens[1::2])

    # These are defined in core/src/main/resources/hudson/Messages.properties and
    # core/src/main/java/hudson/Util.java.
    seconds_mapping = {
        'ms': 0.001,
        'sec': 1.0,
        'min': 60.0,
        'hr': 3600.0,
        'day': 24 * 3600.0,
        'days': 24 * 3600.0,
        'mo': 30 * 24 * 3600.0,
        'yr': 365 * 24 * 3600.0,
    }

    seconds = 0.0
    for amount, unit in pairs:
        if unit not in seconds_mapping:
            return None

        try:
            int_amount = int(amount)
        except ValueError:
            return None

        seconds += int_amount * seconds_mapping[unit]

    return seconds


class JenkinsElapsedHTMLParser(HTMLParser):
    """Parse a Jenkins build page and extract the current build duration."""
    current_tag = None
    elapsed_time = None

    def handle_starttag(self, tag, attrs):
        """Record when a tag is opened."""
        self.current_tag = tag

    def handle_data(self, data):
        """Process data if it's inside a <div>."""
        if self.elapsed_time is not None or self.current_tag != 'div':
            return

        elapsed_string = 'Build has been executing for '
        if elapsed_string in data:
            timestring = data[len(elapsed_string):].split('\n')[0]
            self.elapsed_time = convert_timestring_to_secs(timestring)

    def error(self, message):
        """Satisfes pylint as error is NotImplemented in HTMLParser."""
        raise message


class JenkinsCollector(object):
    # The build statuses we want to export about.
    statuses = ["lastBuild", "lastCompletedBuild", "lastFailedBuild",
                "lastStableBuild", "lastSuccessfulBuild", "lastUnstableBuild",
                "lastUnsuccessfulBuild"]

    def __init__(self, target, user, password, timeout):
        self._target = target.rstrip("/")
        self._auth = None
        if user and password:
            self._auth = (user, password)
        self.timeout = timeout

    def collect(self):
        self._setup_empty_prometheus_metrics()

        # Request data from Jenkins
        jobs, config_mapping = self._request_data()

        for job in jobs:
            name = job['name']
            if DEBUG:
                print "Found Job: %s" % name
                pprint(job)
            self._get_metrics(name, job)

        self._request_nodes(config_mapping)
        self._request_queue(jobs, config_mapping)

        for status in self.statuses:
            for metric in self._prometheus_metrics[status].values():
                yield metric

        for metric in self._prom_metrics.itervalues():
            yield metric

    def _jenkins_call(self, url_fragment, params=None):
        """Make a generic Jenkins web call."""
        url = '%s%s' % (self._target, url_fragment)

        initial_time = time.time()
        response = requests.get(url, params=params, auth=self._auth, timeout=self.timeout)
        latency = time.time() - initial_time
        self._prom_metrics['jenkins_latency'].add_metric([url_fragment], latency)
        self._prom_metrics['jenkins_response'].add_metric(
            [url_fragment], response.status_code)
        if response.status_code != requests.codes.ok:
            self._prom_metrics['jenkins_fetch_ok'].add_metric([url_fragment], 0)
            print url, response.status_code
            return None, initial_time
        self._prom_metrics['jenkins_fetch_ok'].add_metric([url_fragment], 1)

        # We return initial_time here to provide a reference for calculations based on any
        # timestamps found in the response.
        return response, initial_time

    def _jenkins_api_call(self, url_fragment, tree):
        """Make a Jenkins API call and return the parsed result."""
        params = {
            'tree': tree,
        }

        response, initial_time = self._jenkins_call(url_fragment, params)
        if response is None:
            return None, initial_time

        return response.json(), initial_time

    def _request_data(self):
        # Request exactly the information we need from Jenkins
        jobs = "[number,timestamp,duration,actions[queuingDurationMillis,totalDurationMillis," \
               "skipCount,failCount,totalCount,passCount]]"
        tree = 'jobs[name,url,activeConfigurations[name,url],{0}]'.format(
            ','.join([s + jobs for s in self.statuses]))

        result, _ = self._jenkins_api_call('/api/json', tree)
        if result is None:
            return [], {}
        if DEBUG:
            pprint(result)

        jobs = result['jobs']

        config_mapping = {}
        for job in jobs:
            for config in job.get('activeConfigurations', []):
                config_mapping[config['url']] = (job['name'], config['name'])
            config_mapping[job['url']] = (job['name'], NULL_CONFIGURATION_NAME)

        return jobs, config_mapping

    def _request_queue(self, jobs, config_mapping):
        tree = 'items[inQueueSince,task[url]]'
        result, initial_time = self._jenkins_api_call('/queue/api/json', tree)
        if result is None:
            return []

        max_queue_time = collections.defaultdict(lambda: collections.defaultdict(
            lambda: 0.0))
        task_count = collections.defaultdict(lambda: collections.defaultdict(lambda: 0))

        for task in result['items']:
            task_url = task.get('task', {}).get('url', '')
            job_name, job_config = map_url_to_job_config(task_url, config_mapping)

            if job_name is None or job_config is None:
                # We found a job or configuration that wasn't in the mapping. This can
                # happen if the job was added after we got the mapping in _request_data().
                # The next scan should have the job in the mapping.
                self._prom_metrics['dropped_job_urls'].add_metric([task_url], 1)
                continue

            old_count = task_count[job_name][job_config]
            task_count[job_name][job_config] = old_count + 1

            queuing_time = initial_time - (task['inQueueSince'] / 1000.0)
            old_max = max_queue_time[job_name][job_config]
            max_queue_time[job_name][job_config] = max(old_max, queuing_time)

        # Note: this is itervalues(), not iteritems().
        for job_name, job_config in config_mapping.itervalues():
            self._prom_metrics['queue'].add_metric(
                [job_name, job_config], max_queue_time[job_name][job_config])
            self._prom_metrics['queue_count'].add_metric(
                [job_name, job_config], task_count[job_name][job_config])

    def _request_nodes(self, config_mapping):
        tree = ('computer[displayName,offline,temporarilyOffline,idle,monitorData[*],'
                'executors[currentExecutable[url,number]]]')
        result, _ = self._jenkins_api_call('/computer/api/json', tree)
        if result is None:
            return []

        running_builds = []
        for node in result.get('computer', []):
            self._prom_metrics['online'].add_metric(
                [node['displayName']], not node.get('offline', True))
            self._prom_metrics['temporarily_offline'].add_metric(
                [node['displayName']], node.get('temporarilyOffline', False))
            self._prom_metrics['busy'].add_metric(
                [node['displayName']], not node.get('idle', False))
            monitor_data = node.get('monitorData', {})
            clockmonitor = (monitor_data or {}).get(
                'hudson.node_monitors.ClockMonitor', {})
            clock_diff = (clockmonitor or {}).get('diff')
            if clock_diff is not None:
                self._prom_metrics['skew'].add_metric(
                    [node['displayName']], clock_diff / 1000.0)

            for executor in node['executors']:
                if executor['currentExecutable'] is not None:
                    running_builds.append(executor['currentExecutable'])

        self._add_running_build_data_to_prometheus(running_builds, config_mapping)

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

        self._prom_metrics = {}
        self._prom_metrics['online'] = GaugeMetricFamily(
            'jenkins_node_online',
            'If the node is online.',
            labels=['node'])
        self._prom_metrics['temporarily_offline'] = GaugeMetricFamily(
            'jenkins_node_temporarily_offline',
            'If the node is offline only temporarily.',
            labels=['node']
        )
        self._prom_metrics['busy'] = GaugeMetricFamily(
            'jenkins_node_busy',
            'If the node is busy.',
            labels=['node']
        )
        self._prom_metrics['skew'] = GaugeMetricFamily(
            'jenkins_node_clock_skew_seconds',
            'Estimated clock skew from the Jenkins master in seconds.',
            labels=['node']
        )
        self._prom_metrics['queue'] = GaugeMetricFamily(
            'jenkins_job_queue_time_seconds',
            'Time the oldest pending task has spent in the queue.',
            labels=['jenkins_job', 'jenkins_job_config']
        )
        self._prom_metrics['queue_count'] = GaugeMetricFamily(
            'jenkins_job_queue_size',
            'Number of tasks currently in the queue.',
            labels=['jenkins_job', 'jenkins_job_config']
        )
        self._prom_metrics['jenkins_latency'] = GaugeMetricFamily(
            'jenkins_api_latency_seconds',
            'Latency when making API calls to the Jenkins master.',
            labels=['url']
        )
        self._prom_metrics['jenkins_response'] = GaugeMetricFamily(
            'jenkins_api_response_code',
            'HTTP response code of the Jenkins API.',
            labels=['url']
        )
        self._prom_metrics['jenkins_fetch_ok'] = GaugeMetricFamily(
            'jenkins_api_fetch_ok',
            'If the HTTP response of Jenkins was successful',
            labels=['url']
        )
        self._prom_metrics['dropped_job_urls'] = GaugeMetricFamily(
            'jenkins_dropped_job_urls',
            "Job URls that weren't found in the configuration mapping.",
            labels=['url'],
        )
        self._prom_metrics['executing_builds'] = GaugeMetricFamily(
            'jenkins_executing_builds',
            'Number of currently executing builds.',
            labels=['jenkins_job', 'jenkins_job_config'],
        )
        self._prom_metrics['max_currently_running_duration'] = GaugeMetricFamily(
            'jenkins_max_currently_running_duration_seconds',
            'How long the longest-running still-executing build has taken.',
            labels=['jenkins_job', 'jenkins_job_config'],
        )
        self._prom_metrics['max_currently_running_build_number'] = GaugeMetricFamily(
            'jenkins_max_currently_running_build_number',
            'Build number of the longest-running still-executing build.',
            labels=['jenkins_job', 'jenkins_job_config'],
        )

    def _get_metrics(self, name, job):
        for status in self.statuses:
            if status in job.keys():
                status_data = job[status] or {}
                self._add_data_to_prometheus_structure(status, status_data, job, name)

    def _add_running_build_data_to_prometheus(self, builds, config_mapping):
        """Calculate metrics on running builds and report those to Prometheus.

        Because we calculate running duration off a timestamp, we need request time (the
        time the API call was made) to subtract from.
        """
        executing_builds_breakdown = collections.defaultdict(
            lambda: collections.defaultdict(list))
        for build in builds:
            build_url = build.get('url', '')
            job_name, job_config = map_url_to_job_config(build_url, config_mapping)

            if job_name is None or job_config is None:
                # We found a job or configuration that wasn't in the mapping. This can
                # happen if the job was added after we got the mapping in _request_data().
                # The next scan should have the job in the mapping.
                self._prom_metrics['dropped_job_urls'].add_metric([build_url], 1)
                continue

            executing_builds_breakdown[job_name][job_config].append(build)

        # Report over all job configs here, so things return to zero when they're done.
        for job_name, job_config in config_mapping.itervalues():
            builds = executing_builds_breakdown[job_name][job_config]

            self._prom_metrics['executing_builds'].add_metric(
                [job_name, job_config], len(builds))

            def get_timestamp_from_build_url(build_url):
                """Parse the build's status page for current duration."""
                # Remove the host, scheme and port off the build_url.
                fragments = urlparse.urlsplit(build_url)
                build_url_part = urlparse.urlunsplit(
                    (0, 0, fragments[2], fragments[3], fragments[4]))
                data, _ = self._jenkins_call(build_url_part)
                if data is None:
                    return None
                parser = JenkinsElapsedHTMLParser()
                parser.feed(data.text)
                return parser.elapsed_time

            build_numbers_and_durations = [
                (b['number'], get_timestamp_from_build_url(b['url']))
                for b in builds
            ]
            # Remove any durations that came out None.
            build_numbers_and_durations = [b for b in build_numbers_and_durations if b[1]]

            if build_numbers_and_durations:
                max_build_num, max_build_dur = max(
                    build_numbers_and_durations, key=lambda x: x[1])
            else:
                max_build_num = -1
                max_build_dur = 0

            self._prom_metrics['max_currently_running_duration'].add_metric(
                [job_name, job_config], max_build_dur)
            self._prom_metrics['max_currently_running_build_number'].add_metric(
                [job_name, job_config], max_build_num)

    def _add_data_to_prometheus_structure(self, status, status_data, job, name):
        # If there's a null result, we want to pass.
        if status_data.get('duration', 0):
            self._prometheus_metrics[status]['duration'].add_metric([name], status_data.get('duration') / 1000.0)
        if status_data.get('timestamp', 0):
            self._prometheus_metrics[status]['timestamp'].add_metric([name], status_data.get('timestamp') / 1000.0)
        if status_data.get('number', 0):
            self._prometheus_metrics[status]['number'].add_metric([name], status_data.get('number'))
        actions_metrics = status_data.get('actions', [{}])
        for metric in actions_metrics:
            if metric.get('queuingDurationMillis', False):
                self._prometheus_metrics[status]['queuingDurationMillis'].add_metric([name], metric.get('queuingDurationMillis') / 1000.0)
            if metric.get('totalDurationMillis', False):
                self._prometheus_metrics[status]['totalDurationMillis'].add_metric([name], metric.get('totalDurationMillis') / 1000.0)
            if metric.get('skipCount', False):
                self._prometheus_metrics[status]['skipCount'].add_metric([name], metric.get('skipCount'))
            if metric.get('failCount', False):
                self._prometheus_metrics[status]['failCount'].add_metric([name], metric.get('failCount'))
            if metric.get('totalCount', False):
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
        '--timeout-secs',
        metavar='timeout',
        type=int,
        help='Time out Jenkins API requests after this many seconds',
        default=5,
    )
    return parser.parse_args()


def main():
    try:
        args = parse_args()
        port = int(args.port)
        REGISTRY.register(JenkinsCollector(
            args.jenkins,
            args.user,
            args.password,
            args.timeout_secs,
        ))
        start_http_server(port)
        print "Polling %s. Serving at port: %s" % (args.jenkins, port)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(" Interrupted")
        exit(0)


if __name__ == "__main__":
    main()
