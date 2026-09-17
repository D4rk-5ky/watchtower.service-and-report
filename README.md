# Watchtower service and MQTT reports

Run Watchtower once through systemd, verify its completed result, and publish JSON that Home Assistant can handle like Syncerate's JSON status messages. MQTT and email are independently optional. The Python reporter inspects Docker; it does not start the update itself.

## Requirements

- Python 3.10+; Docker Engine and the Docker Compose plugin on the target Linux host.
- `paho-mqtt` when actually publishing MQTT (`sudo apt install python3-paho-mqtt` on Debian/Ubuntu).
- Local sendmail/Postfix or an SMTP account when sending email.
- Home Assistant's MQTT integration and your existing MQTT command listener for the daily chain.

## JonsBo daily chain

Use `HomeAssistant/jonsbo-daily-with-watchtower.yaml` as the replacement for your daily automation:

1. AsusN14E backup succeeds → start RPI5 backup.
2. RPI5 backup succeeds → start SnapBeforeWatchTower cleanup.
3. SnapBeforeWatchTower cleanup succeeds → start CleanUpInSyncoidSnapshots.
4. CleanUpIn succeeds → send `start_watchtower`.
5. A successful completed Watchtower report → send `shutdown_delay`.

The new Watchtower result subscription is:

```text
homeassistant/watchtower/jonsbo-n3-cwwk-n355/status
```

Watchtower must report `host=JonsBo-N3-CWWK-N355`, `job=watchtower`, `phase=completed`, `status=success`, `success=true`, and numeric `exit_code=0` before shutdown is allowed. Dry-run reports are ignored. Failure, unknown status, another host/job, or an uncompleted result cannot authorize shutdown. If no result arrives, this event-driven chain sends no shutdown; it has no additional missing-report timer.

The scheduled start, Monday restriction, entities, existing backup topics, and command listener topic from the supplied automation remain in the new example. Despite its daily title, the supplied schedule is Monday only. Its readiness loop permits 60 × 15 seconds (about 15 minutes). No live Home Assistant configuration is installed by this package.

Replace the existing automation instead of enabling both copies. Your **external MQTT listener** must map `start_watchtower` on `homeassistant/mqtt-listener/jonsbo-n3-cwwk-n355` to `systemctl start watchtower.service`. This project does not implement that listener or `shutdown_delay`. Keep unrelated power readiness messages on their own topic.

Use `configs/config-jonsbo-watchtower.example.ini` for this flow. It contains every available option, enables real MQTT reporting (`dry_run=false`), disables email, and uses `action=none`. Set its broker address and credentials before starting. Select this config filename in the service's `ExecStartPost` line.

The original `HomeAssistant/home-assistant-automation.yaml` and `syncerate-all-servers.yaml` remain as supplied references. The generic `watchtower-manual-update.yaml` is an alternative shared-topic workflow; customize its host, entities, command topic, and shutdown script if using it. Its result topic is `homeassistant/watchtower/status`, matching the generic INI examples.

## Install and run

Copy the project to `/opt/mqtt-power-action`. Put the dedicated Compose example at `/opt/watchtower/docker-compose.yaml`, then edit its settings. The optional Watchtower-native email settings require their environment password; remove that optional email block if unused. Watchtower-native email is separate from the Python reporter's email.

Choose and edit one INI file. INI parsing is strict and UTF-8: every section and every option may appear only once. A duplicate such as two `publish_dry_run` entries is rejected instead of silently choosing one value; the error names the duplicate and line without echoing the configured value.

In `systemd/watchtower.service`, set the actual `WorkingDirectory`, Compose path, Python path, and config path. `WorkingDirectory=` is a systemd directive on its own line; it is **not** part of the value passed to `--watchtower-compose`. The argument must be only the YAML path, for example `--watchtower-compose /Storage/WatchTower/docker-compose.yaml`, not `--watchtower-compose WorkingDirectory=/Storage/WatchTower/docker-compose.yaml`. For JonsBo, replace `config-sendmail-none.example.ini` in `ExecStartPost` with `config-jonsbo-watchtower.example.ini`. The root `watchtower.service` contains the same unit for compatibility; use the copy under `systemd/` as the installation source.

