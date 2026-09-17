"""Offline consumer-contract, transport deadline, preview, and JonsBo chain checks."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import test_mqtt_reports as base

ROOT = Path(__file__).resolve().parents[1]


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        """Reuse the original fixture without importing Paho or contacting any service."""
        fixture = base.ReportTests()
        fixture.setUp()
        self.app, self.cfg = fixture.app, fixture.cfg
        self.session = {'msg': 'Session done', 'level': 'info', 'Scanned': 2, 'Updated': 1, 'Failed': 0}

    def test_syncerate_contract_for_success_failure_warning(self):
        """Match Syncerate's common keys/types while identifying Watchtower as the job."""
        for failed, warn in ((False, False), (True, False), (False, True)):
            records = [self.session | {'Failed': int(failed)}]
            if warn:
                records.insert(0, {'msg': 'retry recovered', 'level': 'warning'})
            payload = self.app.inspect_watchtower_output('\n'.join(map(json.dumps, records)), 0, self.cfg)
            expected_types = dict(status=str, success=bool, title=str, name=str, job=str,
                                  exit_code=int, error=str, stderr=str, warning=bool, skipped_datasets=list)
            for key, kind in expected_types.items():
                self.assertIs(type(payload[key]), kind)
            self.assertEqual(payload['status'], 'failure' if failed else 'success')
            self.assertIs(payload['success'], not failed)
            self.assertEqual(payload['name'], payload['title'])
            self.assertEqual(payload['job'], 'watchtower')
            self.assertIs(payload['warning'], warn)
            self.assertEqual(payload['phase'], 'completed')

    def test_dry_run_notification_matrix(self):
        """Every MQTT/mail opt-in combination is independent and never powers the host."""
        self.cfg.set('power', 'action', 'reboot')
        self.cfg.set('power', 'dry_run', 'true')
        for mqtt_on in (False, True):
            for mail_on in (False, True):
                self.cfg.set('mqtt', 'publish_dry_run', str(mqtt_on))
                self.cfg.set('mail', 'send_dry_run', str(mail_on))
                with patch.object(self.app, 'parse_args', return_value=types.SimpleNamespace(config='unused')), patch.object(self.app, 'load_config', return_value=self.cfg), patch.object(self.app.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)) as worker, patch.object(self.app, 'send_mail_sendmail', return_value=True) as mail, patch.object(self.app.time, 'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.app.main(), 0)
                self.assertEqual(worker.call_count, int(mqtt_on))
                self.assertEqual(mail.call_count, int(mail_on))
                sleep.assert_not_called()
                if mqtt_on:
                    self.assertIn('--mqtt-publish', worker.call_args.args[0])
                    payload = json.loads(json.loads(worker.call_args.kwargs['input'])['message'])
                    self.assertIs(payload['dry_run'], True)
                if mail_on:
                    self.assertTrue(mail.call_args.args[1]['Subject'].startswith('[DRY-RUN] '))

    def test_dry_run_failure_mail_and_disabled_master_switch(self):
        """Preview failure selects on_failure; master switches still override preview opt-ins."""
        self.cfg.set('power', 'dry_run', 'true')
        self.cfg.set('mqtt', 'publish_dry_run', 'true')
        self.cfg.set('mail', 'send_dry_run', 'true')
        with patch.object(self.app, 'parse_args', return_value=types.SimpleNamespace(config='unused')), patch.object(self.app, 'load_config', return_value=self.cfg), patch.object(self.app.subprocess, 'run', side_effect=subprocess.TimeoutExpired('mqtt', 20)), patch.object(self.app, 'send_mail_sendmail', return_value=True) as mail, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.app.main(), 1)
        self.assertEqual(mail.call_args.args[2], 'failure')
        self.cfg.set('mqtt', 'enabled', 'false')
        self.cfg.set('mail', 'enabled', 'false')
        with patch.object(self.app.subprocess, 'run') as worker, patch.object(self.app, 'build_mail_message') as build:
            self.assertTrue(self.app.publish_mqtt(self.cfg)[0])
            self.assertTrue(self.app.send_mail(self.cfg, 'success', 'unused'))
        worker.assert_not_called()
        build.assert_not_called()

    def test_worker_always_non_retained(self):
        """The actual Paho boundary hard-codes retain=False, as Syncerate JSON does."""
        publisher = types.ModuleType('paho.mqtt.publish')
        publisher.single = unittest.mock.Mock()
        request = dict(topic='test/status', message='{}', host='test.invalid', port=1883,
                       username='', password='', client_id='test', qos=1)
        with patch.dict(sys.modules, {'paho.mqtt.publish': publisher}), patch.object(sys, 'stdin', io.StringIO(json.dumps(request))):
            self.app.publish_worker()
        self.assertIs(publisher.single.call_args.kwargs['retain'], False)

    def test_worker_failure_deadline_and_secret_suppression(self):
        """Timeouts/start failures cannot hang or disclose captured credentials."""
        outcomes = [subprocess.TimeoutExpired('mqtt', 20), OSError('secret-password'),
                    types.SimpleNamespace(returncode=1, stderr='secret-password')]
        for outcome in outcomes:
            with patch.object(self.app.subprocess, 'run', **({'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome})):
                ok, text = self.app.publish_mqtt(self.cfg)
            self.assertFalse(ok)
            self.assertNotIn('secret-password', text)

    def test_no_failure_can_be_overridden_in_watchtower_mode(self):
        """Continuation flags and report.status cannot turn an actual failed job into success."""
        self.cfg.set('power', 'continue_on_mqtt_fail', 'true')
        self.cfg.set('power', 'continue_on_mail_fail', 'true')
        self.cfg.set('report', 'status', 'success')
        log = types.SimpleNamespace(returncode=0, stdout=json.dumps(self.session | {'Failed': 1}))
        with patch.object(self.app, '_read_runtime_text', side_effect=[('2026-09-17T10:00:00+00:00', None), ('0', None)]), patch.object(self.app.subprocess, 'run', return_value=log), patch.object(self.app, 'publish_mqtt', return_value=(True, 'sent')) as publish, patch.object(self.app, 'send_mail', return_value=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.app.report_watchtower(self.cfg, '/compose', 'watchtower', '/start', '/exit'), 1)
        publish.assert_called_once()
        self.assertIs(self.cfg.watchtower_report['success'], False)

    def test_bad_markers_never_read_historical_logs(self):
        """Missing timezone, invalid dates/codes, and absent files fail before Docker inspection."""
        for stamp, code in [('invalid', '0'), ('2026-09-17T10:00:00', '0'), ('2026-09-17T10:00:00Z', '-1'), ('2026-09-17T10:00:00Z', '256')]:
            with patch.object(self.app, '_read_runtime_text', side_effect=[(stamp, None), (code, None)]), patch.object(self.app.subprocess, 'run') as docker, patch.object(self.app, 'publish_mqtt', return_value=(True, 'sent')), patch.object(self.app, 'send_mail', return_value=True), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.app.report_watchtower(self.cfg, '/compose', 'watchtower', '/start', '/exit'), 1)
            docker.assert_not_called()

    def test_malformed_logs_running_container_and_duplicate_services(self):
        """Ambiguous or incomplete data must not authorize continuation."""
        for suffix in ('\nnot a log', '\n' + json.dumps(self.session)):
            self.assertFalse(self.app.inspect_watchtower_output(json.dumps(self.session) + suffix, 0, self.cfg)['success'])
        for state in ('running', 'restarting', 'created'):
            self.assertIsNone(self.app.parse_compose_exit_code(json.dumps(dict(Service='watchtower', State=state, ExitCode=0)), 'watchtower'))
        self.assertIsNone(self.app.parse_compose_exit_code(json.dumps([dict(Service='watchtower', ExitCode=0)] * 2), 'watchtower'))

    def test_redaction_and_payload_bounds(self):
        """Large errors remain bounded after configured and generic secrets are removed."""
        self.cfg.set('mqtt', 'password', 'private-secret')
        errors = [dict(msg='Unable to update container "x": password=private-secret ' + 'x' * 2000, level='error')] * 30
        report = self.app.inspect_watchtower_output('\n'.join(map(json.dumps, errors + [self.session])), 0, self.cfg)
        self.assertNotIn('private-secret', json.dumps(report))
        self.assertLessEqual(len(report['stderr']), 4000)
        self.assertLessEqual(len(report['failed_containers']), 20)
        self.assertTrue(report['details_truncated'])

    def test_marker_reader(self):
        """Marker reads reject empty/oversized/missing input and never execute text."""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'marker'
            for content in ('', 'x' * 4097):
                path.write_text(content)
                self.assertIsNotNone(self.app._read_runtime_text(path, 'test')[1])
            path.write_text('0\n')
            self.assertEqual(self.app._read_runtime_text(path, 'test'), ('0', None))
            self.assertIsNotNone(self.app._read_runtime_text(Path(temp) / 'missing', 'test')[1])

    def test_cli_markers_must_be_paired(self):
        """Reject partial runtime correlation and unrelated mode flags at CLI parsing."""
        for flags in (['--watchtower-since-file', '/start'], ['--watchtower-compose', '/compose', '--watchtower-exit-code-file', '/exit'], ['--watchtower-service', 'other']):
            with patch.object(sys, 'argv', ['app', '-c', '/config'] + flags), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                self.app.parse_args()
            self.assertEqual(error.exception.code, 2)

    def test_real_worker_subprocess_with_fake_paho(self):
        """Execute the real worker with a fake Paho module; check wire data and hard timeout."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / 'paho/mqtt'
            package.mkdir(parents=True)
            (root / 'paho/__init__.py').write_text('')
            (package / '__init__.py').write_text('')
            (package / 'publish.py').write_text(
                'import json, os, time\n'
                'def single(topic, **kwargs):\n'
                '    time.sleep(float(os.environ.get("TEST_DELAY", "0")))\n'
                '    with open(os.environ["TEST_CAPTURE"], "w") as f:\n'
                '        json.dump(dict(topic=topic, **kwargs), f)\n')
            capture = root / 'capture.json'
            with patch.dict('os.environ', {'PYTHONPATH': temp, 'TEST_CAPTURE': str(capture), 'TEST_DELAY': '0'}):
                ok, detail = self.app.publish_mqtt(self.cfg)
            self.assertTrue(ok, detail)
            wire = json.loads(capture.read_text())
            self.assertIs(wire['retain'], False)
            self.assertTrue(json.loads(wire['payload'])['success'])
            self.cfg.set('mqtt', 'timeout', '0.15')
            with patch.dict('os.environ', {'PYTHONPATH': temp, 'TEST_CAPTURE': str(capture), 'TEST_DELAY': '5'}):
                ok, detail = self.app.publish_mqtt(self.cfg)
            self.assertFalse(ok)
            self.assertIn('timed out', detail)

    def test_watchtower_preview_notification_matrix(self):
        """Watchtower previews obey both opt-ins and preserve completed-job verification."""
        self.cfg.set('power', 'dry_run', 'true')
        for mqtt_on in (False, True):
            for mail_on in (False, True):
                self.cfg.set('mqtt', 'publish_dry_run', str(mqtt_on))
                self.cfg.set('mail', 'send_dry_run', str(mail_on))
                log = types.SimpleNamespace(returncode=0, stdout=json.dumps(self.session))
                with patch.object(self.app, '_read_runtime_text', side_effect=[('2026-09-17T10:00:00Z', None), ('0', None)]), patch.object(self.app.subprocess, 'run', side_effect=[log, types.SimpleNamespace(returncode=0)] if mqtt_on else [log]) as external, patch.object(self.app, 'send_mail_sendmail', return_value=True) as mail, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.app.report_watchtower(self.cfg, '/compose', 'watchtower', '/start', '/exit'), 0)
                self.assertEqual(external.call_count, 1 + int(mqtt_on))
                self.assertEqual(mail.call_count, int(mail_on))
                self.assertEqual(self.cfg.watchtower_report['phase'], 'dry_run')

    def test_custom_message_survives_ordinary_publish(self):
        """Generated readiness metadata must not silently replace a valid custom message."""
        self.cfg.set('mqtt', 'message', '{{"status":"success","title":"custom"}}')
        with patch.object(self.app.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)) as worker:
            self.app.publish_mqtt(self.cfg, self.app.build_mqtt_report(self.cfg))
        payload = json.loads(json.loads(worker.call_args.kwargs['input'])['message'])
        self.assertEqual(payload, {'status': 'success', 'title': 'custom'})


try:
    import yaml
    from jinja2 import Environment, StrictUndefined
except ImportError:
    yaml = None


@unittest.skipIf(yaml is None, 'Install PyYAML and Jinja2 for automation checks')
class JonsBoTests(unittest.TestCase):
    def setUp(self):
        """Load the shipped automation and a minimal HA-compatible boolean filter."""
        self.flow = yaml.safe_load((ROOT / 'HomeAssistant/jonsbo-daily-with-watchtower.yaml').read_text())
        self.env = Environment(undefined=StrictUndefined)
        self.env.filters['bool'] = lambda value, default=False: (value.lower() in ('true', 'yes', 'on', '1') if isinstance(value, str) else bool(value))

    def condition(self, condition, variables):
        """Evaluate the trigger/template subset used by result routing."""
        if condition['condition'] == 'trigger':
            expected = condition['id']
            return variables['trigger']['id'] in (expected if isinstance(expected, list) else [expected])
        return self.env.from_string(condition['value_template']).render(**variables).strip().lower() == 'true'

    def commands(self, trigger_id, report):
        """Walk result guards/choose branches and collect emitted MQTT command payloads."""
        variables = dict(trigger={'id': trigger_id}, report=report, mqtt_status=report.get('status', 'unknown'))
        guards = [step for step in self.flow['actions'] if step.get('condition') == 'template']
        if not all(self.condition(step, variables) for step in guards):
            return []
        handler = next(step for step in self.flow['actions'] if step.get('alias') == 'Handle success or failure')
        commands = []
        for branch in handler['choose']:
            if all(self.condition(c, variables) for c in branch['conditions']):
                for step in branch['sequence']:
                    for route in step.get('choose', []):
                        if all(self.condition(c, variables) for c in route['conditions']):
                            commands += [action['data']['payload'] for action in route['sequence'] if action.get('action') == 'mqtt.publish']
                break
        return commands

    def test_cleanup_starts_watchtower_and_only_watchtower_success_shuts_down(self):
        """Protect the exact chain requested by the user, including failure/preview guards."""
        self.assertEqual(self.commands('cleanupinsyncoidsnapshots_status', {'status': 'success'}), ['start_watchtower'])
        good = dict(status='success', success=True, exit_code=0, host='JonsBo-N3-CWWK-N355', job='watchtower', phase='completed', dry_run=False)
        self.assertEqual(self.commands('watchtower_status', good), ['shutdown_delay'])
        for changes in ({'status': 'failure'}, {'status': 'unknown'}, {'dry_run': True}, {'success': False}, {'exit_code': 1}, {'host': 'other'}, {'job': 'mqtt-power-action'}, {'phase': 'before_action'}):
            self.assertEqual(self.commands('watchtower_status', good | changes), [])
        self.assertEqual(self.commands('watchtower_status', {}), [])
        self.assertEqual(self.commands('cleanupinsyncoidsnapshots_status', {'status': 'failure'}), [])

    def test_topic_and_config_agree(self):
        """Ensure the supplied JonsBo publisher and consumer use the same host/topic."""
        import configparser
        config = configparser.ConfigParser(interpolation=None)
        config.read(ROOT / 'configs/config-jonsbo-watchtower.example.ini')
        trigger = next(t for t in self.flow['triggers'] if t['id'] == 'watchtower_status')
        self.assertEqual(trigger['options']['topic'], config['mqtt']['topic'])
        self.assertEqual(config['power']['action'], 'none')
        self.assertFalse(config.getboolean('power', 'dry_run'))
        self.assertFalse(config.getboolean('mqtt', 'retain'))
        self.assertEqual(self.flow['mode'], 'queued')
        self.assertEqual(len(self.flow['triggers']), 6)
        self.assertEqual(self.flow['triggers'][0]['weekday'], ['mon'])


if __name__ == '__main__':
    unittest.main()
