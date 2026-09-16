# MQTT Power Action

`mqtt_power_action_none.py` can independently publish a structured MQTT JSON result, send email, and request a Linux shutdown or reboot. MQTT and mail are separate optional channels: either one, both, or neither can be enabled. The supplied Watchtower service uses the same reporter after systemd has finished the Watchtower Compose job.

## Safety

This project can publish MQTT commands, send mail, stop/recreate containers through Watchtower, and optionally call `systemctl poweroff` or `systemctl reboot`. Review the configuration, Home Assistant automations, and service paths before using it on a production machine. `dry_run = true` suppresses only the local power command. Any notification channel that is enabled still runs, and receiving MQTT automations may still take destructive actions.

## Requirements

- Python 3.10 or later.
- `paho-mqtt` only when `[mqtt] enabled = true`. MQTT-disabled configurations do not need Paho installed.
- Docker with the Compose plugin for the supplied Watchtower service flow.
- Local `sendmail`/Postfix or an SMTP account only when `[mail] enabled = true` and the selected mail event is enabled.
- Linux/systemd permissions if ordinary mode is allowed to shut down or reboot the host.

On Debian/Ubuntu, install Paho only if you will use MQTT:

```sh
sudo apt install python3-paho-mqtt
```

## Project layout

The examples use these generic installation paths; edit them to match your system:

```text
/opt/mqtt-power-action/
  mqtt_power_action_none.py
  compose.example.yaml
  systemd/
    watchtower.service
  configs/
    config-sendmail-none.example.ini
    config-smtp.example.ini
  HomeAssistant/
    watchtower-manual-update.yaml
```

The dedicated Watchtower Compose project is shown separately as `/opt/watchtower/docker-compose.yaml`.

All shipped Home Assistant/config examples are deliberately redacted and use placeholders such as `example-host`, `mqtt.example.invalid`, and `sender@example.com`. Replace them with your own values before use.

## The Watchtower systemd flow

The supplied `systemd/watchtower.service` intentionally keeps orchestration in systemd:

```text
ExecStartPre  -> docker compose pull watchtower
ExecStart     -> docker compose up --pull never ... --exit-code-from watchtower
                and records this invocation's Compose exit code
ExecStartPost -> mqtt_power_action_none.py reads only this invocation's logs
                 and reports through whichever MQTT/mail channels are enabled
ExecStop      -> docker compose down as the oneshot returns to stopped
```

`ExecStartPre` performs the only Watchtower image pull. `ExecStart` uses `--pull never`, records the actual Compose command exit code in `/run/mqtt-power-action/`, and deliberately returns control so `ExecStartPost` always runs. `ExecStartPost` is the final gate: it exits 0 only when the completed Watchtower job is verified successful and every **enabled** reporting channel that was attempted succeeds. Disabled channels are neutral. If MQTT and mail are both disabled, the verified Watchtower result alone controls the unit result.

The reporter does **not** start, pull, restart, or rerun Watchtower in this mode. In the systemd flow it reads the captured current-run exit code and calls `docker compose logs --since <this-run-start>` so logs from an older Watchtower container can never satisfy the success check. If the timestamp/exit-code marker is missing or invalid, the result fails closed instead of falling back to historical logs.

For strict verification, the Watchtower Compose service must keep one-shot/info logging enabled:

```yaml
WATCHTOWER_RUN_ONCE: "true"
WATCHTOWER_LOG_LEVEL: info
```

The reporter accepts both Watchtower JSON logs and the normal `Auto`/`LogFmt` console format used by Watchtower 1.7.1 on non-TTY Docker output. `WATCHTOWER_LOG_FORMAT: json` remains recommended in the supplied Compose example because it is the most deterministic format, but it is no longer required for successful verification.

A successful report requires all of the following from the **current service invocation**:

- the completed Compose service has exit code 0;
- exactly one valid Watchtower `Session done` record is present in JSON or LogFmt form;
- `Scanned`, `Updated`, and `Failed` are non-negative integers;
- `Updated <= Scanned`;
- `Failed == 0`;
- no error/fatal/panic log records are present;
- no `Unable to update container ...` record is present.

If the result cannot be verified, the job is treated as `failure` rather than guessing success. If MQTT is enabled, that failure is published as JSON; if mail failure reporting is enabled, it can also be emailed. Even with both channels disabled, `ExecStartPost` returns failure to systemd.


### Why the service uses one pull only

`ExecStartPre` already runs `docker compose ... pull watchtower`, so `ExecStart` explicitly uses `--pull never`. This prevents Compose from pulling the Watchtower image a second time during the same service run, even if the Compose file previously used `pull_policy: always`. The supplied Compose example therefore does not set `pull_policy: always`.

