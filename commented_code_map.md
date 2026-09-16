# Commented Code Map

This file maps the current 0.0.15 code and operational commands. It describes what each function/command does and why it exists.

## Project files

| File | Purpose |
| --- | --- |
| `mqtt_power_action_none.py` | Main optional-MQTT/optional-mail/power reporter plus completed-Watchtower result inspection. |
| `systemd/watchtower.service` | Keeps Watchtower lifecycle in systemd: pull, run/wait, post-run reporting, teardown. |
| `compose.example.yaml` | Redacted one-shot Watchtower Compose example with recommended JSON/info logging; the parser also accepts default Auto/LogFmt output. |
| `configs/config-sendmail-none.example.ini` | Complete 43-option example using local sendmail and no local power action. |
| `configs/config-smtp.example.ini` | Complete 43-option example using SMTP and no local power action. |
| `HomeAssistant/watchtower-manual-update.yaml` | Redacted one-host workflow that waits on one shared result-topic trigger, filters by JSON `host`, reads JSON `status`, and shuts down only after success. |
| `tests/test_mqtt_reports.py` | Offline report/config/mail/power/systemd wiring regressions. |
| `tests/test_watchtower_flow.py` | Offline Watchtower result parsing and HA flow regressions. |
| `README.md` | Current usage only. |
| `VERSIONING.md` | Version-by-version change history. |
| `VERIFICATION.md` | Checks performed for the current package. |
| `MANIFEST.json` | File sizes/hashes and previous-release accounting. |
| `VERSION` | Current package version. |

## `mqtt_power_action_none.py` functions

