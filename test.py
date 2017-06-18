#!/usr/bin/python

import unittest
from jenkins_exporter import JenkinsCollector


class JenkinsCollectorTestCase(unittest.TestCase):
    # The build statuses we want to export about.
    # TODO: add more test cases

    def test_prometheus_metrics(self):
        exporter = JenkinsCollector('', '', '')
        self.assertFalse(hasattr(exporter, '_prometheus_metrics'))

        exporter._setup_empty_prometheus_metrics()
        self.assertTrue(hasattr(exporter, '_prometheus_metrics'))
        self.assertEqual(sorted(exporter._prometheus_metrics.keys()), sorted(JenkinsCollector.statuses))


if __name__ == "__main__":
    unittest.main()
