# Commented code map

This map describes the current code's purpose and actual behavior. All runtime
logic remains in `mqtt_power_action_none.py`; existing functions
are reused without replacement modules. Source comments occasionally overstate
early validation or contain misplaced references to SMTP/systemctl. The
explanations below follow the executed code.

## Files

| File | What it contains and why |
| --- | --- |
| `mqtt_power_action_none.py` | Complete executable application: config readers, templates, MQTT, mail, power, CLI, and orchestration. |
| `configs/config-sendmail-none.example.ini` | All 41 supported settings, using notification-only sendmail defaults, automatic JSON reports, and an inactive SMTP section, so setup options are discoverable. |
| `configs/config-smtp.example.ini` | All 41 supported settings, using SMTP/STARTTLS and the user's shutdown-plus-dry-run defaults. Corrected JSON templates and plain INI names work with the existing script. |
| `watchtower.service` | Original generic Compose service; kept because it was supplied as part of the project. Its external stack and hook are prerequisites, not included application modules. |
| `README.md` | The user's disclaimer and project-specific operational/data-loss warning, followed by current installation, CLI, configuration, service use, and troubleshooting. Dry-run limits are explicit because MQTT can trigger external actions. |
| `VERSION` | Package version, readable without importing dependencies. |
| `VERSIONING.md` | Increment/rollover policy and all release changes. |
| `VERIFICATION.md` | Check results and limits so readers can distinguish simulation from deployment tests. |
| `MANIFEST.json` | Release paths, sizes, hashes, original inventory, and preservation classifications for archive verification. |
| `HomeAssistant/home-assistant-automation.yaml` | Supplied automation with its original behavior and identifiers; a regular automation YAML, not a parameterized blueprint. Never installed or executed by this package. |
| `tests/test_mqtt_reports.py` | Offline regression tests with fake MQTT/mail/power I/O, protecting report compatibility and original safety gates. |

## Configuration and formatting functions

| Function | What it does | Why it does it |
| --- | --- | --- |
| `config_error(message)` | Prints `CONFIG ERROR:` and raises `SystemExit(2)`. | Gives explicitly handled config errors a consistent exit status. |
| `get_str(config, section, option, default, required)` | Reads and strips a string; handles absent sections/options and rejects required empty values. | Centralizes config lookup and required-value handling. |
| `get_int(config, section, option, default, required)` | Reuses `get_str`, converts to integer, and reports conversion errors. | Reads ports and QoS without duplicating missing-value rules; does not itself validate ranges. |
| `get_float(config, section, option, default, required)` | Reuses `get_str`, converts to float, and reports conversion errors. | Supports fractional delays/timeouts; does not reject infinity, NaN, or negative values. |
| `get_bool(config, section, option, default)` | Uses ConfigParser boolean conversion or the provided default. | Keeps boolean flags consistent and rejects unrecognized boolean strings. |
| `get_password(value, env_var)` | Uses a nonempty direct password first, otherwise looks up the named environment variable. | Allows credentials outside the INI while preserving direct-value precedence. |
| `get_config_hostname(config)` | Uses configured nonempty hostname, otherwise `socket.gethostname()`. | Gives notifications a friendly override without requiring one. |
| `make_safe_id(value)` | Lowercases, replaces non-alphanumeric/non-dash/non-underscore characters, trims edge separators, and falls back to `unknown-host`. | Creates reusable hostname-based topic/client identifiers; Unicode alphanumerics are retained. |
| `get_event_name_for_action(action)` | Maps shutdown/reboot/none to server_shutdown/server_reboot/success; rejects anything else. | Keeps MQTT events consistent with the selected action. |
| `render_template(value, config)` | Resolves hostname, safe_hostname, action, and event with `str.format`; reports formatting errors. | Reuses one template mechanism for topic, custom payload, client ID, and subjects. Literal braces must be doubled. |
| `encode_mqtt_report(report)` | Requires an object and success/failure status, checks optional known field types, and emits compact strict JSON with no NaN/Infinity. | Shares validation across automatic/custom reports so the consumer receives a usable JSON object; incorrect config exits 2. |
| `build_mqtt_message(config)` | For empty/auto, reads the six report options, renders title, derives an automatic result code, and adds original event/host; otherwise renders and parses custom JSON. Both paths call `encode_mqtt_report`. | Provides consumer-compatible reports with safe automatic string escaping. Custom messages replace report settings and still require valid JSON after formatting. Status describes the caller's job independently of action/transport success. |
| `get_mqtt_client_id(config)` | Builds `mqtt-power-action-` plus safe hostname for empty/auto, or renders a custom ID. | Makes client naming consistent without requiring manual configuration. |
| `load_config(path)` | Reads INI without interpolation; checks readability, action, QoS, backend, enabled-mail recipient, enabled-SMTP credential-source settings, and builds/validates the report. | Rejects report errors before MQTT/mail/power side effects. It does not validate every other option/template here or catch every INI parser exception. |

