# MQTT Power Action

`mqtt_power_action_none.py` publishes a structured MQTT JSON result, can optionally send email, and can optionally request a Linux shutdown or reboot. The supplied Watchtower service uses the same reporter in notification-only mode after systemd has finished the Watchtower Compose job.

## Safety

This project can publish MQTT commands, send mail, stop/recreate containers through Watchtower, and optionally call `systemctl poweroff` or `systemctl reboot`. Review the configuration, Home Assistant automations, and service paths before using it on a production machine. `dry_run = true` suppresses only the local power command; MQTT and mail still run and receiving automations may still take destructive actions.

## Requirements

- Python 3.10 or later.
- `paho-mqtt` for MQTT publishing.
- Docker with the Compose plugin for the supplied Watchtower service flow.
- Optional local `sendmail`/Postfix or an SMTP account for email.
- Linux/systemd permissions if ordinary mode is allowed to shut down or reboot the host.

On Debian/Ubuntu:

```sh
sudo apt install python3-paho-mqtt
```

## Project layout

The examples use these generic installation paths; edit them to match your system:

```text
/opt/mqtt-power-action/
  mqtt_power_action_none.py
  watchtower.service
  compose.example.yaml
  configs/
    config-sendmail-none.example.ini
    config-smtp.example.ini
  HomeAssistant/
    watchtower-manual-update.yaml
    home-assistant-automation.yaml
    syncerate-all-servers.yaml
```

The dedicated Watchtower Compose project is shown separately as `/opt/watchtower/docker-compose.yaml`.

All shipped Home Assistant/config examples are deliberately redacted and use placeholders such as `example-host`, `mqtt.example.invalid`, and `sender@example.com`. Replace them with your own values before use.

## The Watchtower systemd flow

The supplied `watchtower.service` intentionally keeps orchestration in systemd:

```text
ExecStartPre  -> docker compose pull watchtower
ExecStart     -> docker compose up ... --exit-code-from watchtower
ExecStartPost -> mqtt_power_action_none.py reads the completed service status/logs
                 and publishes one JSON success/failure result
ExecStop      -> docker compose down
```

`ExecStartPre` and `ExecStart` use systemd's leading `-` command prefix so a non-zero Docker/Watchtower exit does not prevent `ExecStartPost` from running. `ExecStartPost` is the final gate: it exits 0 only when the completed Watchtower job is verified successful and required reporting succeeds; otherwise it exits 1 so the unit is failed.

The reporter does **not** start, pull, restart, or rerun Watchtower in this mode. It only runs `docker compose ps` and `docker compose logs` against the already-completed job.

For strict verification, the Watchtower Compose service must keep:

```yaml
WATCHTOWER_RUN_ONCE: "true"
WATCHTOWER_LOG_FORMAT: json
WATCHTOWER_LOG_LEVEL: info
```

A successful report requires all of the following:

- the completed Compose service has exit code 0;
- exactly one valid Watchtower `Session done` JSON record is present;
- `Scanned`, `Updated`, and `Failed` are non-negative integers;
- `Updated <= Scanned`;
- `Failed == 0`;
- no error/fatal/panic log records are present;
- no `Unable to update container ...` record is present.

If the result cannot be verified, the MQTT report is `failure` rather than guessing success.

## Install the Watchtower service

Copy the project contents to your chosen install directory and edit `watchtower.service` so `WorkingDirectory`, the Python path, the config path, and the Compose path match your machine. Copy `compose.example.yaml` to the dedicated Watchtower directory and customize it.

Then install and verify the unit:

```sh
sudo install -m 644 watchtower.service /etc/systemd/system/watchtower.service
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/watchtower.service
sudo systemctl start watchtower.service
sudo systemctl status watchtower.service
sudo journalctl -u watchtower.service -n 100 --no-pager
```

Because `RemainAfterExit=yes` is enabled, repeat runs should normally use:

```sh
sudo systemctl restart watchtower.service
```

Stopping/restarting the service runs the supplied `docker compose down` for that dedicated Compose project.

## CLI commands and flags

```sh
python3 mqtt_power_action_none.py --help
python3 mqtt_power_action_none.py -c /path/to/config.ini
python3 mqtt_power_action_none.py --config /path/to/config.ini
python3 mqtt_power_action_none.py -c /path/to/config.ini \
  --watchtower-compose /opt/watchtower/docker-compose.yaml \
  --watchtower-service watchtower
cat VERSION
```

| Flag/command | Meaning |
| --- | --- |
| `-h`, `--help` | Show argparse help and exit. |
| `-c PATH`, `--config PATH` | Required INI configuration path. The short and long forms are equivalent. |
| `--watchtower-compose FILE` | Select completed-Watchtower report mode. The script inspects `FILE` with `docker compose ps/logs`; it does not start Docker. |
| `--watchtower-service NAME` | Compose service to inspect in report mode. Defaults to `watchtower`. |
| `cat VERSION` | Show the packaged application version. There is no separate `--version` flag. |

Without `--watchtower-compose`, the script runs ordinary report mode: load the configured result, publish MQTT, optionally send mail, wait only when a real power action follows, then run or dry-run the configured shutdown/reboot.

## Configuration

Both supplied INI examples contain the same 41 options. The sendmail example selects the local sendmail backend; the SMTP example selects SMTP. For the Watchtower systemd service, keep `power.action = none`, `mqtt.message = auto`, and `mqtt.retain = false`.

