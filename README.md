# MQTT Power Action

## ⚠️ Disclaimer / Liability Notice

**This script is provided “as is”, without warranty of any kind.**\
By using this script, **you agree that I am not liable for any data loss, system damage, service interruption, or other issues** that may occur as a result of running it.

This script performs **destructive operations**, including but not limited to:

- Requesting host **shutdown or reboot** using `systemctl`, which can interrupt running services, backups, and active writes.
- Publishing **MQTT messages** that can trigger actions in receiving automations, including cleanup or shutdown. Incorrect reports or topics can trigger those actions at the wrong time.
- Sending email through **sendmail or SMTP**, which can send unintended notifications or disclose information included in the report.
- Through the bundled **Docker Compose service**, pulling images, starting or replacing containers, stopping and removing containers and networks, and executing the configured `success.sh` hook. These operations can interrupt services or lose data stored only inside removed containers; the hook can perform additional operations defined by its owner.

⚠️ **Always test on a non-production system first.**\
⚠️ **Always ensure you have verified backups.**\
⚠️ **You are fully responsible for reviewing and understanding the code before running it.**

⚠️ AI-assisted / vibe-coded experimental software. Use at your own risk.

## Disclaimer

This project is AI-assisted / vibe-coded software created as a hobby project. It has not been professionally audited and may contain bugs, unsafe behavior, data-loss issues, security problems, or incorrect assumptions.

You are responsible for reviewing the code, testing it in a safe environment, making backups, and understanding what it does before using it on real data. The author is not responsible for damage, data loss, broken systems, security issues, or other problems caused by using this software.

## Data Loss Warning

This application can perform destructive operations, including shutting down or rebooting the host and, through the bundled service, stopping and removing Docker containers. These actions can interrupt backups and active writes, cause data loss or corruption, and interrupt services. MQTT messages can also trigger destructive actions in receiving automations. Always test with dry-runs first, review the configuration and receiving automations, and keep a separate working backup.

**For this script, `dry_run = true` suppresses only the local power command. MQTT messages and email are still sent, and receiving automations may still perform destructive actions.** The script does not generate an execution plan; review its configuration, the receiving automations, and any service hooks before running it.

## Requirements and setup

Publish one JSON MQTT status report, optionally send email, then optionally
request a Linux shutdown or reboot. Configuration controls the whole run.

- Python 3.10 or later (the script uses `str | None` annotations).
- The `paho-mqtt` Python package. The code contains compatibility paths for Paho
  1.x and 2.x; see `VERIFICATION.md` for what was actually tested.
- Access to your MQTT broker. The script uses plain MQTT; it has no MQTT TLS
  configuration options.
- For mail: a configured local sendmail-compatible program, or an SMTP account.
- For real power actions: Linux with `systemctl` and permission to power off or
  reboot. Notification-only mode does not call `systemctl`.

On Debian/Ubuntu with a suitable Python version, the supplied script suggests:

```sh
sudo apt install python3-paho-mqtt
```

This installs the MQTT dependency for the system Python. Mail server setup is
separate; merely installing the Python dependency does not configure delivery.

Extract the ZIP, open a terminal in its project directory, and copy the example
for your mail backend. For sendmail/Postfix:

```sh
cp configs/config-sendmail-none.example.ini config.ini
chmod 600 config.ini
```

For SMTP, use this alternative instead:

```sh
cp configs/config-smtp.example.ini config.ini
chmod 600 config.ini
```

`cp` creates your working configuration; `chmod 600` restricts it to its owner.
Edit `config.ini`: set your broker, topic, hostname, and mail addresses. Both
examples enable success and failure mail. Set both mail flags to `false` if you
do not want email. The sendmail example uses `action = none`; the SMTP example
uses `action = shutdown` with `dry_run = true`. Choose `action = none` for
notifications only. Replace the SMTP username/password placeholders before use.

| Example | Mail backend | Power behavior as supplied |
| --- | --- | --- |
| `configs/config-sendmail-none.example.ini` | Local sendmail/Postfix | Notifications only; no power command or delay. |
| `configs/config-smtp.example.ini` | SMTP on port 587 with STARTTLS | Sends notifications, waits 10 seconds, prints the shutdown command; dry-run prevents the local shutdown. |