## MQTT functions

| Function | What it does | Why it does it |
| --- | --- | --- |
| `make_mqtt_client(client_id)` | Tries the Paho v2 callback constructor, then falls back on AttributeError/TypeError to the older constructor. | Supports both callback API generations. |
| `reason_code_to_int(reason_code)` | Tries integer conversion, then `.value`, then success/0 text; otherwise returns 1. | Normalizes broker results from different Paho representations. |
| `wait_for_publish_compatible(info, timeout)` | Calls `wait_for_publish(timeout=...)`; retries without arguments on TypeError. | Supports older method signatures; that fallback has no timeout bound. |
| `publish_mqtt(config)` | Reads and renders settings, builds a client, optionally authenticates, connects, starts the loop, waits for broker result, publishes, checks receipt status, and returns `(ok, details)`. Tries disconnect and loop stop in `finally`. | Completes notification before allowing the later mail/power flow; returns ordinary network failures for main's abort policy. Config/client setup before its try block can still raise. If disconnect raises, loop_stop is skipped by the shared cleanup try block. |
| `publish_mqtt.on_connect(client, userdata, flags, reason_code, properties)` | Stores normalized broker result and sets a threading Event. | Signals the waiting main thread on both connection acceptance and rejection. |

`client.connect(host, port, keepalive=30)` initiates a synchronous connection;
`client.loop_start()` processes MQTT asynchronously. The Event timeout begins
after connect returns. `client.publish()` uses configured QoS/retain and
`info.is_published()` checks completion; this does not prove a subscriber acted.
`client.disconnect()` and `client.loop_stop()` attempt connection/thread cleanup.

## Mail functions

| Function | What it does | Why it does it |
| --- | --- | --- |
| `find_sendmail(path)` | Returns an explicit path, otherwise checks two conventional paths then PATH. | Supports both local defaults and custom installations. Explicit paths are not prevalidated for executability. |
| `build_mail_message(config, mail_type, details)` | Builds From/To/Subject and a plain body with host, action, MQTT topic/payload, details, and optional static text. | Shares message creation across backends so the notification content stays consistent. Sender falls back to SMTP username or root@hostname. |
| `send_mail_sendmail(config, msg, mail_type)` | Finds the binary and runs `[sendmail_bin, '-t']` with message bytes on stdin; reports errors and returns a bool. | Uses local mail delivery without shell interpolation. `-t` reads recipients from headers; no subprocess timeout is configured. |
| `send_mail_smtp(config, msg, mail_type)` | Resolves credentials; opens SMTP_SSL or normal SMTP with optional STARTTLS, logs in, sends, and closes via a context manager. | Supports remote authenticated delivery with default certificate checks when TLS is enabled. SSL takes precedence; a missing resolved password fails. |
| `send_mail(config, mail_type, details)` | Builds one message, then dispatches to the configured backend. | Avoids duplicating body/header logic. Message-building exceptions are not caught here. |

SMTP command sequence on the normal path is `EHLO`, optional `STARTTLS` and a
second `EHLO`, authentication via `login`, then `send_message`. The implicit-TLS
path opens `SMTP_SSL` before login/send. A successful return means the local
program or SMTP server accepted the send operation, not recipient delivery.

## Power and program entry