| Function | What it does | Why it exists |
| --- | --- | --- |
| `config_error(message)` | Prints a consistent configuration error and exits 2. | Keeps invalid configuration failures predictable and prevents unsafe partial execution. |
| `get_str(config, section, option, default, required)` | Reads/strips string settings with required/default handling. | Centralizes repeated INI lookup rules. |
| `get_int(...)` | Reads a setting through `get_str` and converts it to integer. | Reuses common validation for ports, QoS, and integer fields. |
| `get_float(...)` | Reads a setting and converts it to float. | Supports timeouts/delays without duplicating parsing code. |
| `get_bool(...)` | Reads configparser-compatible booleans. | Normalizes true/false option handling. |
| `feature_enabled(config, section)` | Treats an explicit `enabled` boolean as the master switch; an omitted optional section is disabled, while an existing legacy section without `enabled` remains enabled. | Makes MQTT and mail independently optional without breaking older configs. |
| `get_password(value, env_var)` | Uses a direct password first, otherwise reads the named environment variable. | Supports secrets outside the INI while preserving explicit override behavior. |
| `get_config_hostname(config)` | Uses `[server] hostname`, falling back to `socket.gethostname()`. | Gives reports/templates a stable friendly host label. |
| `make_safe_id(value)` | Lowercases and replaces unsupported client-ID characters. | Prevents awkward/special hostname characters from producing unsafe MQTT client IDs. |
| `get_event_name_for_action(action)` | Maps `shutdown`, `reboot`, `none` to report event names. | Preserves the original event contract independently of job `status`. |
| `render_template(value, config)` | Expands `{hostname}`, `{safe_hostname}`, `{action}`, `{event}`. | Reuses one controlled template mechanism for topics, client IDs, subjects, and custom payloads. |
| `encode_mqtt_report(report)` | Validates required JSON object/status and known field types, then emits compact strict JSON. | Prevents malformed payloads from reaching Home Assistant. |
| `build_mqtt_message(config, force_auto=False)` | Builds auto/custom ordinary reports, or encodes the runtime Watchtower result. `force_auto=True` ignores an unused MQTT custom template for mail-only reporting. | Reuses one validated result serializer while keeping mail-only mode independent of MQTT configuration. |
| `get_mqtt_client_id(config)` | Builds automatic hostname-based client IDs or renders a configured template. | Keeps MQTT identity configurable without duplicating template logic. |
| `load_config(path)` | Loads the INI, always validates the power action, and validates MQTT or mail settings only when that channel is enabled. MQTT-enabled mode also checks that Paho is installed. | Rejects relevant configuration problems before side effects without letting disabled features break a run. |
| `make_mqtt_client(client_id)` | Creates Paho v2 client with a v1 fallback. | Keeps compatibility with both commonly deployed Paho APIs. |
| `reason_code_to_int(reason_code)` | Normalizes different Paho callback result representations to an integer. | Makes connection success/failure checks version-independent. |
| `wait_for_publish_compatible(info, timeout)` | Uses timeout-aware publish waiting when available and the older fallback otherwise. | Preserves compatibility across Paho versions. |
| `publish_mqtt(config)` | Returns a successful no-op when MQTT is disabled; otherwise connects, authenticates, publishes JSON, waits for confirmation, and returns `(ok, details)`. | Keeps MQTT optional and contains all transport handling in one reusable function. |
| nested `on_connect(...)` | Stores the broker connection result and releases the waiting thread. | Lets synchronous main flow safely wait for Paho's asynchronous connect callback. |
| `find_sendmail(path)` | Uses configured executable or searches common sendmail locations/PATH. | Supports local MTA delivery without shell command construction. |
| `build_mail_message(config, mail_type, details)` | Builds email headers/body and includes the result JSON. In mail-only mode it forces automatic result generation and labels MQTT as disabled. | Keeps email useful without making it depend on MQTT settings. |
| `send_mail_sendmail(config, msg, mail_type)` | Sends message bytes to `sendmail -t`. | Provides local-MTA delivery without shell interpolation. |
| `send_mail_smtp(config, msg, mail_type)` | Handles SMTP/SMTP_SSL, optional STARTTLS, login, and send. | Provides direct authenticated SMTP delivery. |
| `send_mail(config, mail_type, details)` | Returns a successful no-op when mail is disabled; otherwise builds a message and routes it to sendmail or SMTP. | Makes mail independently optional while keeping backend selection out of main flow. |
| `run_power_action(config)` | Performs/dry-runs `systemctl poweroff` or `systemctl reboot`, or no-ops for `none`. | Centralizes the dangerous local power action behind configuration safety checks. |
| `redact_watchtower_text(text, config)` | Removes configured secrets, URL credentials, and common password assignments from forwarded diagnostics. | Reduces accidental credential disclosure in MQTT/email result fields. |
| `parse_watchtower_log_record(line)` | Parses one Watchtower line as JSON first, then as the default LogFmt/Auto syntax; numeric session counters are normalized to integers. | Lets production Watchtower 1.7.1 defaults and explicit JSON logging use the same strict verifier without configuration-specific workarounds. |
| `inspect_watchtower_output(output, returncode, config)` | Parses Watchtower JSON or LogFmt logs, validates one `Session done` record/counters, detects failed updates/errors, and builds a bounded result object. | Converts completed Watchtower output into a reliable `success`/`failure` contract instead of trusting exit code alone. |
| `_read_runtime_text(path, label)` | Reads a per-run systemd timestamp/exit-code marker and returns the value plus any read error. | Keeps current-run correlation fail-closed without shell interpolation. |
| `parse_compose_exit_code(output, service)` | Reads `ExitCode` from Docker Compose `ps --format json` output in object, array, or line-delimited forms. | Lets the post-start reporter recover the completed container exit status after systemd has already run it. |
| `report_watchtower(config, compose_file, service, since_file, exit_code_file)` | Validates safe report mode, uses the captured current-run Compose exit code when supplied, scopes logs with `--since` to the current invocation, fails closed on missing markers, then reports through enabled channels. Manual use without runtime files can still fall back to Compose `ps`. | Prevents stale Watchtower logs/container state from being mistaken for the current run while keeping execution in systemd. |
| `parse_args()` | Defines `-c/--config`, `--watchtower-compose`, `--watchtower-service`, `--watchtower-since-file`, and `--watchtower-exit-code-file`. | Makes ordinary/report mode explicit and self-documented via `--help`. |
| `main()` | Dispatches Watchtower report mode or ordinary optional-MQTT/optional-mail/power mode and enforces failure gates only for enabled channels. | Provides the single application entry point. |

## systemd service directives and commands