Both examples include all 41 available options, including settings for the other
mail backend. Only the selected backend's delivery settings are used.

## Commands

```sh
python3 mqtt_power_action_none.py --help
python3 mqtt_power_action_none.py -c config.ini
python3 mqtt_power_action_none.py --config /absolute/path/to/config.ini
cat VERSION
```

| Command/flag | Purpose |
| --- | --- |
| `-h`, `--help` | Show usage and exit. Paho must be installed even for help, because it is imported first. |
| `-c PATH`, `--config PATH` | Required path to the INI file; the two forms are equivalent. Relative paths use the current working directory. Running this command actually publishes MQTT and may send mail. |
| `cat VERSION` | Display the package version. There is no `--version` flag. |

There are no other application CLI flags. Power action and dry-run settings
belong in the configuration, not on the command line.

## Run behavior and safety settings

1. Parse arguments and load configuration. Some values are validated here;
   other values are read and validated later when used.
2. Connect and publish MQTT.
3. On MQTT success, optionally send success mail. If that mail fails, optionally
   attempt failure mail. Abort with status 1 unless `continue_on_mail_fail` is true.
4. On MQTT failure, optionally send failure mail. Abort with status 1 unless
   `continue_on_mqtt_fail` is true. Success mail is not sent on this path.
5. For shutdown/reboot, wait for a positive `delay_before_action`, including in
   dry-run mode. Then request the action, or print it in dry-run mode.
6. With `action = none`, skip the delay and all power commands.

**`dry_run = true` suppresses only the power command. MQTT and mail are real.**
The example sets `dry_run = true`, but the script defaults to **false** if you
omit it. Keep the setting explicit. `continue_on_mqtt_fail` and
`continue_on_mail_fail` default to false and govern separate failure paths;
failure-mail delivery failure itself does not add another abort gate.

MQTT report status describes the job outcome supplied in configuration. It is
published before mail and the power command; it does not confirm those later
steps. Success mail confirms MQTT publication, even if the published report says
the caller's job failed. The script does not run or inspect a backup job.
Allowed failures may still lead to exit status 0. Config errors and unexpected
exceptions do not necessarily produce failure mail.

### Choosing an action

| `power.action` | MQTT event with `message = auto` | Power behavior |
| --- | --- | --- |
| `none` | `success` | No delay, no power command. |
| `shutdown` | `server_shutdown` | `systemctl poweroff`, unless dry-run. |
| `reboot` | `server_reboot` | `systemctl reboot`, unless dry-run. |

To test a power-action configuration, keep `dry_run = true`. To perform the
configured shutdown or reboot, set it to false and run with the necessary host
permissions. The script does not automatically invoke sudo or confirm interactively.

## Full configuration reference

Each example in `configs/` contains all 41 supported section/option pairs,
including the inactive mail backend. Defaults below are **code defaults**, which sometimes
differ from the example. Values are stripped of surrounding whitespace. INI
interpolation is disabled, so `%` in a password is literal. Boolean values accept
true/false, yes/no, on/off, or 1/0. Use exact lowercase action/backend names.