```sh
sudo install -m 644 systemd/watchtower.service /etc/systemd/system/watchtower.service
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/watchtower.service
sudo systemctl start watchtower.service
sudo systemctl status watchtower.service
sudo journalctl -u watchtower.service -n 100 --no-pager
```

`install` copies the configured unit; `daemon-reload` loads it; `systemd-analyze verify` checks unit wiring; `start` runs one update; `status` and `journalctl` show the result and diagnostics. A successful oneshot returns inactive (`RemainAfterExit=no`), allowing another `start`. `sudo systemctl stop watchtower.service` requests a stop. The configured `ExecStop` runs `docker compose down` for this dedicated project during normal teardown. systemd may skip `ExecStop` if startup/post-start fails; inspect Docker state after a failed unit. Do not place unrelated services in this dedicated Compose project.

The service resets runtime markers, records its start time, pulls Watchtower once, runs Compose with `--pull never`, and captures that invocation's exit code. Its post-start reporter reads the captured code and logs with `--since` using the start marker. A failed image pull permits trying the existing local image; the final run result controls reporting.

Keep `WATCHTOWER_RUN_ONCE: "true"` and info-level logs enabled. JSON logging is recommended; LogFmt/Auto output is also accepted. Verified success requires exit code zero, exactly one `Session done` record, nonnegative integer counters, consistent counts, zero failed updates, and no error/fatal/panic or `Unable to update container` records. Missing, malformed, duplicate, or unverifiable data means failure. A warning can accompany success.

## CLI

```sh
python3 mqtt_power_action_none.py --help
python3 mqtt_power_action_none.py --version
python3 mqtt_power_action_none.py -c configs/config-sendmail-none.example.ini
python3 mqtt_power_action_none.py --config /path/config.ini \
  --watchtower-compose /opt/watchtower/docker-compose.yaml \
  --watchtower-service watchtower \
  --watchtower-since-file /run/mqtt-power-action/watchtower-started-at \
  --watchtower-exit-code-file /run/mqtt-power-action/watchtower-exit-code
```

| Flag | Meaning |
| --- | --- |
| `-h`, `--help` | List public flags and exit without loading a config. |
| `--version` | Print the application version and exit. `cat VERSION` reads the same packaged version. |
| `-c PATH`, `--config PATH` | Required UTF-8 INI path for an actual run; no default file is assumed. Duplicate sections/options are rejected with a line-specific error. |
| `--watchtower-compose FILE` | Inspect an already-completed job from this Compose file. Pass the YAML path only; do not prefix it with `WorkingDirectory=`. Never starts/pulls containers. Requires `power.action=none`; enabled MQTT requires automatic, non-retained JSON. |
| `--watchtower-service NAME` | Compose service name to inspect; default `watchtower`. Requires Watchtower mode when overridden. |
| `--watchtower-since-file FILE` | File containing this invocation's timezone-aware ISO-8601 start timestamp. Must accompany the exit-code marker. Invalid/missing markers fail closed without reading historical logs. |
| `--watchtower-exit-code-file FILE` | File containing this invocation's integer Compose exit code (0–255). Must accompany the start marker. |

Omitting both marker flags permits manual inspection using `docker compose ps --all --format json` and container logs. This fallback cannot establish that historical logs belong to a newly requested run; use the service with both markers for automation. Each Docker inspection command has a 30-second timeout.

Without `--watchtower-compose`, ordinary mode reports a caller-supplied result or readiness before an optional local power action. It cannot verify a Watchtower update. It sends readiness mail first, publishes MQTT, then waits and requests power if configured. Its success means readiness or a supplied result, **not completed shutdown/reboot**. Never use ordinary mode to authorize the JonsBo Watchtower step.

The internal `--mqtt-publish` switch is used only by the parent script with a private JSON request on stdin. It is not a user reporting command.

## Dry-run notification options

Both generic INI examples start with `power.dry_run=true`. A dry run never runs local power commands or the power delay. Notifications default off, and can be independently opted in:

```ini
[power]
action = none
dry_run = true

[mqtt]
enabled = true
publish_dry_run = true
# Keep the remaining broker options from a complete example.
topic = test/watchtower/status

[mail]
enabled = true
send_dry_run = true
on_success = true
on_failure = true
# Keep the remaining backend/account options from a complete example.
```