| Function / entry | What it does | Why it does it |
| --- | --- | --- |
| `run_power_action(config)` | Returns immediately for none. For shutdown/reboot selects systemctl poweroff/reboot; prints instead of executing when dry_run is true. Otherwise runs the argument list with check=True. | Keeps notification-only and dry-run guards immediately before the destructive command. Missing dry_run defaults to false. |
| `parse_args()` | Creates argparse help and requires `-c`/`--config`; returns parsed arguments. | Makes the external configuration explicit for each invocation. |
| `main()` | Loads arguments/config, reads flags/delay, publishes, sends conditional mail, enforces separate MQTT/success-mail abort gates, waits for non-none actions, and catches power-command failures. | Orders MQTT and mail before any power request. Permitted failures can still finish successfully. Delay is outside the power-action try block. |
| `if __name__ == '__main__'` | Calls main only for direct execution. | Allows controlled import without running the workflow. The top-level Paho import still happens and exits 1 if unavailable. |

`systemctl poweroff` requests host shutdown; `systemctl reboot` requests host
restart. Neither is executed for none or dry-run. `time.sleep` delays positive
shutdown/reboot runs, including dry-run, so downstream consumers have time to
process the notification. It is skipped for none.

## CLI, setup, and service command map

| Command/directive | What it does and why |
| --- | --- |
| `python3 mqtt_power_action_none.py -h` / `--help` | Displays argparse usage, making accepted flags discoverable; dependency import runs first. |
| `python3 mqtt_power_action_none.py -c PATH` / `--config PATH` | Runs the notification/power workflow with the chosen config; these are the only execution flags. |
| `cat VERSION` | Reads version metadata without executing the app. |
| `python3 -c "...compile(...)..."` in VERIFICATION | Reads and compiles the application in memory, checking syntax without importing Paho, running the app, or writing bytecode. |
| `sudo apt install python3-paho-mqtt` | Installs the system-Python MQTT dependency on Debian/Ubuntu, as suggested by the original script. |
| `cp configs/config-sendmail-none.example.ini config.ini` | Creates an editable live sendmail configuration while retaining the example. |
| `cp configs/config-smtp.example.ini config.ini` | Alternative setup command: creates an editable SMTP configuration from the complete SMTP example. |
| `chmod 600 config.ini` | Restricts config access to its owner because it may contain credentials. |
| `export MQTT_PASSWORD SMTP_PASSWORD` | Exports already-populated shell variables for password_env lookup by the child process. |
| `Requires`, `After`, `Wants` in the unit | Express Docker dependency and network startup ordering so startup prerequisites are requested first. |
| `Type=oneshot`, `RemainAfterExit=yes` | Preserve active unit state after Compose's startup process finishes. |
| `WorkingDirectory=/opt/mycompose` | Selects the directory containing the user's Compose project. |
| `/usr/bin/docker compose pull` (`ExecStartPre`) | Pulls service images so startup uses the fetched images. |
| `/usr/bin/docker compose up -d --wait` (`ExecStart`) | Starts the stack in the background and waits for running/healthy state before the hook. |
| `/opt/mycompose/success.sh` (`ExecStartPost`) | Runs the user's external success hook after startup; its actual behavior is unknown because it was not supplied. |
| `/usr/bin/docker compose down` (`ExecStop`) | Stops/removes the Compose stack's containers/networks when the service is stopped. |
| `TimeoutStartSec=0`, `TimeoutStopSec=120` | Allows unlimited startup and limits service stopping to 120 seconds. |
| `WantedBy=multi-user.target` | Associates enablement with normal multi-user boot. |
| `sudo install -m 644 watchtower.service /etc/systemd/system/watchtower.service` | Copies the supplied unit into systemd's local unit directory with explicit permissions. |
| `sudo systemctl daemon-reload` | Reloads unit definitions after installation/editing. |
| `sudo systemctl enable --now watchtower.service` | Enables future boot startup and starts the unit now, including pulls and the hook. |
| `systemctl status watchtower.service` | Inspects current service state for diagnosis. |
| `journalctl -u watchtower.service -n 100 --no-pager` | Displays the most recent 100 unit log lines without an interactive pager. |
| `sudo systemctl stop watchtower.service` | Stops the unit and its Compose stack. |
| `sudo systemctl disable watchtower.service` | Removes boot enablement; does not stop an already-running unit. |