| Section.option | Default / requirement | Meaning |
| --- | --- | --- |
| `server.hostname` | OS hostname | Friendly name used in messages; missing or empty falls back to OS hostname. |
| `power.action` | Required | `none`, `shutdown`, or `reboot`. |
| `power.delay_before_action` | `1.0` | Seconds before shutdown/reboot; positive values also delay a dry-run. `none` skips waiting, though the value is still parsed. |
| `power.dry_run` | `false` | Print the power command instead of executing it. |
| `power.continue_on_mqtt_fail` | `false` | Allow later power processing after MQTT failure. |
| `power.continue_on_mail_fail` | `false` | Allow later power processing after success-mail failure. |
| `mqtt.host` | Required | Broker address. |
| `mqtt.port` | `1883` | Broker TCP port; no TLS support in this script. |
| `mqtt.username` | Empty | Authenticate only when nonempty. |
| `mqtt.password` | Empty | Literal password; takes priority over the environment variable. |
| `mqtt.password_env` | Empty | Name of environment variable holding the password. |
| `mqtt.topic` | Required | Publish topic; supports templates below. |
| `mqtt.message` | `auto` | Empty or case-insensitive `auto` generates the JSON report below; otherwise a template that must render to a JSON object with status success/failure. |
| `mqtt.client_id` | `auto` | Empty or `auto` generates `mqtt-power-action-{safe_hostname}`; otherwise a template. Use distinct IDs for overlapping runs. |
| `mqtt.qos` | `1` | 0 (at most once), 1 (at least once), or 2 (exactly once at the MQTT protocol level). |
| `mqtt.retain` | `false` | Ask broker to retain the last message for future subscribers. |
| `mqtt.connect_timeout` | `10.0` | Wait for the connection callback after `connect()` returns; does not bound the preceding synchronous DNS/TCP connection. |
| `mqtt.publish_timeout` | `10.0` | Publish wait limit where supported by Paho; the compatibility fallback waits without a timeout. |
| `report.status` | `success` | Reported job outcome: success/failure (case-insensitive in this setting). Independent of action and MQTT delivery. Used only for automatic messages. |
| `report.title` | `auto` | Empty/auto becomes `hostname: action`; otherwise a template. Name your actual job here. |
| `report.exit_code` | `auto` | Integer job exit code; empty/auto gives 0 for success or 1 for failure. Does not set this script's process exit status. |
| `report.warning` | `false` | Job has non-fatal warnings; emits a JSON boolean. |
| `report.error` | Empty | Plain error summary for the reported job, safely JSON-escaped. No template expansion. |
| `report.stderr` | Empty | Plain captured output for the reported job, safely JSON-escaped. No template expansion; indent continuation lines for multiline INI values. |
| `mail.on_success` | `false` | Send mail after successful MQTT publication, before power action. |
| `mail.on_failure` | `false` | Attempt mail on MQTT failure, success-mail failure, or a caught power-action error. |
| `mail.backend` | `sendmail` | `sendmail` or `smtp`; validated even if mail is disabled. |
| `mail.to` | Empty | Required if either mail flag is enabled. |
| `mail.from` | Empty | Sender; defaults to SMTP username for SMTP, then `root@{hostname}` if still empty. |
| `mail.success_subject` | `{hostname}: SUCCESS MQTT before {action}` | Success subject template. |
| `mail.failure_subject` | `{hostname}: FAILURE MQTT/power action` | Failure subject template. |
| `mail.extra_body` | Empty | Static text appended to mail; not template-expanded. |
| `sendmail.path` | Empty | Explicit executable, or detection at `/usr/sbin/sendmail`, `/usr/bin/sendmail`, then PATH. |
| `smtp.host` | `smtp.gmail.com` | SMTP server. |
| `smtp.port` | `587` | SMTP TCP port. |
| `smtp.username` | Required for enabled SMTP mail | Authentication username; also fallback sender. |
| `smtp.password` | Empty | Literal password, preferred over environment value. |
| `smtp.password_env` | Empty | Password environment variable name; one password source must be configured for enabled SMTP mail. A missing/empty resolved password makes sending fail. |
| `smtp.ssl` | `false` | Connect with TLS immediately. Takes precedence over `starttls`. |
| `smtp.starttls` | `true` | Upgrade a normal SMTP connection to TLS before login. Setting both TLS flags false leaves the connection unencrypted. |
| `smtp.timeout` | `20.0` | SMTP connection/socket timeout in seconds. |

Use positive, finite timeout values and a finite, nonnegative delay. The script
does not fully validate ranges or reject unknown option names; check spelling.
The sendmail subprocess has no configured timeout.

### Templates and JSON

MQTT topic, custom message, custom client ID, report title, and both mail subjects support:
`{hostname}`, `{safe_hostname}`, `{action}`, and `{event}`. `safe_hostname`
lowercases the hostname, keeps alphanumeric characters, dashes, and underscores,
replaces other characters with `-`, trims edge dashes/underscores, and falls back
to `unknown-host`. Alphanumeric characters can include Unicode.

`message = auto` safely JSON-encodes all report strings. For custom JSON, double the
literal outer braces because custom values pass through Python string formatting:

```ini
message = {{"status":"success","title":"Maintenance completed","exit_code":0,"warning":false,"event":"{event}","host":"{hostname}","source":"unattended-upgrades"}}
```