`publish_dry_run` and `send_dry_run` each default to `false`; a disabled channel stays disabled regardless of its preview option. Opted-in notifications are real. MQTT previews include `dry_run=true` and `phase=dry_run`; email subjects start with `[DRY-RUN]`. The JonsBo example ignores previews. Use a test topic when testing other consumers that do not check `dry_run`.

`dry_run` controls the Python reporter, not Docker/systemd or Watchtower-native email. Starting `watchtower.service` still performs actual container updates. To preview reports, invoke the Python reporter directly against an already-completed job. Set `dry_run=false` for production reporting; keeping `action=none` prevents all local power commands.

## Configuration reference

All three INI examples contain the same 48 options. The files are read as UTF-8 with strict duplicate detection: each section and option may occur only once. MQTT and mail are disabled if their whole section is omitted. An existing section without `enabled` remains enabled for compatibility. Settings for a disabled transport are ignored. Paho is loaded only inside the publishing worker.

Templates support `{hostname}`, `{safe_hostname}`, `{action}`, and `{event}`. `safe_hostname` is normalized for IDs; `event` is `success` for `none`, `server_shutdown` for shutdown, or `server_reboot` for reboot. Use double literal braces in custom JSON templates. Prefer `message=auto` for safe escaping.

| Setting | Meaning/default |
| --- | --- |
| `server.hostname` | Friendly host; empty/missing uses the OS hostname. |
| `power.action` | Required: `none`, `shutdown`, or `reboot`. Watchtower mode requires `none`. |
| `power.delay_before_action` | Finite nonnegative seconds; default 1. Skipped for `none` and all dry runs. |
| `power.dry_run` | Preview notifications and suppress local power; default false. Generic examples explicitly set true. |
| `power.continue_on_mqtt_fail` | Ordinary mode only: allow power after failed MQTT; default false. Cannot override Watchtower failure. |
| `power.continue_on_mail_fail` | Ordinary mode only: allow power after failed readiness mail; default false. Cannot override Watchtower failure. |
| `mqtt.enabled` | Enable MQTT, subject to dry-run opt-in. |
| `mqtt.host` | Required broker hostname/IP when MQTT is enabled. |
| `mqtt.port` | Port 1–65535; default 1883. MQTT TLS is not implemented. |
| `mqtt.username` | Optional username; empty means no authentication. |
| `mqtt.password` | Direct password, taking precedence over `password_env`. |
| `mqtt.password_env` | Environment variable containing the password when direct password is empty. |
| `mqtt.topic` | Required publish topic; supports templates. No wildcards, NUL, or overlong topics. Must match HA subscription. |
| `mqtt.message` | `auto`/empty generates JSON. Ordinary-mode custom templates must produce a JSON object with success/failure status and valid field types. Watchtower mode requires auto. Failure and preview reports force generated JSON. |
| `mqtt.client_id` | `auto` generates `mqtt-power-action-{safe_hostname}`; custom templates supported. |
| `mqtt.qos` | 0: at most once; 1: at least once; 2: protocol exactly once. Default 1. QoS does not provide application-level deduplication. |
| `mqtt.retain` | Must be false. Result messages are events, not retained state. |
| `mqtt.timeout` | Positive finite overall worker timeout, covering DNS, connect and publish. Examples use 20 seconds. |
| `mqtt.connect_timeout` | Positive finite legacy component (default 10 seconds), added to `publish_timeout` when `timeout` is omitted. |
| `mqtt.publish_timeout` | Positive finite legacy component (default 10 seconds). Not a separate timer when `timeout` is set. |
| `mqtt.publish_dry_run` | Send real MQTT in preview; default false. Master switch must also be enabled. |
| `report.status` | Ordinary result `success`/`failure`, default success. Used to choose the default exit code. |
| `report.title` | `auto`/empty generates hostname plus Watchtower/action; custom templates allowed. Also used as `name`. |
| `report.job` | Ordinary job identifier; default `mqtt-power-action`. Watchtower always uses `watchtower`. |
| `report.comment` | Optional static context in automatic JSON. |
| `report.exit_code` | Ordinary integer result or `auto`: 0 for success, 1 for failure. Explicit zero implies success; nonzero implies failure. |
| `report.warning` | Ordinary nonfatal warning boolean; default false. |
| `report.error` | Ordinary plain-text error summary. |
| `report.stderr` | Ordinary captured output; bounded to its final 4,000 characters. |
| `mail.enabled` | Enable script email, subject to the event and preview switches. |
| `mail.send_dry_run` | Send real email in preview; default false. |
| `mail.on_success` | Send success/readiness mail; default false. |
| `mail.on_failure` | Send failure mail; default false. |
| `mail.backend` | `sendmail` (default) or `smtp`. |
| `mail.to` | Recipient; required when a mail event is enabled. |
| `mail.from` | Sender; falls back to SMTP username or `root@hostname`. |
| `mail.success_subject` | Success subject template. |
| `mail.failure_subject` | Failure subject template. |
| `mail.extra_body` | Static text appended to the email. |
| `sendmail.path` | Explicit executable, or auto-detect common system paths/PATH. |
| `smtp.host` | SMTP server; default `smtp.gmail.com`; examples use a placeholder. |
| `smtp.port` | SMTP port; default 587, commonly 465 with implicit TLS. |
| `smtp.username` | Required login for enabled SMTP mail. |
| `smtp.password` | Direct SMTP password, taking precedence over its environment source. |
| `smtp.password_env` | Name of the environment variable containing the SMTP password. |
| `smtp.ssl` | Implicit TLS; default false; takes precedence over STARTTLS. |
| `smtp.starttls` | Upgrade SMTP with TLS; default true. |
| `smtp.timeout` | Positive finite socket timeout; default 20 seconds. |

