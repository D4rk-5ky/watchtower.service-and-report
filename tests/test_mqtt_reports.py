"""Offline report-contract and safety regressions; never contact real services."""

import configparser
import contextlib
import io
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]


class ReportTests(unittest.TestCase):
    def setUp(self):
        """Load a fresh app with an in-memory Paho stand-in and example config."""
        mqtt = types.ModuleType('paho.mqtt.client')
        mqtt.MQTT_ERR_SUCCESS = 0
        mqtt.Client = Mock(side_effect=AssertionError('Unexpected MQTT client creation'))
        package = types.ModuleType('paho.mqtt')
        package.client = mqtt
        paho = types.ModuleType('paho')
        paho.mqtt = package
        self.app = types.ModuleType('app_under_test')
        self.app.__file__ = str(ROOT / 'mqtt_power_action_none.py')
        source = ROOT / 'mqtt_power_action_none.py'
        with patch.dict(sys.modules, {'paho': paho, 'paho.mqtt': package, 'paho.mqtt.client': mqtt}):
            exec(compile(source.read_bytes(), str(source), 'exec'), self.app.__dict__)
        self.cfg = configparser.ConfigParser(interpolation=None)
        self.cfg.read(ROOT / 'configs' / 'config-sendmail-none.example.ini')
        self.cfg.set('power', 'dry_run', 'false')

    def assert_config_error(self, function, *args):
        """Require a controlled config exit instead of a traceback or side effect."""
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            function(*args)
        self.assertEqual(error.exception.code, 2)

    def test_default_report(self):
        """Automatic output is an object with exactly the documented typed fields."""
        report = json.loads(self.app.build_mqtt_message(self.cfg))
        self.assertEqual({k: report[k] for k in ('status', 'title', 'exit_code', 'warning', 'error', 'stderr', 'event', 'host')}, dict(status='success', title='example-host: none',
                                     exit_code=0, warning=False, error='', stderr='',
                                     event='success', host='example-host'))

    def test_auto_without_report_section(self):
        """Automatic defaults work without maintaining an original config snapshot."""
        cfg = self.cfg
        cfg.remove_section('report')
        report = json.loads(self.app.build_mqtt_message(cfg))
        self.assertEqual(report['status'], 'success')
        self.assertEqual(report['exit_code'], 0)
        self.assertEqual(report['host'], 'example-host')

    def test_status_independent_of_action(self):
        """Both job outcomes work with every action while preserving legacy events."""
        for action, event in [('none', 'success'), ('shutdown', 'server_shutdown'), ('reboot', 'server_reboot')]:
            for status in ['success', 'failure']:
                with self.subTest(action=action, status=status):
                    self.cfg.set('power', 'action', action)
                    self.cfg.set('report', 'status', status)
                    report = json.loads(self.app.build_mqtt_message(self.cfg))
                    self.assertEqual(report['status'], status)
                    self.assertEqual(report['exit_code'], 0 if status == 'success' else 1)
                    self.assertEqual(report['event'], event)

    def test_escaping_and_failure_details(self):
        """Quotes, Unicode, slashes, braces and newlines survive the JSON round trip."""
        hostname = 'Example "host" \\ ø {host}'
        error = 'Backup "failed" at C:\\backup\\data'
        stderr = 'line one\nline two {detail} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“ ÃƒÆ’Ã‚Â¸'
        self.cfg.set('server', 'hostname', hostname)
        self.cfg.set('report', 'status', 'FAILURE')
        self.cfg.set('report', 'title', '{hostname}: {action}')
        self.cfg.set('report', 'exit_code', '23')
        self.cfg.set('report', 'warning', 'true')
        self.cfg.set('report', 'error', error)
        self.cfg.set('report', 'stderr', stderr)
        report = json.loads(self.app.build_mqtt_message(self.cfg))
        self.assertEqual(report['title'], hostname + ': none')
        self.assertEqual(report['host'], hostname)
        self.assertEqual(report['error'], error)
        self.assertEqual(report['stderr'], stderr)
        self.assertEqual(report['exit_code'], 23)
        self.assertIs(report['warning'], True)
        self.assertEqual(report['status'], 'failure')

    def test_custom_object_and_title_fallback(self):
        """Custom payloads replace report settings and allow the consumer's name/job keys."""
        for label in ['title', 'name', 'job']:
            payload = {'status': 'failure', label: 'Backup', 'exit_code': 12,
                       'warning': False, 'error': 'Unavailable', 'stderr': 'Timed out',
                       'extra': {'source': 'caller'}}
            template = json.dumps(payload).replace('{', '{{').replace('}', '}}')
            self.cfg.set('mqtt', 'message', template)
            self.assertEqual(json.loads(self.app.build_mqtt_message(self.cfg)), payload)

    def test_commented_custom_example(self):
        """The shipped commented template actually renders to consumer-compatible JSON."""
        example = (ROOT / 'configs' / 'config-sendmail-none.example.ini').read_text()
        template = next(line.split('=', 1)[1].strip() for line in example.splitlines() if line.startswith('#message ='))
        self.cfg.set('mqtt', 'message', template)
        report = json.loads(self.app.build_mqtt_message(self.cfg))
        self.assertEqual(report['status'], 'success')
        self.assertEqual(report['host'], 'example-host')
        self.assertEqual(report['source'], 'unattended-upgrades')

    def test_invalid_custom_payloads(self):
        """Plain text, arrays, missing/unknown status, bad types and nonfinite JSON fail."""
        invalid = ['plain text', '[]', 'null', '"success"', '{{}}',
                   '{{"event":"success"}}', '{{"status":"unknown"}}',
                   '{{"status":"success","exit_code":true}}',
                   '{{"status":"success","exit_code":"0"}}',
                   '{{"status":"success","warning":"false"}}',
                   '{{"status":"success","title":null}}',
                   '{{"status":"failure","error":123}}',
                   '{{"status":"failure","stderr":[]}}',
                   '{{"status":"success","extra":NaN}}',
                   '{{"status":"success","extra":Infinity}}',
                   '{{"status":"success",}}']
        for template in invalid:
            with self.subTest(template=template):
                self.cfg.set('mqtt', 'message', template)
                self.assert_config_error(self.app.build_mqtt_message, self.cfg)

    def test_invalid_auto_settings(self):
        """Invalid automatic status/code/warning are config errors."""
        for option, value in [('status', 'running'), ('exit_code', '1.5'), ('warning', 'maybe')]:
            with self.subTest(option=option):
                previous = self.cfg.get('report', option)
                self.cfg.set('report', option, value)
                self.assert_config_error(self.app.build_mqtt_message, self.cfg)
                self.cfg.set('report', option, previous)

    def test_invalid_report_stops_before_io(self):
        """Even continuation flags cannot publish or execute power with invalid JSON."""
        self.cfg.set('mqtt', 'message', 'not JSON')
        self.cfg.set('power', 'action', 'reboot')
        self.cfg.set('power', 'dry_run', 'false')
        self.cfg.set('power', 'continue_on_mqtt_fail', 'true')
        self.cfg.set('power', 'continue_on_mail_fail', 'true')
        # Supply the parsed INI in memory; execute the real load_config validation.
        with patch.object(self.app.configparser, 'ConfigParser', return_value=self.cfg), patch.object(self.cfg, 'read', return_value=['invalid.ini']), patch.object(sys, 'argv', ['app', '-c', 'invalid.ini']), patch.object(self.app, 'publish_mqtt') as publish, patch.object(self.app, 'send_mail') as mail, patch.object(self.app.subprocess, 'run') as power:
            self.assert_config_error(self.app.main)
            publish.assert_not_called()
            mail.assert_not_called()
            power.assert_not_called()

    def test_config_parse_errors_identify_duplicates_without_echoing_secrets(self):
        """Malformed INI explains the line/option while never printing config values."""
        cases = [
            ("[mqtt]\npublish_dry_run = true\npublish_dry_run = false\n",
             "Duplicate option 'publish_dry_run' in section [mqtt] at line 3"),
            ("[mqtt]\na = 1\n[mqtt]\nb = 2\n",
             "Duplicate section [mqtt] at line 3"),
            ("password = TOPSECRET\n[mqtt]\na = 1\n",
             "Expected an INI section header such as [server] before at line 1"),
            ("[mqtt]\npassword = TOPSECRET\nthis line is invalid\n",
             "Could not parse INI syntax at line(s) 3"),
        ]
        for text, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'config.ini'
                path.write_text(text, encoding='utf-8')
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as error:
                    self.app.load_config(str(path))
                self.assertEqual(error.exception.code, 2)
                message = output.getvalue()
                self.assertIn(expected, message)
                self.assertNotIn('TOPSECRET', message)

    def test_published_payload_and_shared_topic(self):
        """Either outcome uses the configured topic and bounded worker transport."""
        for status in ('success', 'failure'):
            self.cfg.set('report', 'status', status)
            with patch.object(self.app.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)) as worker:
                self.assertTrue(self.app.publish_mqtt(self.cfg)[0])
            request = json.loads(worker.call_args.kwargs['input'])
            report = json.loads(request['message'])
            self.assertEqual(request['topic'], 'homeassistant/watchtower/status')
            self.assertEqual(request['qos'], 1)
            self.assertEqual(report['status'], status)
            self.assertIs(report['success'], status == 'success')
            self.assertEqual(worker.call_args.kwargs['timeout'], 20)
            self.assertNotIn(request['password'] or 'unused-secret', str(worker.call_args.args[0]))

    def test_optional_mqtt_disabled_needs_no_paho_or_mqtt_settings(self):
        """Disabled MQTT is a dependency-free no-op and ignores unused MQTT settings."""
        self.cfg.set('mqtt', 'enabled', 'false')
        self.cfg.remove_option('mqtt', 'host')
        self.cfg.remove_option('mqtt', 'topic')
        self.cfg.set('mqtt', 'qos', '99')
        self.cfg.set('mqtt', 'message', 'not JSON')
        self.app.mqtt = None
        with patch.object(self.app.configparser, 'ConfigParser', return_value=self.cfg), \
             patch.object(self.cfg, 'read', return_value=['disabled-mqtt.ini']):
            loaded = self.app.load_config('disabled-mqtt.ini')
        self.assertIs(loaded, self.cfg)
        with patch.object(self.app.subprocess, 'run') as client:
            self.assertEqual(self.app.publish_mqtt(self.cfg),
                             (True, 'MQTT disabled by configuration.'))
        client.assert_not_called()

    def test_optional_mail_disabled_ignores_unused_mail_settings(self):
        """Disabled mail ignores backend/recipient/SMTP settings and never sends."""
        self.cfg.set('mail', 'enabled', 'false')
        self.cfg.set('mail', 'backend', 'invalid-backend')
        self.cfg.set('mail', 'to', '')
        self.cfg.set('mail', 'on_success', 'true')
        self.cfg.set('mail', 'on_failure', 'true')
        with patch.object(self.app.configparser, 'ConfigParser', return_value=self.cfg), \
             patch.object(self.cfg, 'read', return_value=['disabled-mail.ini']):
            loaded = self.app.load_config('disabled-mail.ini')
        self.assertIs(loaded, self.cfg)
        with patch.object(self.app, 'build_mail_message') as build, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.app.send_mail(self.cfg, 'success', 'unused'))
        build.assert_not_called()

    def test_omitted_optional_sections_are_disabled(self):
        """A config may omit both optional output sections entirely."""
        self.cfg.remove_section('mqtt')
        self.cfg.remove_section('mail')
        self.app.mqtt = None
        with patch.object(self.app.configparser, 'ConfigParser', return_value=self.cfg), \
             patch.object(self.cfg, 'read', return_value=['local-only.ini']):
            loaded = self.app.load_config('local-only.ini')
        self.assertFalse(self.app.feature_enabled(loaded, 'mqtt'))
        self.assertFalse(self.app.feature_enabled(loaded, 'mail'))
        self.assertEqual(self.app.publish_mqtt(loaded),
                         (True, 'MQTT disabled by configuration.'))

    def test_mqtt_only_mode_never_sends_mail(self):
        """mail.enabled=false leaves MQTT and the later power path independent."""
        self.cfg.set('mail', 'enabled', 'false')
        with patch.object(self.app, 'parse_args', return_value=types.SimpleNamespace(config='unused')), \
             patch.object(self.app, 'load_config', return_value=self.cfg), \
             patch.object(self.app, 'publish_mqtt', return_value=(True, 'sent')) as publish, \
             patch.object(self.app, 'send_mail') as mail, \
             patch.object(self.app, 'run_power_action') as power, \
             contextlib.redirect_stdout(io.StringIO()):
            self.app.main()
        publish.assert_called_once()
        mail.assert_not_called()
        power.assert_called_once_with(self.cfg)

    def test_mail_only_mode_needs_no_mqtt_transport(self):
        """Mail-only mode bypasses the MQTT worker and retains the power gate."""
        self.cfg.set('mqtt', 'enabled', 'false')
        with patch.object(self.app, 'parse_args', return_value=types.SimpleNamespace(config='unused')), patch.object(self.app, 'load_config', return_value=self.cfg), patch.object(self.app.subprocess, 'run') as worker, patch.object(self.app, 'send_mail', return_value=True) as mail, patch.object(self.app, 'run_power_action') as power, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.app.main(), 0)
        worker.assert_not_called()
        mail.assert_called_once()
        power.assert_called_once_with(self.cfg)

    def test_none_and_dry_run_guards(self):
        """Every original action/dry-run combination retains its command suppression."""
        for action in ['none', 'shutdown', 'reboot']:
            for dry in ['true', 'false']:
                self.cfg.set('power', 'action', action)
                self.cfg.set('power', 'dry_run', dry)
                with patch.object(self.app.subprocess, 'run') as command, contextlib.redirect_stdout(io.StringIO()):
                    self.app.run_power_action(self.cfg)
                    if action == 'none' or dry == 'true':
                        command.assert_not_called()
                    else:
                        command.assert_called_once_with(['systemctl', 'poweroff' if action == 'shutdown' else 'reboot'], check=True, capture_output=True, text=True)

    def test_failure_gates(self):
        """Notification failures abort power unless the matching explicit override is set."""
        for failed_channel in ('mqtt', 'mail'):
            for allowed in (False, True):
                self.cfg.set('power', 'continue_on_mqtt_fail', str(allowed if failed_channel == 'mqtt' else False))
                self.cfg.set('power', 'continue_on_mail_fail', str(allowed if failed_channel == 'mail' else False))
                with patch.object(self.app, 'parse_args', return_value=types.SimpleNamespace(config='unused')), patch.object(self.app, 'load_config', return_value=self.cfg), patch.object(self.app, 'publish_mqtt', return_value=(failed_channel != 'mqtt', 'mock result')), patch.object(self.app, 'send_mail', return_value=failed_channel != 'mail'), patch.object(self.app, 'run_power_action') as power, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.app.main(), 0 if allowed else 1)
                    self.assertEqual(power.called, allowed)

    def test_dry_run_skips_delay_and_notifications(self):
        """The supplied Python preview skips delay as well as mail/MQTT/power by default."""
        self.cfg.set('power', 'action', 'reboot')
        self.cfg.set('power', 'dry_run', 'true')
        with patch.object(self.app, 'parse_args', return_value=types.SimpleNamespace(config='unused')), patch.object(self.app, 'load_config', return_value=self.cfg), patch.object(self.app, 'send_mail') as mail, patch.object(self.app.subprocess, 'run') as command, patch.object(self.app.time, 'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.app.main(), 0)
        sleep.assert_not_called()
        command.assert_not_called()
        mail.assert_not_called()

    def test_power_failure_is_reported_by_mail(self):
        """A rejected power command retains its exit code and reports failure to MQTT/mail."""
        self.cfg.set('power', 'action', 'reboot')
        with patch.object(self.app, 'parse_args', return_value=types.SimpleNamespace(config='unused')), patch.object(self.app, 'load_config', return_value=self.cfg), patch.object(self.app, 'publish_mqtt', return_value=(True, 'sent')) as publish, patch.object(self.app, 'send_mail', return_value=True) as mail, patch.object(self.app.subprocess, 'run', side_effect=subprocess.CalledProcessError(5, ['systemctl', 'reboot'])), patch.object(self.app.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.app.main(), 5)
        self.assertEqual([c.args[1] for c in mail.call_args_list], ['success', 'failure'])
        self.assertEqual(publish.call_args.args[1]['exit_code'], 5)

    def test_mail_includes_same_json(self):
        """Mail troubleshooting context includes the exact generated report."""
        message = self.app.build_mail_message(self.cfg, 'success', 'MQTT published')
        report_line = next(line.split(': ', 1)[1] for line in message.get_content().splitlines() if line.startswith('MQTT message: '))
        received = json.loads(report_line)
        expected = json.loads(self.app.build_mqtt_message(self.cfg))
        received.pop('timestamp'); expected.pop('timestamp')
        self.assertEqual(received, expected)

    def test_both_config_examples_load(self):
        """Both distributed configs load through the app and produce the right JSON event."""
        for name, backend, action in [('config-sendmail-none.example.ini', 'sendmail', 'none'),
                                      ('config-smtp.example.ini', 'smtp', 'none')]:
            with self.subTest(name=name):
                cfg = self.app.load_config(str(ROOT / 'configs' / name))
                self.assertEqual(cfg.get('mail', 'backend'), backend)
                self.assertTrue(cfg.getboolean('mqtt', 'enabled'))
                self.assertTrue(cfg.getboolean('mail', 'enabled'))
                self.assertEqual(sum(len(cfg.items(section)) for section in cfg.sections()), 48)
                self.assertEqual(cfg.get('power', 'action'), action)
                self.assertTrue(cfg.getboolean('power', 'dry_run'))
                self.assertFalse(cfg.getboolean('power', 'continue_on_mqtt_fail'))
                self.assertFalse(cfg.getboolean('power', 'continue_on_mail_fail'))
                report = json.loads(self.app.build_mqtt_message(cfg))
                self.assertEqual(report['status'], 'success')
                self.assertEqual(report['event'], 'success' if action == 'none' else 'server_shutdown')
                text = (ROOT / 'configs' / name).read_text()
                self.assertNotIn('\\_', text)
                self.assertNotIn('\\@', text)
                template = next(line.split('=', 1)[1].strip() for line in text.splitlines() if line.startswith('#message ='))
                cfg.set('mqtt', 'message', template)
                self.assertEqual(json.loads(self.app.build_mqtt_message(cfg))['status'], 'success')

    def test_smtp_starttls_delivery(self):
        """The supplied SMTP config selects STARTTLS, logs in and sends the report email."""
        cfg = self.app.load_config(str(ROOT / 'configs' / 'config-smtp.example.ini'))
        cfg.set('power', 'dry_run', 'false')
        with patch.object(self.app.smtplib, 'SMTP') as smtp, patch.object(self.app.smtplib, 'SMTP_SSL') as smtp_ssl, patch.object(self.app.ssl, 'create_default_context', return_value='test-context'), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.app.send_mail(cfg, 'success', 'MQTT published'))
            smtp.assert_called_once_with('smtp.example.com', 587, timeout=20.0)
            smtp_ssl.assert_not_called()
            server = smtp.return_value.__enter__.return_value
            message = server.send_message.call_args.args[0]
            self.assertEqual(server.method_calls, [call.ehlo(), call.starttls(context='test-context'),
                             call.ehlo(), call.login('sender@example.com', 'replace-with-password'),
                             call.send_message(message)])
            self.assertEqual(message['To'], 'receiver@example.com')
            self.assertEqual(message['From'], 'sender@example.com')
            self.assertIn('\"status\":\"success\"', message.get_content())

    def test_smtp_ssl_and_environment_password(self):
        """Implicit TLS selects SMTP_SSL and accepts the configured password environment."""
        cfg = self.app.load_config(str(ROOT / 'configs' / 'config-smtp.example.ini'))
        cfg.set('power', 'dry_run', 'false')
        cfg.set('smtp', 'ssl', 'true')
        cfg.set('smtp', 'port', '465')
        cfg.set('smtp', 'password', '')
        cfg.set('smtp', 'password_env', 'MQTT_ACTION_TEST_SMTP_SECRET')
        with patch.dict('os.environ', {'MQTT_ACTION_TEST_SMTP_SECRET': 'test-secret'}), patch.object(self.app.smtplib, 'SMTP') as smtp, patch.object(self.app.smtplib, 'SMTP_SSL') as smtp_ssl, patch.object(self.app.ssl, 'create_default_context', return_value='test-context'), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.app.send_mail(cfg, 'success', 'MQTT published'))
            smtp.assert_not_called()
            smtp_ssl.assert_called_once_with('smtp.example.com', 465, timeout=20.0, context='test-context')
            server = smtp_ssl.return_value.__enter__.return_value
            server.login.assert_called_once_with('sender@example.com', 'test-secret')
            server.starttls.assert_not_called()
            server.send_message.assert_called_once()

    def test_smtp_missing_password_never_connects(self):
        """An absent resolved environment password fails before any SMTP connection."""
        cfg = self.app.load_config(str(ROOT / 'configs' / 'config-smtp.example.ini'))
        cfg.set('power', 'dry_run', 'false')
        cfg.set('smtp', 'password', '')
        cfg.set('smtp', 'password_env', 'MQTT_ACTION_TEST_SMTP_SECRET')
        with patch.dict('os.environ', {'MQTT_ACTION_TEST_SMTP_SECRET': ''}), patch.object(self.app.smtplib, 'SMTP') as smtp, patch.object(self.app.smtplib, 'SMTP_SSL') as smtp_ssl, contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(self.app.send_mail(cfg, 'success', 'MQTT published'))
            smtp.assert_not_called()
            smtp_ssl.assert_not_called()

    def test_smtp_failure_aborts_power(self):
        """Real SMTP routing under mocks preserves abort-before-power behavior."""
        cfg = self.app.load_config(str(ROOT / 'configs/config-smtp.example.ini'))
        cfg.set('power', 'dry_run', 'false')
        with patch.object(self.app, 'parse_args', return_value=types.SimpleNamespace(config='unused')), patch.object(self.app, 'load_config', return_value=cfg), patch.object(self.app, 'publish_mqtt', return_value=(True, 'sent')), patch.object(self.app.smtplib, 'SMTP', side_effect=OSError('simulated failure')) as smtp, patch.object(self.app, 'run_power_action') as power, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.app.main(), 1)
        self.assertEqual(smtp.call_count, 2)
        power.assert_not_called()

    def test_smtp_full_notification_order(self):
        """Mail readiness is completed before publishing readiness for a power action."""
        events = []
        cfg = self.app.load_config(str(ROOT / 'configs/config-smtp.example.ini'))
        cfg.set('power', 'dry_run', 'false')
        with patch.object(self.app, 'parse_args', return_value=types.SimpleNamespace(config='unused')), patch.object(self.app, 'load_config', return_value=cfg), patch.object(self.app, 'publish_mqtt', side_effect=lambda *a, **kw: (events.append('mqtt') or (True, 'sent'))), patch.object(self.app.smtplib, 'SMTP') as smtp, patch.object(self.app.subprocess, 'run') as power, contextlib.redirect_stdout(io.StringIO()):
            smtp.return_value.__enter__.return_value.send_message.side_effect = lambda message: events.append('mail')
            self.assertEqual(self.app.main(), 0)
        self.assertEqual(events, ['mail', 'mqtt'])
        power.assert_not_called()

    def test_sendmail_example_routes_to_sendmail(self):
        """The relocated sendmail config still uses the local sender and valid report bytes."""
        cfg = self.app.load_config(str(ROOT / 'configs' / 'config-sendmail-none.example.ini'))
        cfg.set('power', 'dry_run', 'false')
        with patch.object(self.app, 'find_sendmail', return_value='/test/sendmail'), patch.object(self.app.subprocess, 'run') as sender, patch.object(self.app.smtplib, 'SMTP') as smtp, contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.app.send_mail(cfg, 'success', 'MQTT published'))
            smtp.assert_not_called()
            self.assertEqual(sender.call_args.args[0], ['/test/sendmail', '-t'])
            self.assertIn(b'example-host', sender.call_args.kwargs['input'])
            self.assertTrue(sender.call_args.kwargs['check'])

    def service_settings(self):
        """Read shipped unit directives/variables for static wiring checks, not systemd emulation."""
        directives = {}
        environment = {}
        for line in (ROOT / 'systemd/watchtower.service').read_text().splitlines():
            if not line or line.startswith(('#', '[', ';')):
                continue
            key, value = line.split('=', 1)
            directives.setdefault(key, []).append(value)
            if key == 'Environment':
                for setting in shlex.split(value):
                    name, content = setting.split('=', 1)
                    environment[name] = content
        return directives, environment

    def service_arguments(self, command, environment):
        """Expand the unit's braced variables as single arguments to inspect file references."""
        arguments = shlex.split(command)
        for index, argument in enumerate(arguments):
            for name, value in environment.items():
                argument = argument.replace('${' + name + '}', value)
            arguments[index] = argument
        return arguments

    def test_service_report_paths_and_config_selection(self):
        """ExecStartPost resolves the shipped reporter and either config independently of cwd."""
        unit, _ = self.service_settings()
        install_root = PurePosixPath('/opt/mqtt-power-action')
        self.assertEqual(len(unit['ExecStartPost']), 1)
        for filename, backend in [('config-sendmail-none.example.ini', 'sendmail'), ('config-smtp.example.ini', 'smtp')]:
            args = shlex.split(unit['ExecStartPost'][0])
            args[3] = args[3].replace('config-sendmail-none.example.ini', filename)
            self.assertEqual(args[0], '/usr/bin/python3')
            self.assertEqual(args[2], '-c')
            self.assertEqual(args[4:], ['--watchtower-compose', '/opt/watchtower/docker-compose.yaml', '--watchtower-service', 'watchtower', '--watchtower-since-file', '/run/mqtt-power-action/watchtower-started-at', '--watchtower-exit-code-file', '/run/mqtt-power-action/watchtower-exit-code'])
            script = ROOT / PurePosixPath(args[1]).relative_to(install_root)
            config = ROOT / PurePosixPath(args[3]).relative_to(install_root)
            self.assertEqual(script, ROOT / 'mqtt_power_action_none.py')
            self.assertTrue(script.is_file())
            cfg = self.app.load_config(str(config))
            self.assertEqual(cfg.get('mail', 'backend'), backend)

    def test_service_systemd_owned_lifecycle(self):
        """The unit keeps pull/up/report phases in ExecStartPre/ExecStart/ExecStartPost."""
        unit, _ = self.service_settings()
        self.assertEqual(unit['WorkingDirectory'], ['/opt/watchtower'])
        self.assertEqual(len(unit['ExecStartPre']), 3)
        self.assertEqual(shlex.split(unit['ExecStartPre'][-1]),
                         ['-/usr/bin/docker', 'compose', '-f', 'docker-compose.yaml', 'pull', 'watchtower'])
        start_text = unit['ExecStart'][0]
        self.assertIn('docker compose -f docker-compose.yaml up --pull never', start_text)
        self.assertIn('watchtower-exit-code', start_text)
        self.assertNotIn('pull watchtower', start_text)
        post = shlex.split(unit['ExecStartPost'][0])
        self.assertEqual(post[0], '/usr/bin/python3')
        self.assertEqual(post[-8:], ['--watchtower-compose', '/opt/watchtower/docker-compose.yaml',
                                    '--watchtower-service', 'watchtower',
                                    '--watchtower-since-file', '/run/mqtt-power-action/watchtower-started-at',
                                    '--watchtower-exit-code-file', '/run/mqtt-power-action/watchtower-exit-code'])
        self.assertEqual(unit['RuntimeDirectory'], ['mqtt-power-action'])
        self.assertEqual(shlex.split(unit['ExecStop'][0]),
                         ['/usr/bin/docker', 'compose', '-f', 'docker-compose.yaml', 'down'])
        self.assertEqual(unit['Type'], ['oneshot'])
        self.assertEqual(unit['RemainAfterExit'], ['no'])
        self.assertEqual(unit['TimeoutStartSec'], ['0'])
        self.assertEqual(unit['TimeoutStopSec'], ['120'])
        self.assertFalse((ROOT / 'run_watchtower_once.py').exists())

    def test_service_report_invocation_for_both_backends(self):
        """Run the post-start reporter with fake completed Compose status/logs for both mail configs."""
        unit, _ = self.service_settings()
        install_root = PurePosixPath('/opt/mqtt-power-action')
        ps = types.SimpleNamespace(returncode=0, stdout=json.dumps({'Service': 'watchtower', 'ExitCode': 0, 'State': 'exited'}))
        logs = types.SimpleNamespace(returncode=0, stdout=json.dumps({'msg': 'Session done', 'level': 'info', 'Scanned': 1, 'Updated': 0, 'Failed': 0}))
        for filename, backend in [('config-sendmail-none.example.ini', 'sendmail'), ('config-smtp.example.ini', 'smtp')]:
            with self.subTest(backend=backend):
                arguments = shlex.split(unit['ExecStartPost'][0])
                arguments[3] = arguments[3].replace('config-sendmail-none.example.ini', filename)
                local_args = [str(ROOT / PurePosixPath(arguments[1]).relative_to(install_root)),
                              '--config', str(ROOT / PurePosixPath(arguments[3]).relative_to(install_root))] + arguments[4:]
                with patch.object(sys, 'argv', local_args), \
                     patch.object(self.app, '_read_runtime_text', side_effect=[('2026-09-16T10:00:00+00:00', None), ('0', None)]), \
                     patch.object(self.app, 'publish_mqtt', return_value=(True, 'mock MQTT')) as publish, \
                     patch.object(self.app, 'send_mail', return_value=True) as mail, \
                     patch.object(self.app.subprocess, 'run', side_effect=[logs]) as docker, \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.app.main(), 0)
                publish.assert_called_once()
                mail.assert_not_called()  # Example configs are safe previews.
                self.assertEqual(docker.call_count, 1)
                cfg = publish.call_args.args[0]
                self.assertEqual(cfg.get('mail', 'backend'), backend)
                self.assertEqual(cfg.get('power', 'action'), 'none')
                self.assertEqual(cfg.watchtower_report['status'], 'success')

    def test_cli_parser(self):
        """Verify both config flags plus help/error exits with Paho import stubbed."""
        for flag in ['-c', '--config']:
            with patch.object(sys, 'argv', ['app', flag, 'config.ini']):
                self.assertEqual(self.app.parse_args().config, 'config.ini')
        for args, code in [(['--help'], 0), ([], 2), (['--invalid'], 2)]:
            with patch.object(sys, 'argv', ['app'] + args), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                self.app.parse_args()
            self.assertEqual(error.exception.code, code)


if __name__ == '__main__':
    unittest.main()