| Section.option | Purpose |
| --- | --- |
| `server.hostname` | Friendly host label used in payloads/templates. Empty/missing falls back to the OS hostname. |
| `power.action` | `none`, `shutdown`, or `reboot`. Watchtower report mode requires `none`. |
| `power.delay_before_action` | Seconds before shutdown/reboot. Ignored for `none`. |
| `power.dry_run` | Suppresses only the local `systemctl` action. MQTT/mail still occur. |
| `power.continue_on_mqtt_fail` | Ordinary mode only: continue toward later power handling after MQTT failure. |
| `power.continue_on_mail_fail` | Ordinary mode only: continue toward power handling after success-mail failure. |
| `mqtt.host` | MQTT broker host/IP. |
| `mqtt.port` | MQTT broker port. |
| `mqtt.username` | Optional broker username. |
| `mqtt.password` | Optional direct MQTT password; takes precedence over `password_env`. |
| `mqtt.password_env` | Environment variable containing the MQTT password. |
| `mqtt.topic` | Publish topic; supports `{hostname}`, `{safe_hostname}`, `{action}`, `{event}`. |
| `mqtt.message` | `auto` for generated JSON, or a custom JSON object template. Watchtower report mode requires `auto`/empty. |
| `mqtt.client_id` | `auto` or a template for the MQTT client ID. |
| `mqtt.qos` | MQTT QoS 0, 1, or 2. |
| `mqtt.retain` | MQTT retain flag. Watchtower report mode requires `false`. |
| `mqtt.connect_timeout` | Seconds to wait for the MQTT connect callback after the synchronous connect call returns. |
| `mqtt.publish_timeout` | Publish-confirmation wait where supported by the installed Paho version. |
| `report.status` | Ordinary mode job status: `success` or `failure`. In Watchtower report mode it is derived from the completed job. |
| `report.title` | Human-readable title. `auto` chooses a generated title; template placeholders are supported. |
| `report.exit_code` | Ordinary mode result code, or `auto`. Derived in Watchtower report mode. |
| `report.warning` | Ordinary mode non-fatal warning boolean. Derived in Watchtower report mode. |
| `report.error` | Ordinary mode error summary. Derived in Watchtower report mode. |
| `report.stderr` | Ordinary mode captured output/diagnostic text. Derived in Watchtower report mode. |
| `mail.on_success` | Send success mail when the applicable flow succeeds. |
| `mail.on_failure` | Send failure mail when the applicable flow fails. |
| `mail.backend` | `sendmail` or `smtp`. |
| `mail.to` | Recipient address; required when mail is enabled. |
| `mail.from` | Sender address. |
| `mail.success_subject` | Success subject template. |
| `mail.failure_subject` | Failure subject template. |
| `mail.extra_body` | Static extra body text. |
| `sendmail.path` | Optional explicit sendmail executable; empty auto-detects common paths/PATH. |
| `smtp.host` | SMTP server. |
| `smtp.port` | SMTP port. |
| `smtp.username` | SMTP login username; also fallback sender when `mail.from` is empty. |
| `smtp.password` | Direct SMTP password; takes precedence over `password_env`. |
| `smtp.password_env` | Environment variable containing the SMTP password. |
| `smtp.ssl` | Use implicit TLS immediately. Takes precedence over STARTTLS. |
| `smtp.starttls` | Upgrade a plain SMTP connection with STARTTLS. |
| `smtp.timeout` | SMTP socket timeout in seconds. |

### Automatic MQTT JSON

Ordinary `message = auto` output has this shape:

```json
{"status":"success","title":"example-host: none","exit_code":0,"warning":false,"error":"","stderr":"","event":"success","host":"example-host"}
```

Watchtower report mode adds fields such as `compose_exit_code`, `scanned`, `updated`, `failed`, `failed_containers`, and `details_truncated`. The `status` field is always normalized to `success` or `failure` for the Home Assistant examples.

Known MQTT/SMTP passwords, URL credentials, and common `password=...`/`password:...` diagnostic text are redacted before Watchtower diagnostics are forwarded in MQTT/mail fields. Full Docker/service logs remain in the journal and should still be treated as sensitive.

## Home Assistant examples

`HomeAssistant/watchtower-manual-update.yaml` demonstrates the intended control flow:

1. Optionally wake a generic example host and wait for stable readiness.
2. Publish `start_watchtower` to the example listener topic.
3. Wait for JSON on `homeassistant/watchtower/example-host/status`.
4. Continue to shutdown only when `status == "success"`.
5. On `failure` or timeout, notify and leave the machine on.

`HomeAssistant/syncerate-all-servers.yaml` is a generic multi-topic JSON consumer showing how to branch on `success`, `failure`, or unknown status. `HomeAssistant/home-assistant-automation.yaml` is a redacted chained-job example. Replace every example entity/topic/action before importing into a real Home Assistant instance.

## Exit behavior

In ordinary mode, configuration errors exit 2. MQTT/mail/power failures return non-zero according to the existing safety gates and underlying power command where applicable.

In Watchtower report mode, configuration errors still exit 2. The post-start reporter returns 0 only when the Watchtower result is verified successful and required notification delivery succeeds; otherwise it returns 1. This is what allows `ExecStartPost` to make the systemd unit succeed or fail while still publishing a failure report after an unsuccessful Watchtower run.

## Tests

Offline tests use mocked Docker, MQTT, mail, and power operations:

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile mqtt_power_action_none.py tests/test_mqtt_reports.py tests/test_watchtower_flow.py
```

See `VERIFICATION.md` for the checks run for this packaged version.
