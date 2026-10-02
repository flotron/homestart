"""Sampling continuity and host payload contracts after metric extraction."""
import unittest
from unittest.mock import Mock, patch
from homestart.metrics.host import HostMetrics


def collector():
    return HostMetrics(clamp_percent=lambda n: None if n is None else max(0, min(100, n)),
                       process_tracker=Mock(), process_identity=Mock(),
                       network_payload=Mock(return_value={'interface': 'eth0'}),
                       docker_apps=Mock(return_value=[]))


class HostMetricsTests(unittest.TestCase):
    def test_cpu_delta_state_is_persistent_and_instance_local(self):
        metrics = collector()
        with patch.object(metrics, 'read_cpu_times', side_effect=[(100, 40), (200, 60), (200, 60)]):
            self.assertIsNone(metrics.cpu_percent())
            self.assertEqual(metrics.cpu_percent(), 80)
            self.assertIsNone(metrics.cpu_percent())
        other = collector()
        with patch.object(other, 'read_cpu_times', return_value=(200, 60)):
            self.assertIsNone(other.cpu_percent())

    def test_system_payload_preserves_multiple_gpus_and_optional_network(self):
        metrics = collector()
        gpus = [{'name': 'A', 'available': True, 'percent': 12, 'frequency_mhz': 500, 'source': 'nvidia-smi'},
                {'name': 'B', 'available': True, 'percent': 80, 'frequency_mhz': 700, 'source': 'nvidia-smi'}]
        with patch.object(metrics, 'nvidia_gpus_payload', return_value=gpus), \
             patch.object(metrics, 'cpu_percent', return_value=25), \
             patch.object(metrics, 'memory_payload', return_value={'percent': 30}), \
             patch.object(metrics, 'temperature_payload', return_value={'celsius': 40}):
            payload = metrics.system_payload()
            self.assertEqual(payload['gpu']['count'], 2)
            self.assertEqual(payload['gpu']['percent'], 80)
            self.assertEqual(payload['gpus'], gpus)
            self.assertEqual(payload['network'], {})
            metrics.network_payload.assert_not_called()
            metrics.process_tracker.top.assert_called_with(metrics.process_identity)
            self.assertEqual(metrics.system_payload('live')['network']['interface'], 'eth0')
            metrics.network_payload.assert_called_once_with('live')

    def test_missing_gpu_retains_monitor_hint(self):
        metrics = collector()
        with patch.object(metrics, 'nvidia_gpus_payload', return_value=[]), \
             patch.object(metrics, 'gpu_frequency', return_value=(None, None)), \
             patch.object(metrics, 'gpu_busy_percent', return_value=None), \
             patch.object(metrics, 'gpu_monitor_hint', return_value={'title': 'Missing utility'}), \
             patch.object(metrics, 'cpu_percent', return_value=None), \
             patch.object(metrics, 'memory_payload', return_value={}), \
             patch.object(metrics, 'temperature_payload', return_value={}):
            payload = metrics.system_payload()
            self.assertFalse(payload['gpu']['available'])
            self.assertEqual(payload['gpu']['monitor_hint']['title'], 'Missing utility')
            self.assertEqual(payload['gpus'], [])
