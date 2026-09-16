# Commented Code Map

This file maps the current 0.0.9 code and operational commands. It describes what each function/command does and why it exists.

## Project files

| File | Purpose |
| --- | --- |
| `mqtt_power_action_none.py` | Main MQTT/mail/power reporter plus completed-Watchtower result inspection. |
| `watchtower.service` | Keeps Watchtower lifecycle in systemd: pull, run/wait, post-run reporting, teardown. |
| `compose.example.yaml` | Redacted one-shot Watchtower Compose example with JSON/info logging required by the post-run parser. |
| `configs/config-sendmail-none.example.ini` | Complete 41-option example using local sendmail and no local power action. |
| `configs/config-smtp.example.ini` | Complete 41-option example using SMTP and no local power action. |
| `HomeAssistant/watchtower-manual-update.yaml` | Redacted example that waits for JSON success/failure and shuts down only after success. |
| `HomeAssistant/syncerate-all-servers.yaml` | Generic multi-topic MQTT JSON consumer example. |
| `HomeAssistant/home-assistant-automation.yaml` | Redacted chained-job Home Assistant example. |
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
| `get_password(value, env_var)` | Uses a direct password first, otherwise reads the named environment variable. | Supports secrets outside the INI while preserving explicit override behavior. |
| `get_config_hostname(config)` | Uses `[server] hostname`, falling back to `socket.gethostname()`. | Gives reports/templates a stable friendly host label. |
| `make_safe_id(value)` | Lowercases and replaces unsupported client-ID characters. | Prevents awkward/special hostname characters from producing unsafe MQTT client IDs. |
| `get_event_name_for_action(action)` | Maps `shutdown`, `reboot`, `none` to report event names. | Preserves the original event contract independently of job `status`. |
| `render_template(value, config)` | Expands `{hostname}`, `{safe_hostname}`, `{action}`, `{event}`. | Reuses one controlled template mechanism for topics, client IDs, subjects, and custom payloads. |
| `encode_mqtt_report(report)` | Validates required JSON object/status and known field types, then emits compact strict JSON. | Prevents malformed payloads from reaching Home Assistant. |
| `build_mqtt_message(config)` | Builds auto/custom ordinary reports, or encodes the runtime Watchtower result attached to the config. | Provides one shared MQTT payload path for ordinary and Watchtower reporting. |
| `get_mqtt_client_id(config)` | Builds automatic hostname-based client IDs or renders a configured template. | Keeps MQTT identity configurable without duplicating template logic. |
| `load_config(path)` | Loads the INI and validates action, QoS, mail backend/recipient/SMTP credential source, and report JSON. | Rejects configuration problems before external side effects. |
| `make_mqtt_client(client_id)` | Creates Paho v2 client with a v1 fallback. | Keeps compatibility with both commonly deployed Paho APIs. |
| `reason_code_to_int(reason_code)` | Normalizes different Paho callback result representations to an integer. | Makes connection success/failure checks version-independent. |
| `wait_for_publish_compatible(info, timeout)` | Uses timeout-aware publish waiting when available and the older fallback otherwise. | Preserves compatibility across Paho versions. |
| `publish_mqtt(config)` | Connects, authenticates, publishes the generated JSON, waits for confirmation, and returns `(ok, details)`. | Keeps all MQTT transport handling in one reusable function. |
| nested `on_connect(...)` | Stores the broker connection result and releases the waiting thread. | Lets synchronous main flow safely wait for Paho's asynchronous connect callback. |
| `find_sendmail(path)` | Uses configured executable or searches common sendmail locations/PATH. | Supports local MTA delivery without shell command construction. |
| `build_mail_message(config, mail_type, details)` | Builds the email headers/body and includes the same MQTT JSON for troubleshooting. | Keeps MQTT and email reporting consistent. |
| `send_mail_sendmail(config, msg, mail_type)` | Sends message bytes to `sendmail -t`. | Provides local-MTA delivery without shell interpolation. |
| `send_mail_smtp(config, msg, mail_type)` | Handles SMTP/SMTP_SSL, optional STARTTLS, login, and send. | Provides direct authenticated SMTP delivery. |
| `send_mail(config, mail_type, details)` | Builds a message and routes it to the selected backend. | Keeps backend selection out of main flow. |
| `run_power_action(config)` | Performs/dry-runs `systemctl poweroff` or `systemctl reboot`, or no-ops for `none`. | Centralizes the dangerous local power action behind configuration safety checks. |
| `redact_watchtower_text(text, config)` | Removes configured secrets, URL credentials, and common password assignments from forwarded diagnostics. | Reduces accidental credential disclosure in MQTT/email result fields. |
| `inspect_watchtower_output(output, returncode, config)` | Parses Watchtower JSON logs, validates one `Session done` record/counters, detects failed updates/errors, and builds a bounded result object. | Converts completed Watchtower output into a reliable `success`/`failure` contract instead of trusting exit code alone. |
| `parse_compose_exit_code(output, service)` | Reads `ExitCode` from Docker Compose `ps --format json` output in object, array, or line-delimited forms. | Lets the post-start reporter recover the completed container exit status after systemd has already run it. |
| `report_watchtower(config, compose_file, service)` | Validates safe report-mode settings, runs only Compose `ps` and `logs`, creates the verified report, publishes MQTT/mail, and returns 0/1. | Keeps Watchtower execution in systemd while still reporting both success and failure from `ExecStartPost`. |
| `parse_args()` | Defines `-c/--config`, `--watchtower-compose`, and `--watchtower-service`. | Makes ordinary/report mode explicit and self-documented via `--help`. |
| `main()` | Dispatches Watchtower report mode or ordinary MQTT/mail/power mode and enforces existing failure gates. | Provides the single application entry point. |