Watchtower derives status, success, exit code, warnings, errors, and output from inspection, regardless of configured ordinary outcome values. Mail includes the generated result. Known configured secrets and common credential patterns are redacted from forwarded Watchtower diagnostics; raw Docker logs stay on the host.

## MQTT payload

The common keys match Syncerate's JSON status channel, with a Watchtower identity and additional diagnostics:

```json
{"status":"success","success":true,"title":"JonsBo N3 - Watchtower","name":"JonsBo N3 - Watchtower","job":"watchtower","exit_code":0,"error":"","stderr":"","warning":false,"skipped_datasets":[],"host":"JonsBo-N3-CWWK-N355","dry_run":false,"phase":"completed","scanned":5,"updated":2,"failed":0}
```

`skipped_datasets` is empty because this job updates containers, not datasets. Additional fields include a UTC `timestamp`, `version`, `event`, `action`, `command`, `comment`, `message`, `compose_exit_code`, `failed_containers`, and `details_truncated`. Failure payloads use `status=failure`, `success=false`, a nonzero result code, and error/output text. Diagnostics are bounded to 4,000 output characters and 20 failed-container entries.

There is one final MQTT publish attempt per Watchtower inspection. Both success and failure use the same topic, with retention disabled. MQTT delivery failure cannot change a failed job to success, and an unreachable broker cannot receive its own failure notification. The local exit status/journal still records delivery failure. The status describes the update, not whether later email was delivered. The workflow does not implement request IDs or duplicate-event suppression; do not replay completion messages into its production topic.

The shared fields come from the supplied Syncerate source. See also the [Home Assistant MQTT trigger documentation](https://www.home-assistant.io/docs/automation/trigger/#mqtt-trigger) and [Watchtower arguments](https://containrrr.dev/watchtower/arguments/) for upstream trigger/logging options.

## Exit codes and checks

Watchtower mode returns 0 only for a verified successful job and successful attempted notification channels; otherwise 1. Disabled/suppressed channels are neutral. Invalid configuration/CLI use returns 2. Ordinary mode returns 1 on blocked notification errors, a failed systemctl exit code on power errors, or 130 on an interrupted power phase. Ordinary caller-supplied report status does not itself authorize/block power: use `action=none` for reporting jobs.

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile mqtt_power_action_none.py tests/test_mqtt_reports.py tests/test_watchtower_flow.py tests/test_syncerate_compatibility.py
```

Install PyYAML and Jinja2 in your test environment to run YAML/template checks; otherwise those checks are skipped. Tests mock Docker, MQTT, mail, and power. Compile checks only validate Python syntax. See `VERIFICATION.md` for the packaged verification results, `commented_code_map.md` for each function/command, and `MANIFEST.json` for file hashes and original-archive accounting.