| Directive/command | What it does and why |
| --- | --- |
| `Requires=docker.service` | Requires Docker for the unit. |
| `After=docker.service network-online.target` | Orders the unit after Docker/network startup. |
| `Wants=network-online.target` | Requests network-online startup support without making it a hard dependency. |
| `Type=oneshot` | systemd waits for the update/report sequence to complete. |
| `RemainAfterExit=no` | Lets a successful one-shot return to the inactive/stopped state immediately after `ExecStartPost` finishes, so another `systemctl start` can run the job again without a prior stop/restart. |
| `WorkingDirectory=/opt/watchtower` | Example directory containing the dedicated Compose file; user must customize it. |
| `RuntimeDirectory=mqtt-power-action` | Creates `/run/mqtt-power-action` for per-invocation timestamp and exit-code markers. |
| timestamp/reset `ExecStartPre` commands | Remove stale marker files and record this service invocation start time before Docker work begins. |
| `ExecStartPre=-/usr/bin/docker compose -f docker-compose.yaml pull watchtower` | Pulls the Watchtower image exactly once. The leading `-` allows an existing local image to be tried and the final result to be reported if the pull fails. |
| `ExecStart=/bin/sh -c ... docker compose ... up --pull never ...` | Runs/waits for the one-shot service without a second pull, writes the actual current Compose exit code to `/run/mqtt-power-action/watchtower-exit-code`, then returns control so post-reporting always runs. |
| `ExecStartPost=/usr/bin/python3 ... --watchtower-since-file ... --watchtower-exit-code-file ...` | Reads only current-invocation logs and the captured current Compose exit code, reports the verified result through enabled channels, and becomes the final success/failure gate. |
| `ExecStop=/usr/bin/docker compose -f docker-compose.yaml down` | Tears down the dedicated Compose project when the non-remaining oneshot enters its stop phase after reporting, and on an explicit stop. |
| `TimeoutStartSec=0` | Does not impose a systemd startup timeout on the update. |
| `TimeoutStopSec=120` | Bounds the stop/teardown phase. |
| `systemctl start watchtower.service` | Starts a fresh pull/update/report sequence whenever the unit is not running. After reporting, the unit automatically runs its stop/Compose-down phase and returns to inactive on success. |
| `systemctl stop watchtower.service` | Explicitly stops an in-progress/active unit; the normal completed oneshot also reaches the teardown path automatically. |
| `systemctl status watchtower.service` | Shows inactive/dead after a successful completed run, or failed after an unsuccessful post-run report. |
| `journalctl -u watchtower.service -n 100 --no-pager` | Displays Docker output and reporter diagnostics. |
| `systemd-analyze verify /etc/systemd/system/watchtower.service` | Performs native unit syntax/dependency validation without running the workload. |

## CLI commands

| Command | Purpose |
| --- | --- |
| `python3 mqtt_power_action_none.py --help` | Show all application flags. |
| `python3 mqtt_power_action_none.py -c PATH` | Ordinary configured flow with independently optional MQTT/mail plus optional power action. |
| `python3 mqtt_power_action_none.py --config PATH` | Long-form equivalent of `-c`. |
| `python3 mqtt_power_action_none.py -c PATH --watchtower-compose FILE --watchtower-service NAME [--watchtower-since-file FILE] [--watchtower-exit-code-file FILE]` | Inspect an already-completed Compose Watchtower service and process its verified result and use the enabled notification channels. |
| `cat VERSION` | Show package version. |
| `python3 -m unittest discover -s tests -v` | Run offline regression tests. |
| `python3 -m py_compile ...` | Check Python syntax without executing external actions. |

## Test helper/method map

`tests/test_mqtt_reports.py` defines `ReportTests.setUp`, `assert_config_error`, report-format/validation tests, optional MQTT/mail tests, MQTT/power failure-gate tests, mail backend tests, `service_settings`, `service_arguments`, service wiring/invocation tests, and CLI parser tests. These methods use mocks only; they exist to protect the original safety behavior and the current systemd wiring.

`tests/test_watchtower_flow.py` defines `WatchtowerReportTests.setUp`, `report`, strict session/exit tests, failure-detail/redaction tests, Compose exit-code parser tests, completed-job-only reporter tests, disabled-channel Watchtower tests, report-delivery/preflight tests, and release-layout checks that protect the systemd subfolder and excluded reference YAML. `AutomationTests.setUp`, `render_bool`, `condition`, and `walk_actions` form a small offline evaluator used by the success/failure/timeout shutdown-guard tests and Compose logging checks.

## Home Assistant flow

When MQTT is enabled, the Watchtower publisher and HA examples use one shared result-topic contract. `mqtt_power_action_none.py` publishes a JSON object containing `status` and `host`; it does not publish separate success and failure topics.

`watchtower-manual-update.yaml` publishes `start_watchtower`, then has exactly one MQTT wait trigger on the shared result topic. That trigger matches the expected `host` and accepts the report regardless of outcome. Later template conditions read `wait.trigger.payload_json.status`: only exact `success` reaches the final shutdown guard; `failure`, unknown/malformed status, or timeout stops without shutdown. It uses `mode: restart` so a new manual invocation replaces an older still-running invocation.