No Compose definition or hook implementation can be mapped beyond these call
sites because those files were not among the three supplied originals.

## Offline test functions and command

Run `python3 -B -m unittest discover -s tests -v` from the project directory.
`-B` avoids bytecode, `-m unittest` selects the standard library runner,
`discover -s tests` loads the suite, and `-v` reports each test. Running the test
file directly calls `unittest.main()` under its main guard for the same suite.

All functions below are methods of `ReportTests` in `tests/test_mqtt_reports.py`.
They exist to verify the consumer contract or protect safety behavior during edits.

| Function | What it verifies and why |
| --- | --- |
| `setUp()` | Creates a fresh app with Paho stubbed and reads the example so tests cannot connect to real MQTT accidentally. |
| `assert_config_error(function, *args)` | Requires exit 2 for rejected config, distinguishing controlled validation from tracebacks. |
| `test_default_report()` | Checks every generated field and type against the documented default object. |
| `test_auto_without_report_section()` | Confirms automatic defaults without a report section, using an in-memory config instead of shipping an original snapshot. |
| `test_status_independent_of_action()` | Covers all six status/action pairs so legacy events and job status stay independent. |
| `test_escaping_and_failure_details()` | Round-trips quotes, Unicode, slashes, braces, and multiline output so consumer JSON remains valid. |
| `test_custom_object_and_title_fallback()` | Confirms custom objects replace report settings and permit title/name/job plus extra data. |
| `test_commented_custom_example()` | Executes the shipped example template to prevent unusable documentation. |
| `test_invalid_custom_payloads()` | Rejects text/non-objects, absent/unknown status, wrong field types, invalid JSON and nonfinite numbers. |
| `test_invalid_auto_settings()` | Checks status, code, and warning validation on generated reports. |
| `test_invalid_report_stops_before_io()` | Exercises real config validation with an in-memory INI reader and proves invalid messages cannot reach MQTT/mail/power even with continuation enabled. |
| `test_published_payload_and_exact_topics()` | Captures fake-client publish arguments for both reference topics and both statuses; checks payload types, QoS, retain, and cleanup without invoking Home Assistant. |
| `test_none_and_dry_run_guards()` | Checks all six power-action/dry-run combinations against mocked subprocess calls. |
| `test_failure_gates()` | Checks MQTT/mail abort and continuation paths for both report statuses; confirms none skips delay. |
| `test_dry_run_still_waits()` | Preserves configured delay in dry-run and suppresses systemctl. |
| `test_power_failure_is_reported_by_mail()` | Preserves failure-mail handling and original power subprocess exit-code propagation. |
| `test_mail_includes_same_json()` | Keeps the mail troubleshooting body consistent with the published JSON report. |
| `test_cli_parser()` | Checks config aliases, help, and invalid argument exits with dependency import stubbed. |
| `test_both_config_examples_load()` | Loads both relocated INIs through the real config loader, validates the action/JSON/safety values and commented templates, and checks that pasted Markdown escapes are absent. |
| `test_smtp_starttls_delivery()` | Confirms SMTP connection parameters, EHLO/STARTTLS/login/send order, recipient/sender and report body using a fake SMTP connection. |
| `test_smtp_ssl_and_environment_password()` | Confirms implicit TLS takes precedence and credentials can come from the named environment variable. |
| `test_smtp_missing_password_never_connects()` | Proves an empty resolved password fails before any connection. |
| `test_smtp_failure_aborts_power()` | Exercises real mail routing with a simulated connection failure; confirms failure-mail attempt, exit 1, and no later delay/power call. |
| `test_smtp_full_dry_run_order()` | Runs main with the actual SMTP INI and fake MQTT/SMTP: publication precedes mail and delay; dry-run prints poweroff but invokes no power subprocess. |
| `test_sendmail_example_routes_to_sendmail()` | Confirms the relocated sendmail INI still routes through sendmail -t with message bytes rather than SMTP. |
