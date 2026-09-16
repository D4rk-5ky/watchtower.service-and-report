# Verification — 0.0.9

Verification was performed on the packaged source tree without contacting a real MQTT broker, SMTP server, Docker daemon, Home Assistant instance, or issuing a real host power command.

## Completed checks

- `python3 -m unittest discover -s tests -v`
  - Result: **37 tests passed**.
  - Docker, MQTT, mail, and power operations are mocked.
  - Covers ordinary JSON/report validation, MQTT/mail/power safety gates, both mail backends, systemd command wiring, completed-Watchtower result inspection, failure/success reporting, HA success/failure branching, and shutdown-only-after-success behavior.
- `python3 -m py_compile mqtt_power_action_none.py tests/test_mqtt_reports.py tests/test_watchtower_flow.py`
  - Result: **passed**.
- YAML parsing with PyYAML for all three `HomeAssistant/*.yaml` files and `compose.example.yaml`.
  - Result: **passed**.
- INI parsing with `configparser` for both example configs.
  - Result: **passed**; each example contains **41 active options**.
- CLI help was executed with a temporary local Paho import stub because `paho-mqtt` is not installed in this build environment.
  - `--help` displayed all four flags/forms: `-h/--help`, `-c/--config`, `--watchtower-compose`, and `--watchtower-service`.
  - A missing config path exited with code **2** and a controlled `CONFIG ERROR`.
- `systemd-analyze verify ./watchtower.service` was attempted.
  - The checker reached the unit and reported environment/dependency errors because this build container does not have `docker.service` or `/usr/bin/docker`.
  - No unit syntax error was reported before those missing-environment failures.
- Static/unit tests verify the intended service phases exactly:
  - `ExecStartPre`: `docker compose ... pull watchtower`
  - `ExecStart`: `docker compose ... up --abort-on-container-exit --exit-code-from watchtower watchtower`
  - `ExecStartPost`: Python completed-job reporter
  - `ExecStop`: `docker compose ... down`
- Privacy/redaction scan across the full project tree found no prior local/private IPs, host/device/account labels, personal MQTT topic names, or non-placeholder email addresses.
- Final archive staging was checked for `__pycache__`, `.pyc`, `.pyo`, build cache, and temporary files before packaging.
- Final file-path manifest was compared with the supplied 0.0.8 project: all required previous project files remain present; none were silently dropped.

## What was not fully tested

- No real Watchtower container was run, so behavior against a live Docker/Compose/Watchtower installation remains to be confirmed on the target host.
- No real `docker compose ps --format json` output was collected from the target Docker Compose version. The parser is covered against object, array, and line-delimited JSON shapes in tests.
- No real MQTT broker, sendmail/Postfix installation, or SMTP provider was contacted.
- No Home Assistant automation was imported/executed in a live Home Assistant instance; YAML and Jinja-relevant control-flow pieces are checked offline.
- No real shutdown/reboot was performed.
- Native `systemd-analyze verify` could not complete successfully in the build container solely because Docker/systemd Docker service dependencies are absent there. Run it again on the target host after editing paths.

## Recommended target-host checks before enabling automation

```sh
sudo systemd-analyze verify /etc/systemd/system/watchtower.service
sudo systemctl daemon-reload
sudo systemctl start watchtower.service
sudo systemctl status watchtower.service
sudo journalctl -u watchtower.service -n 100 --no-pager
```

Confirm that the Watchtower Compose service emits JSON logs with exactly one `Session done` record and that Home Assistant receives either `status: success` or `status: failure` on the configured result topic before enabling automatic shutdown actions.