Custom substitutions do not escape JSON quotes/backslashes; prefer `auto` when
the hostname may contain them. Unknown or malformed placeholders cause errors.
Custom messages replace the automatic report completely and ignore `[report]`.
They must contain a lowercase `status` string equal to `success` or `failure`.
Optional `exit_code` must be an integer, `warning` a boolean, and
`title`/`name`/`job`/`error`/`stderr` strings. Additional valid JSON fields are
allowed. Non-object payloads, invalid fields, malformed JSON, and nonfinite JSON
numbers are rejected with config exit 2 before network/mail/power operations.
Mail includes the same JSON report as well as delivery result details.

## Use with the supplied Home Assistant automation

The file is `HomeAssistant/home-assistant-automation.yaml`. It is a regular
automation YAML, with the supplied entities, topics, and actions intact. It is
not a parameterized blueprint. Review and adapt it in Home Assistant's automation
YAML editor; it is not installed or enabled by running the Python script.

The automation reads a JSON object from `trigger.payload_json`. Its branch is
selected by `status`; `event` is extra metadata and does not select a branch.
The automatic message with the supplied example values is:

```json
{"status":"success","title":"proxmox: none","exit_code":0,"warning":false,"error":"","stderr":"","event":"success","host":"proxmox"}
```

| JSON field | How the supplied automation uses it |
| --- | --- |
| `status` | `success` continues the corresponding backup sequence; `failure` sends a failure notification without continuing it. |
| `title` | Human-readable job description. For custom messages without title it falls back to name, then job, then Syncerate. |
| `exit_code` | Displayed in the notification; status still controls the branch. |
| `warning` | On success, true adds the non-fatal-warning notice. |
| `error`, `stderr` | Displayed in the failure notification. Empty generated values display as blank. |
| `event`, `host` | Preserved metadata; not read by this automation. Event follows the power action, while status follows the report. |

The automation listens to exactly these two case-sensitive topics:

- `homeassistant/Syncerate/Zotac-RI531-RPI5-Storage/status`
- `homeassistant/Syncerate/Zotac-RI531-AsusN14E/status`

For a report about the completed first backup, edit these settings in your
otherwise complete configuration:

```ini
[power]
action = none
dry_run = true

[mqtt]
topic = homeassistant/Syncerate/Zotac-RI531-RPI5-Storage/status
message = auto
retain = false

[report]
status = success
title = Asus-to-RPI5 backup
exit_code = auto
warning = false
error =
stderr =
```

These are edits to the existing sections, not a standalone connection config.
For the second backup, choose its AsusN14E topic and an appropriate title. On a
known job failure, set `report.status = failure`, set the actual exit code if
available (auto uses 1), and populate error/stderr before running the same `-c`
command. There is no automatic capture of another program's exit status/output.
Neither report status nor report exit code adds a new power-action gate; use
`action = none` for report-only calls.

For maintenance or Watchtower notifications, use a separate topic and an
automation subscribed to it. Publishing success on either backup topic tells
the pasted automation to execute that backup's follow-up actions. Keep
`retain = false` to avoid storing a completion event for later subscribers.
Dry-run still publishes real reports and can trigger those automation actions.
The package leaves the original example topic in place until you select the
appropriate job; JSON formatting alone does not make a different topic match.

### SMTP and environment passwords

Start with `configs/config-smtp.example.ini`, edit its `[smtp]` section, set username and
password source, and enable the desired mail flags. For implicit TLS, configure
the provider's port with `ssl = true`; with `ssl = false`, `starttls = true`
requests a TLS upgrade. TLS contexts use the system's normal certificate checks.

On a shell where the selected variables are already set, make them available to
the child process with:

```sh
export MQTT_PASSWORD SMTP_PASSWORD
```

This exports existing values; it does not populate them. Set `password_env` to
the matching name and leave the direct `password` empty. A systemd job requires
its own environment configuration; it does not inherit an interactive shell's
variables automatically.

The SMTP example's `password = your-gmail-app-password` is a placeholder, not a
working credential. For the environment alternative, clear `password`, set
`password_env = GMAIL_APP_PASSWORD`, and populate that variable in the script's
environment. A nonempty direct password always takes priority. The example is
compatible with the script's SMTP code, but server/account authentication and
delivery must be verified with your actual settings.

