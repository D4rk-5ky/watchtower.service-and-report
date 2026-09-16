"""Offline Watchtower/systemd/HA flow regressions; no real external actions."""

import configparser
import contextlib
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import test_mqtt_reports as reports

try:
    import yaml
    from jinja2 import Environment, StrictUndefined
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[1]


class WatchtowerReportTests(unittest.TestCase):
    def setUp(self):
        loader = reports.ReportTests()
        loader.setUp()
        self.app, self.cfg = loader.app, loader.cfg
        self.session = {'msg': 'Session done', 'level': 'info',
                        'Scanned': 5, 'Updated': 2, 'Failed': 0}

    def report(self, records, code=0):
        return self.app.inspect_watchtower_output(
            '\n'.join(json.dumps(record) for record in records), code, self.cfg)

    def test_session_gate_and_exit_codes(self):
        for changes, expected in [({}, 'success'), ({'Updated': 0}, 'success'),
                                  ({'Scanned': 0, 'Updated': 0}, 'success'),
                                  ({'Failed': 1}, 'failure'), ({'Updated': 6}, 'failure'),
                                  ({'Failed': False}, 'failure'), ({'Scanned': '5'}, 'failure'),
                                  ({'Scanned': -1}, 'failure'), ({'Updated': None}, 'failure')]:
            with self.subTest(changes=changes):
                value = self.report([self.session | changes])
                self.assertEqual(value['status'], expected)
                self.assertEqual(value['exit_code'], 0 if expected == 'success' else 1)
        self.assertEqual(self.report([], 0)['status'], 'failure')
        self.assertEqual(self.report([self.session, self.session], 0)['status'], 'failure')
        self.assertEqual(self.report([self.session], 7)['exit_code'], 7)

    def test_failed_container_details_and_redaction(self):
        failed = {'level': 'info', 'msg': 'Unable to update container "/example-app": pull access denied. Proceeding to next.'}
        report = self.report([failed, self.session])
        self.assertEqual(report['status'], 'failure')
        self.assertEqual(report['failed_containers'][0]['name'], '/example-app')
        self.assertIn('pull access denied', report['stderr'])

        self.cfg.set('mqtt', 'password', 'private-secret')
        noisy = {'level': 'error', 'msg': 'https://user:pass@example.invalid password=private-secret failure'}
        report = self.report([noisy, self.session])
        self.assertNotIn('private-secret', json.dumps(report))
        self.assertNotIn('user:pass', json.dumps(report))
        self.assertIn('[redacted]', json.dumps(report))

    def test_parse_compose_exit_code_shapes(self):
        one = json.dumps({'Service': 'watchtower', 'ExitCode': 0, 'State': 'exited'})
        self.assertEqual(self.app.parse_compose_exit_code(one, 'watchtower'), 0)
        array = json.dumps([{'Service': 'watchtower', 'ExitCode': '3'}])
        self.assertEqual(self.app.parse_compose_exit_code(array, 'watchtower'), 3)
        lines = '\n'.join([json.dumps({'Service': 'other', 'ExitCode': 0}),
                           json.dumps({'Service': 'watchtower', 'ExitCode': 4})])
        self.assertEqual(self.app.parse_compose_exit_code(lines, 'watchtower'), 4)
        self.assertIsNone(self.app.parse_compose_exit_code('', 'watchtower'))
        self.assertIsNone(self.app.parse_compose_exit_code('{}', 'watchtower'))

    def test_reporter_reads_completed_job_without_starting_it(self):
        ps = types.SimpleNamespace(returncode=0, stdout=json.dumps(
            {'Service': 'watchtower', 'ExitCode': 0, 'State': 'exited'}))
        logs = types.SimpleNamespace(returncode=0, stdout=json.dumps(self.session))
        with patch.object(self.app.subprocess, 'run', side_effect=[ps, logs]) as docker, \
             patch.object(self.app, 'publish_mqtt', return_value=(True, 'sent')) as publish, \
             patch.object(self.app, 'send_mail', return_value=True) as mail, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.app.report_watchtower(self.cfg, '/opt/watchtower/docker-compose.yaml'), 0)
        self.assertEqual(docker.call_count, 2)
        first = docker.call_args_list[0].args[0]
        second = docker.call_args_list[1].args[0]
        self.assertIn('ps', first)
        self.assertNotIn('up', first)
        self.assertNotIn('run', first)
        self.assertIn('logs', second)
        self.assertNotIn('up', second)
        publish.assert_called_once()
        mail.assert_called_once()
        self.assertEqual(self.cfg.watchtower_report['status'], 'success')

    def test_reporter_publishes_failure_for_failed_or_unverifiable_job(self):
        cases = [
            (types.SimpleNamespace(returncode=0, stdout=json.dumps({'Service': 'watchtower', 'ExitCode': 9})),
             types.SimpleNamespace(returncode=0, stdout=json.dumps(self.session))),
            (types.SimpleNamespace(returncode=0, stdout=json.dumps({'Service': 'watchtower', 'ExitCode': 0})),
             types.SimpleNamespace(returncode=0, stdout='not json')),
            (types.SimpleNamespace(returncode=1, stdout='compose ps failed'),
             types.SimpleNamespace(returncode=1, stdout='compose logs failed')),
        ]
        for ps, logs in cases:
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(ROOT / 'configs' / 'config-sendmail-none.example.ini')
            with self.subTest(ps=ps.returncode, logs=logs.returncode), \
                 patch.object(self.app.subprocess, 'run', side_effect=[ps, logs]), \
                 patch.object(self.app, 'publish_mqtt', return_value=(True, 'sent')) as publish, \
                 patch.object(self.app, 'send_mail', return_value=True), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.app.report_watchtower(cfg, '/opt/watchtower/docker-compose.yaml'), 1)
            publish.assert_called_once()
            self.assertEqual(cfg.watchtower_report['status'], 'failure')

    def test_reporting_failure_does_not_turn_job_into_success(self):
        ps = types.SimpleNamespace(returncode=0, stdout=json.dumps({'Service': 'watchtower', 'ExitCode': 0}))
        logs = types.SimpleNamespace(returncode=0, stdout=json.dumps(self.session))
        with patch.object(self.app.subprocess, 'run', side_effect=[ps, logs]), \
             patch.object(self.app, 'publish_mqtt', side_effect=RuntimeError('broker unavailable')), \
             patch.object(self.app, 'send_mail', return_value=False), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.app.report_watchtower(self.cfg, '/opt/watchtower/docker-compose.yaml'), 1)
        self.assertEqual(self.cfg.watchtower_report['status'], 'success')

    def test_preflight_and_cli(self):
        for section, option, value in [('power', 'action', 'shutdown'),
                                       ('mqtt', 'retain', 'true'),
                                       ('mqtt', 'message', 'custom')]:
            old = self.cfg.get(section, option)
            self.cfg.set(section, option, value)
            with patch.object(self.app.subprocess, 'run') as docker, \
                 patch.object(self.app, 'publish_mqtt') as publish, \
                 contextlib.redirect_stdout(io.StringIO()), \
                 self.assertRaises(SystemExit) as err:
                self.app.report_watchtower(self.cfg, '/compose')
            self.assertEqual(err.exception.code, 2)
            docker.assert_not_called()
            publish.assert_not_called()
            self.cfg.set(section, option, old)

        with patch.object(sys, 'argv', ['app', '-c', 'config.ini',
                                        '--watchtower-compose', '/compose',
                                        '--watchtower-service', 'updater']):
            args = self.app.parse_args()
        self.assertEqual(args.watchtower_compose, '/compose')
        self.assertEqual(args.watchtower_service, 'updater')

    @unittest.skipIf(yaml is None, 'Install PyYAML and Jinja2 for consumer template checks')
    def test_generic_consumer_understands_success_and_failure(self):
        consumer = yaml.safe_load((ROOT / 'HomeAssistant/syncerate-all-servers.yaml').read_text(encoding='utf-8'))
        env = Environment(undefined=StrictUndefined)
        env.filters['bool'] = lambda value: str(value).strip().lower() in ('true', '1', 'yes', 'on')
        self.assertEqual(consumer['triggers'][0]['options']['topic'], self.cfg.get('mqtt', 'topic'))
        for failure in [False, True]:
            records = [self.session | {'Failed': int(failure)}]
            if failure:
                records.insert(0, {'level': 'info',
                                   'msg': 'Unable to update container "/example-app": pull failed. Proceeding to next.'})
            wire = self.report(records)
            context = {'trigger': {'payload_json': wire}}
            for key, template in consumer['actions'][0]['variables'].items():
                context[key] = env.from_string(template).render(**context).strip()
            self.assertEqual(context['mqtt_status'], 'failure' if failure else 'success')
            branch = consumer['actions'][1]['choose'][int(failure)]
            self.assertEqual(env.from_string(branch['conditions'][0]['value_template']).render(**context), 'True')