## systemd service directives and commands

| Directive/command | What it does and why |
| --- | --- |
| `Requires=docker.service` | Requires Docker for the unit. |
| `After=docker.service network-online.target` | Orders the unit after Docker/network startup. |
| `Wants=network-online.target` | Requests network-online startup support without making it a hard dependency. |
| `Type=oneshot` | systemd waits for the update/report sequence to complete. |
| `RemainAfterExit=yes` | Keeps a successful one-shot active so `restart` first performs `ExecStop`, then runs a fresh update. |
| `WorkingDirectory=/opt/watchtower` | Example directory containing the dedicated Compose file; user must customize it. |
| `ExecStartPre=-/usr/bin/docker compose -f docker-compose.yaml pull watchtower` | Pulls the Watchtower image. The leading `-` prevents a pre-start non-zero exit from skipping the later result reporter. |
| `ExecStart=-/usr/bin/docker compose -f docker-compose.yaml up --abort-on-container-exit --exit-code-from watchtower watchtower` | Runs/waits for the one-shot service. The leading `-` deliberately allows `ExecStartPost` to run after a non-zero Watchtower/Docker result. |
| `ExecStartPost=/usr/bin/python3 ... --watchtower-compose ... --watchtower-service watchtower` | Reads the completed job and publishes one verified JSON success/failure. Its exit code becomes the final success/failure gate. |
| `ExecStop=/usr/bin/docker compose -f docker-compose.yaml down` | Tears down the dedicated Compose project on stop/restart. |
| `TimeoutStartSec=0` | Does not impose a systemd startup timeout on the update. |
| `TimeoutStopSec=120` | Bounds the stop/teardown phase. |
| `systemctl start watchtower.service` | Runs the flow when the unit is inactive. |
| `systemctl restart watchtower.service` | Runs teardown, then a fresh pull/update/report sequence; preferred for repeat runs with `RemainAfterExit=yes`. |
| `systemctl stop watchtower.service` | Executes Compose teardown. |
| `systemctl status watchtower.service` | Shows successful active-exited state or failed state from the post-run reporter. |
| `journalctl -u watchtower.service -n 100 --no-pager` | Displays Docker output and reporter diagnostics. |
| `systemd-analyze verify /etc/systemd/system/watchtower.service` | Performs native unit syntax/dependency validation without running the workload. |

## CLI commands

| Command | Purpose |
| --- | --- |
| `python3 mqtt_power_action_none.py --help` | Show all application flags. |
| `python3 mqtt_power_action_none.py -c PATH` | Ordinary configured MQTT/mail/power flow. |
| `python3 mqtt_power_action_none.py --config PATH` | Long-form equivalent of `-c`. |
| `python3 mqtt_power_action_none.py -c PATH --watchtower-compose FILE --watchtower-service NAME` | Inspect an already-completed Compose Watchtower service and publish its verified result. |
| `cat VERSION` | Show package version. |
| `python3 -m unittest discover -s tests -v` | Run offline regression tests. |
| `python3 -m py_compile ...` | Check Python syntax without executing external actions. |

## Test helper/method map

`tests/test_mqtt_reports.py` defines `ReportTests.setUp`, `assert_config_error`, report-format/validation tests, MQTT/power failure-gate tests, mail backend tests, `service_settings`, `service_arguments`, service wiring/invocation tests, and CLI parser tests. These methods use mocks only; they exist to protect the original safety behavior and the current systemd wiring.

`tests/test_watchtower_flow.py` defines `WatchtowerReportTests.setUp`, `report`, strict session/exit tests, failure-detail/redaction tests, Compose exit-code parser tests, completed-job-only reporter tests, report-delivery/preflight tests, and a generic HA consumer test. `AutomationTests.setUp`, `render_bool`, `condition`, and `walk_actions` form a small offline evaluator used by the success/failure/timeout shutdown-guard tests and Compose logging checks.

## Home Assistant flow

The Watchtower example publishes `start_watchtower`, waits on one redacted result topic, branches on the JSON `status`, stops without shutdown on timeout/failure, and reaches the shutdown actions only after the final success guard. All entity IDs/topics are placeholders and must be replaced for a real installation.