## Install the Watchtower service

Copy the project contents to your chosen install directory and edit `systemd/watchtower.service` so `WorkingDirectory`, the Python path, the config path, and the Compose path match your machine. Copy `compose.example.yaml` to the dedicated Watchtower directory and customize it.

Then install and verify the unit:

```sh
sudo install -m 644 systemd/watchtower.service /etc/systemd/system/watchtower.service
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/watchtower.service
sudo systemctl start watchtower.service
sudo systemctl status watchtower.service
sudo journalctl -u watchtower.service -n 100 --no-pager
```

Because `RemainAfterExit=no` is used, the one-shot does not remain `active (exited)`. After `ExecStartPost` finishes, systemd enters the stop phase, runs the existing `ExecStop=docker compose down`, and a successful run finishes as inactive/stopped. You can therefore run it again directly with:

```sh
sudo systemctl start watchtower.service
```

A failed report remains visible as a systemd `failed` result for diagnostics, but no Watchtower job is left running; `ExecStop` still tears down the dedicated Compose project during the stop path.

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
| `--watchtower-compose FILE` | Select completed-Watchtower report mode. The script inspects `FILE` with `docker compose ps/logs`, then uses whichever MQTT/mail channels are enabled; it does not start Docker. |
| `--watchtower-service NAME` | Compose service to inspect in report mode. Defaults to `watchtower`. |
| `cat VERSION` | Show the packaged application version. There is no separate `--version` flag. |

Without `--watchtower-compose`, the script runs ordinary mode: load the configuration, process MQTT if enabled, process mail if enabled for the outcome, wait only when a real power action follows, then run or dry-run the configured shutdown/reboot.

## Configuration

Both supplied INI examples contain the same 43 options. The sendmail example selects the local sendmail backend; the SMTP example selects SMTP. For the Watchtower systemd service, always keep `power.action = none`. When MQTT is enabled, also keep `mqtt.message = auto` and `mqtt.retain = false`.

| Section.option | Purpose |
| --- | --- |
| `server.hostname` | Friendly host label used in payloads/templates. Empty/missing falls back to the OS hostname. |
| `power.action` | `none`, `shutdown`, or `reboot`. Watchtower report mode requires `none`. |
| `power.delay_before_action` | Seconds before shutdown/reboot. Ignored for `none`. |
| `power.dry_run` | Suppresses only the local `systemctl` action. Enabled MQTT/mail channels still occur. |
| `power.continue_on_mqtt_fail` | Ordinary mode only: continue toward later power handling after an **enabled** MQTT channel fails. Ignored when MQTT is disabled. |
| `power.continue_on_mail_fail` | Ordinary mode only: continue toward power handling after an **enabled** success-mail attempt fails. Ignored when mail is disabled. |
| `mqtt.enabled` | Master MQTT switch. `true` enables validation/publishing; `false` skips MQTT completely, ignores its connection settings, and does not require `paho-mqtt`. If the whole `[mqtt]` section is omitted, MQTT is disabled. Existing configs with a `[mqtt]` section but no `enabled` option remain enabled for compatibility. |
| `mqtt.host` | MQTT broker host/IP; ignored when MQTT is disabled. |
| `mqtt.port` | MQTT broker port. |
| `mqtt.username` | Optional broker username. |
| `mqtt.password` | Optional direct MQTT password; takes precedence over `password_env`. |
| `mqtt.password_env` | Environment variable containing the MQTT password. |
| `mqtt.topic` | Publish topic; supports `{hostname}`, `{safe_hostname}`, `{action}`, `{event}`. The supplied Watchtower examples use one shared result topic for all hosts and identify the sender from the JSON `host` field. |
| `mqtt.message` | `auto` for generated JSON, or a custom JSON object template. When MQTT is enabled, Watchtower report mode requires `auto`/empty. Ignored when MQTT is disabled. |
| `mqtt.client_id` | `auto` or a template for the MQTT client ID. |
| `mqtt.qos` | MQTT QoS 0, 1, or 2. |
| `mqtt.retain` | MQTT retain flag. When MQTT is enabled, Watchtower report mode requires `false`. Ignored when MQTT is disabled. |
| `mqtt.connect_timeout` | Seconds to wait for the MQTT connect callback after the synchronous connect call returns. |
| `mqtt.publish_timeout` | Publish-confirmation wait where supported by the installed Paho version. |
| `report.status` | Ordinary mode job status: `success` or `failure`. In Watchtower report mode it is derived from the completed job. |
| `report.title` | Human-readable title. `auto` chooses a generated title; template placeholders are supported. |
| `report.exit_code` | Ordinary mode result code, or `auto`. Derived in Watchtower report mode. |
| `report.warning` | Ordinary mode non-fatal warning boolean. Derived in Watchtower report mode. |
| `report.error` | Ordinary mode error summary. Derived in Watchtower report mode. |
| `report.stderr` | Ordinary mode captured output/diagnostic text. Derived in Watchtower report mode. |
| `mail.enabled` | Master script-level email switch. `false` skips all mail and ignores backend/recipient/SMTP settings. If the whole `[mail]` section is omitted, mail is disabled. Existing configs with a `[mail]` section but no `enabled` option remain enabled for compatibility. |
| `mail.on_success` | Send success mail when mail is enabled and the applicable flow succeeds. |
| `mail.on_failure` | Send failure mail when mail is enabled and the applicable flow fails. |
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