@unittest.skipIf(yaml is None, 'Install PyYAML and Jinja2 to run YAML flow checks')
class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.flow = yaml.safe_load((ROOT / 'HomeAssistant/watchtower-manual-update.yaml').read_text(encoding='utf-8'))
        self.templates = Environment(undefined=StrictUndefined)

    def render_bool(self, source, variables):
        return self.templates.from_string(source).render(**variables).strip().lower() == 'true'

    def condition(self, item, ready, variables):
        kind = item['condition']
        if kind == 'state':
            self.assertEqual(item['entity_id'], 'binary_sensor.example_host_ready')
            self.assertEqual(item['for'], {'minutes': 4})
            return ready
        if kind == 'not':
            return not all(self.condition(c, ready, variables) for c in item['conditions'])
        if kind == 'template':
            return self.render_bool(item['value_template'], variables)
        self.fail('Unexpected condition: ' + kind)

    def walk_actions(self, sequence, ready, variables, actions):
        for step in sequence:
            if 'stop' in step:
                return False
            if 'if' in step:
                branch = 'then' if all(self.condition(c, ready, variables) for c in step['if']) else 'else'
                if not self.walk_actions(step.get(branch, []), ready, variables, actions):
                    return False
            elif 'condition' in step:
                if not self.condition(step, ready, variables):
                    return False
            elif 'action' in step:
                actions.append((step['action'], step.get('data', {}).get('payload')))
            elif 'wait_for_trigger' in step:
                pass
            else:
                self.fail('Unexpected action structure')
        return True

    def test_shutdown_only_after_success(self):
        for ready, completed, outcome, shutdown in [(False, True, 'success', False),
                                                    (True, False, None, False),
                                                    (True, True, 'failure', False),
                                                    (True, True, 'success', True)]:
            with self.subTest(ready=ready, completed=completed, outcome=outcome):
                actions = []
                variables = {'wait': {'completed': completed,
                                      'trigger': {'id': outcome} if completed else None}}
                self.walk_actions(self.flow['actions'][1:], ready, variables, actions)
                self.assertEqual(('mqtt.publish', 'shutdown') in actions, shutdown)
                self.assertEqual(any(name.startswith('script.') for name, _ in actions), shutdown)
                self.assertEqual(('mqtt.publish', 'start_watchtower') in actions, ready)

    def test_json_wait_matching_and_redacted_examples(self):
        wait = next(step for step in self.flow['actions'] if 'wait_for_trigger' in step)
        self.assertEqual(wait['timeout'], {'minutes': 30})
        self.assertIs(wait['continue_on_timeout'], True)
        for trigger in wait['wait_for_trigger']:
            self.assertEqual(trigger['topic'], 'homeassistant/watchtower/example-host/status')
            self.assertEqual(trigger['payload'], trigger['id'])
            template = self.templates.from_string(trigger['value_template'])
            for payload, expected in [({'status': ' SUCCESS '}, 'success'),
                                      ({'status': 'failure'}, 'failure'),
                                      ({}, 'unknown')]:
                self.assertEqual(template.render(value_json=payload), expected)

        text = json.dumps(self.flow)
        self.assertNotRegex(text, r'\b(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\.')
        self.assertIn('example_host', text)

    def test_schedule_readiness_and_compose_logging(self):
        self.assertEqual(self.flow['triggers'], [{'trigger': 'time', 'at': '17:30:00', 'enabled': False}])
        self.assertEqual(self.flow['conditions'], [{'condition': 'time', 'weekday': ['sun']}])
        self.assertIn('repeat.index >= 40', json.dumps(self.flow))
        self.assertEqual(self.flow['mode'], 'single')
        repeat = self.flow['actions'][0]['then'][0]['repeat']
        self.assertEqual(repeat['sequence'][-1], {'delay': {'seconds': 15}})
        self.assertEqual(repeat['until'][0]['conditions'][0]['for'], {'minutes': 4})
        compose = yaml.safe_load((ROOT / 'compose.example.yaml').read_text())
        env = compose['services']['watchtower']['environment']
        self.assertEqual(env['WATCHTOWER_RUN_ONCE'], 'true')
        self.assertEqual(env['WATCHTOWER_LOG_FORMAT'], 'json')
        self.assertEqual(env['WATCHTOWER_LOG_LEVEL'], 'info')
        self.assertTrue(env['WATCHTOWER_NOTIFICATION_EMAIL_SERVER_PASSWORD'].startswith('${'))


if __name__ == '__main__':
    unittest.main()