## Supplied `watchtower.service`

This is a generic Docker Compose unit named `watchtower.service`. It does not
directly call the Python application or identify any particular container image.
It requires Docker, uses `/opt/mycompose` as its working directory, and expects
an existing Compose project there plus an executable `/opt/mycompose/success.sh`.
Neither `compose.yml` nor `success.sh` was supplied. Provide your actual files
and inspect the hook before enabling the unit. There is no included automatic
integration between the unit and this script.

| Directive/command | Effect |
| --- | --- |
| `Requires=docker.service` / `After=docker.service network-online.target` / `Wants=network-online.target` | Require Docker and request/order after network-online startup; this does not verify broker or mail reachability. |
| `Type=oneshot`, `RemainAfterExit=yes` | Run startup commands and keep the unit active after they exit. |
| `WorkingDirectory=/opt/mycompose` | Resolve the Compose project in this directory. |
| `ExecStartPre=/usr/bin/docker compose pull` | Fetch the configured images before startup. |
| `ExecStart=/usr/bin/docker compose up -d --wait` | Start in the background and wait for containers to be running/healthy as defined by Compose. |
| `ExecStartPost=/opt/mycompose/success.sh` | Execute your hook after successful startup; its failure can fail unit activation. |
| `ExecStop=/usr/bin/docker compose down` | Stop and remove the stack's containers/networks when stopping a successfully started unit. |
| `TimeoutStartSec=0`, `TimeoutStopSec=120` | Disable startup time limit; give service stopping 120 seconds. |
| `WantedBy=multi-user.target` | Enable this unit for normal multi-user boot. |

After supplying the required stack and hook, the following Linux commands install
and manage the service. Starting it pulls images and runs the hook; stopping it
takes the stack down.

```sh
sudo install -m 644 watchtower.service /etc/systemd/system/watchtower.service
sudo systemctl daemon-reload
sudo systemctl enable --now watchtower.service
systemctl status watchtower.service
journalctl -u watchtower.service -n 100 --no-pager
sudo systemctl stop watchtower.service
sudo systemctl disable watchtower.service
```

`install -m 644` copies the unit with read permissions for all and write permission
for its owner. `daemon-reload` reloads unit definitions. `enable --now` enables
boot startup and starts now. `status` reports unit state. `journalctl` shows the
last 100 unit log lines without a pager. `stop` stops the current stack;
`disable` removes boot enablement and does not itself stop a running service.

## Exit status and troubleshooting

| Status | Meaning |
| --- | --- |
| `0` | Processing completed, including dry-run/none or failures explicitly allowed by continuation flags. |
| `1` | Missing Paho, a handled abort, or a generic caught power error; unhandled Python exceptions also normally exit 1. |
| `2` | Argument parsing or errors handled by `config_error`. Malformed INI syntax and some later errors can instead raise an uncaught exception. |
| Power subprocess status | A failed `systemctl` command's return code is propagated, after optional failure mail. |

For missing Paho, install it for the same Python interpreter you use to run the
script. For MQTT errors, inspect broker address, credentials, topic, and network
access. For sendmail errors, check executable detection and local delivery setup;
sendmail accepting a message is not proof that the recipient received it.
For SMTP errors, check TLS mode, server details, and the resolved password.
Do not treat the configured MQTT timeout as a strict whole-run deadline.

See `commented_code_map.md` for implementation explanations and
`VERIFICATION.md` for tested behavior and deployment limits. Configuration
examples live in `configs/`, and the Home Assistant automation lives in
`HomeAssistant/`. `MANIFEST.json` records the release inventory and SHA-256 hashes.
The release contains current project files without original snapshot copies.

## Offline checks

From the extracted project directory, run:

```sh
python3 -B -m unittest discover -s tests -v
```

`-B` disables bytecode files; `-m unittest` runs Python's standard test runner;
`discover -s tests` finds the tests; `-v` lists each result. These tests use fake
MQTT/mail/power interfaces and do not require Paho. They do not send reports or
install the reference automation. Live integration still needs testing on your host.