### Optional output combinations

The two output channels are independent:

```ini
# MQTT only
[mqtt]
enabled = true

[mail]
enabled = false
```

```ini
# Mail only
[mqtt]
enabled = false

[mail]
enabled = true
```

```ini
# No external notification transport; Watchtower verification/systemd status still work
[mqtt]
enabled = false

[mail]
enabled = false
```

You may also omit an optional section entirely. An omitted `[mqtt]` or `[mail]` section is treated as disabled. This is intentionally different from older configs that already contain the section but lack the new `enabled` option: those remain enabled for backward compatibility.

When MQTT is disabled, broker host/topic/QoS/message settings are not validated and Paho is not imported as a hard requirement. When mail is disabled, recipient/backend/SMTP/sendmail settings are not validated or used. Disabled channels do not make a successful run fail.

### Automatic MQTT JSON

When MQTT is enabled, ordinary `message = auto` output has this shape:

```json
{"status":"success","title":"example-host: none","exit_code":0,"warning":false,"error":"","stderr":"","event":"success","host":"example-host"}
```

Watchtower report mode adds fields such as `compose_exit_code`, `scanned`, `updated`, `failed`, `failed_containers`, and `details_truncated`. The `status` field is always normalized to `success` or `failure` for the Home Assistant examples.

Known MQTT/SMTP passwords, URL credentials, and common `password=...`/`password:...` diagnostic text are redacted before Watchtower diagnostics are forwarded in MQTT/mail fields. Full Docker/service logs remain in the journal and should still be treated as sensitive.

## Home Assistant examples

When MQTT is enabled, the Watchtower examples use **one shared MQTT result topic** instead of making separate success/failure subscriptions or a separate result topic for every host. The automatic JSON payload already contains both `status` and `host`, so Home Assistant can decide what happened after receiving the message.

With the supplied examples every Watchtower host publishes to:

```text
homeassistant/watchtower/status
```

A typical received payload contains the identifying fields directly in JSON:

```json
{"status":"success","host":"example-host","title":"example-host: none","exit_code":0,"warning":false}
```

`HomeAssistant/watchtower-manual-update.yaml` demonstrates the intended control flow:

1. Optionally wake a generic example host and wait for stable readiness.
2. Publish `start_watchtower` to that host's listener topic.
3. Wait with **one MQTT trigger** on the shared `homeassistant/watchtower/status` topic.
4. Match only the expected host using `value_json.host`.
5. Read `wait.trigger.payload_json.status` after the message arrives.
6. Continue to shutdown only when the received status is exactly `success`.
7. On `failure`, unknown status, or timeout, notify and leave the machine on.

There is no separate MQTT trigger for success and failure. One result message wakes the automation and the later template decides which branch to take. The example uses `mode: restart`, so starting it again while a previous run is still active replaces that older run instead of being rejected.

You may choose a different MQTT result topic. The important requirement is simply that the publisher config and the Home Assistant trigger use the same topic. For a shared topic, keep a stable unique `[server] hostname` on each machine so the `host` field can identify the source.

## Exit behavior

In ordinary mode, configuration errors exit 2. Failures from enabled MQTT/mail channels and power actions return non-zero according to the existing safety gates and underlying power command where applicable. Disabled channels are successful no-ops and cannot block the power path.

In Watchtower report mode, configuration errors still exit 2. The post-start reporter returns 0 only when the Watchtower result is verified successful and every enabled notification channel that was attempted succeeds; otherwise it returns 1. With both MQTT and mail disabled, the verified Watchtower result alone determines 0/1. This is what allows `ExecStartPost` to make the systemd unit succeed or fail after an unsuccessful Watchtower run even when no external notification channel is enabled.

## Tests

Offline tests use mocked Docker, MQTT, mail, and power operations:

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile mqtt_power_action_none.py tests/test_mqtt_reports.py tests/test_watchtower_flow.py
```

See `VERIFICATION.md` for the checks run for this packaged version.
