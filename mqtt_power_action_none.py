#!/usr/bin/env python3

# This script sends an MQTT message before optionally performing a shutdown or reboot.
# It can also send success/failure mail through either local sendmail/Postfix or SMTP.
# The behavior is controlled by an external config file passed with -c / --config.

# Standard library imports used for config parsing, mail, networking,
# subprocess calls, timing, and command-line arguments.
import argparse
import configparser
import os
import shutil
import smtplib
import socket
import ssl
import subprocess
import sys
import threading
import time
from email.message import EmailMessage
import json
import re

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: Missing paho-mqtt. Install with: sudo apt install python3-paho-mqtt")
    sys.exit(1)


# Print a config-related error and exit with code 2.
# This keeps all config validation failures consistent.
def config_error(message: str):
    print(f"CONFIG ERROR: {message}")
    sys.exit(2)


# Read a string option from the config file.
# Handles missing sections/options, default values, and required values.
def get_str(config, section, option, default=None, required=False):
    # If the whole section is missing, either fail for required values
    # or return the provided default.
    if not config.has_section(section):
        if required:
            config_error(f"Missing section [{section}]")
        return default

    # If the option is missing inside an existing section, either fail
    # for required values or return the provided default.
    if not config.has_option(section, option):
        if required:
            config_error(f"Missing option '{option}' in section [{section}]")
        return default

    # Strip whitespace so values like " reboot " are treated as "reboot".
    value = config.get(section, option).strip()

    if required and value == "":
        config_error(f"Option '{option}' in section [{section}] cannot be empty")

    return value


# Read an integer option from the config file.
# It reuses get_str() first, then validates that the value can be converted to int.
def get_int(config, section, option, default=None, required=False):
    value = get_str(config, section, option, default=None, required=required)

    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        config_error(f"Option '{option}' in section [{section}] must be an integer")


# Read a floating point number from the config file.
# Used for timeout and delay values where decimal numbers are allowed.
def get_float(config, section, option, default=None, required=False):
    value = get_str(config, section, option, default=None, required=required)

    if value is None:
        return default

    try:
        return float(value)
    except ValueError:
        config_error(f"Option '{option}' in section [{section}] must be a number")


# Read a boolean option from the config file.
# configparser accepts values like true/false, yes/no, and 1/0.
def get_bool(config, section, option, default=False):
    if not config.has_section(section) or not config.has_option(section, option):
        return default

    try:
        return config.getboolean(section, option)
    except ValueError:
        config_error(f"Option '{option}' in section [{section}] must be true/false, yes/no, or 1/0")


# Choose a password from either a direct config value or an environment variable.
# Direct config password takes priority; password_env is used when password is empty.
def get_password(value: str | None, env_var: str | None) -> str | None:
    if value:
        return value

    if env_var:
        return os.environ.get(env_var)

    return None

# Decide which hostname the script should use in MQTT messages,
# MQTT client IDs, mail subjects, and mail bodies.
def get_config_hostname(config) -> str:
    """
    Preferred hostname comes from [server] hostname.
    Falls back to the real OS hostname if not configured.
    """
    # [server] hostname lets you override the OS hostname in messages.
    configured_hostname = get_str(config, "server", "hostname", default="")

    if configured_hostname:
        return configured_hostname

    # Fallback: use the machine's current OS hostname.
    return socket.gethostname()


# Convert a hostname or text value into something safe for an MQTT client_id.
# This avoids spaces and special characters causing broker/client problems.
def make_safe_id(value: str) -> str:
    """
    Make hostname safe for MQTT client_id.
    Keeps letters, numbers, dash and underscore.
    Replaces everything else with dash.
    """
    # Build a cleaned string character by character.
    safe = ""

    # Lowercase the value and remove leading/trailing whitespace first.
    for char in value.strip().lower():
        if char.isalnum() or char in ["-", "_"]:
            safe += char
        # Normal SMTP connection, usually upgraded with STARTTLS.
        else:
            safe += "-"

    safe = safe.strip("-_")

    if not safe:
        return "unknown-host"

    return safe


# Convert the configured power action into the event name sent to Home Assistant.
# shutdown becomes server_shutdown, reboot becomes server_reboot, none becomes success.
def get_event_name_for_action(action: str) -> str:
    # Translate the configured action into the MQTT event name.
    if action == "shutdown":
        return "server_shutdown"

    if action == "reboot":
        return "server_reboot"

    # none keeps the legacy success event; report.status describes the reported job.
    if action == "none":
        return "success"

    config_error("[power] action must be shutdown, reboot, or none")


# Replace placeholders in config values.
# Example: homeassistant/{safe_hostname}/power becomes host-specific automatically.
def render_template(value: str, config) -> str:
    """
    Allows config values like:
    {hostname}
    {safe_hostname}
    {action}
    {event}
    """
    hostname = get_config_hostname(config)
    safe_hostname = make_safe_id(hostname)
    # Validate the power action early so no wrong command is executed later.
    action = get_str(config, "power", "action", required=True)
    event = get_event_name_for_action(action)

    try:
        return value.format(
            hostname=hostname,
            safe_hostname=safe_hostname,
            action=action,
            event=event,
        )
    except KeyError as e:
        config_error(f"Unknown placeholder in config value: {{{e.args[0]}}}")
    # Catch any other unexpected power-action failure.
    except Exception as e:
        config_error(f"Failed to render config template '{value}': {e}")


# Validate and encode the JSON object consumed by the Home Assistant automation.
# Keeping this shared prevents custom messages from bypassing the report contract.
def encode_mqtt_report(report) -> str:
    if not isinstance(report, dict):
        config_error("MQTT message must be a JSON object")

    if report.get("status") not in ("success", "failure"):
        config_error("MQTT report status must be success or failure")

    # JSON booleans are not exit codes, even though bool subclasses int in Python.
    if "exit_code" in report and type(report["exit_code"]) is not int:
        config_error("MQTT report exit_code must be an integer")
    if "warning" in report and type(report["warning"]) is not bool:
        config_error("MQTT report warning must be a JSON boolean")
    for field in ("title", "name", "job", "error", "stderr"):
        if field in report and not isinstance(report[field], str):
            config_error(f"MQTT report {field} must be a string")

    try:
        # allow_nan=False rejects nonstandard JSON numbers, including in extra fields.
        return json.dumps(report, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        config_error("MQTT report contains a value that cannot be encoded as valid JSON")


# Build an automation-compatible report, retaining the original event/host fields.
# Report values describe the caller's job; they do not predict later mail/power results.
def build_mqtt_message(config) -> str:
    # Watchtower report mode supplies a checked completed-job outcome in memory, shared by MQTT and mail.
    if hasattr(config, 'watchtower_report'):
        return encode_mqtt_report(config.watchtower_report)

    hostname = get_config_hostname(config)
    action = get_str(config, "power", "action", required=True)
    event = get_event_name_for_action(action)

    # "auto" means the script generates the JSON payload itself.
    configured_message = get_str(config, "mqtt", "message", default="auto")

    # Empty message is treated the same as auto.
    if configured_message.lower() == "auto" or configured_message.strip() == "":
        status = get_str(config, "report", "status", default="success").lower()
        title = get_str(config, "report", "title", default="auto")
        if not title or title.lower() == "auto":
            title = f"{hostname}: {action}"
        else:
            title = render_template(title, config)

        # An omitted/auto code follows the reported status, not this process's exit.
        exit_code_value = get_str(config, "report", "exit_code", default="auto")
        if not exit_code_value or exit_code_value.lower() == "auto":
            exit_code = 0 if status == "success" else 1
        else:
            exit_code = get_int(config, "report", "exit_code")

        return encode_mqtt_report(
            {
                "status": status,
                "title": title,
                "exit_code": exit_code,
                "warning": get_bool(config, "report", "warning", default=False),
                "error": get_str(config, "report", "error", default=""),
                "stderr": get_str(config, "report", "stderr", default=""),
                "event": event,
                "host": hostname,
            }
        )

    # Custom messages replace the generated report; validate after template rendering.
    rendered_message = render_template(configured_message, config)
    try:
        report = json.loads(rendered_message)
    except ValueError:
        config_error("[mqtt] message must render to valid JSON; use message = auto or double literal template braces")
    return encode_mqtt_report(report)


# Build the MQTT client ID.
# If [mqtt] client_id is auto or empty, a hostname-based client ID is generated.
def get_mqtt_client_id(config) -> str:
    hostname = get_config_hostname(config)
    safe_hostname = make_safe_id(hostname)

    # client_id can also be auto or a template using placeholders.
    configured_client_id = get_str(
        config,
        "mqtt",
        "client_id",
        default="auto",
    )

    if configured_client_id.lower() == "auto" or configured_client_id.strip() == "":
        return f"mqtt-power-action-{safe_hostname}"

    return render_template(configured_client_id, config)


# Load and validate the config file before any MQTT, mail, or power action happens.
# This catches invalid options early instead of failing halfway through execution.
def load_config(path: str):
    config = configparser.ConfigParser(interpolation=None)

    # config.read() returns a list of files successfully loaded.
    files_read = config.read(path)

    # If no file was read, the path is probably wrong or unreadable.
    if not files_read:
        config_error(f"Could not read config file: {path}")

    action = get_str(config, "power", "action", required=True)

    if action not in ["shutdown", "reboot", "none"]:
        config_error("[power] action must be shutdown, reboot, or none")

    # MQTT QoS must be one of the official MQTT levels.
    qos = get_int(config, "mqtt", "qos", default=1)

    if qos not in [0, 1, 2]:
        config_error("[mqtt] qos must be 0, 1, or 2")

    # Mail can be handled locally by sendmail/Postfix or directly via SMTP.
    mail_backend = get_str(config, "mail", "backend", default="sendmail")

    if mail_backend not in ["sendmail", "smtp"]:
        config_error("[mail] backend must be either sendmail or smtp")

    # These flags decide whether success/failure mails are sent.
    mail_on_success = get_bool(config, "mail", "on_success", default=False)
    mail_on_failure = get_bool(config, "mail", "on_failure", default=False)
    mail_to = get_str(config, "mail", "to", default="")

    if (mail_on_success or mail_on_failure) and not mail_to:
        config_error("[mail] to is required when on_success or on_failure is enabled")

    # SMTP needs login details before it can send mail.
    if (mail_on_success or mail_on_failure) and mail_backend == "smtp":
        smtp_username = get_str(config, "smtp", "username", default="")
        smtp_password = get_str(config, "smtp", "password", default="")
        smtp_password_env = get_str(config, "smtp", "password_env", default="")

        if not smtp_username:
            config_error("[smtp] username is required when [mail] backend = smtp")

        if not smtp_password and not smtp_password_env:
            config_error("[smtp] password or password_env is required when [mail] backend = smtp")

    # Reject malformed report payloads before any MQTT/mail/power side effects.
    build_mqtt_message(config)

    return config


# Create a paho-mqtt client in a way that works with both paho-mqtt v1 and v2.
# v2 uses CallbackAPIVersion.VERSION2, while v1 does not support that argument.
def make_mqtt_client(client_id: str | None):
    """
    Compatible with paho-mqtt v1 and v2.
    """
    try:
        return mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id or "",
        )
    # Fallback for older paho-mqtt versions.
    except (AttributeError, TypeError):
        return mqtt.Client(client_id=client_id or "")


# Normalize different paho-mqtt connection result formats into a simple integer.
# A result of 0 means success; non-zero means failure.
def reason_code_to_int(reason_code) -> int:
    try:
        return int(reason_code)
    except Exception:
        pass

    # Some paho objects store the actual numeric value in .value.
    if hasattr(reason_code, "value"):
        try:
            return int(reason_code.value)
        except Exception:
            pass

    if str(reason_code).lower() in ["success", "0"]:
        return 0

    return 1


# Wait until MQTT publish completes.
# Some paho-mqtt versions support a timeout argument and some do not.
def wait_for_publish_compatible(info, timeout: float):
    try:
        info.wait_for_publish(timeout=timeout)
    except TypeError:
        info.wait_for_publish()


# Connect to the MQTT broker and publish the power-action message.
# Returns a success flag and a human-readable details string.
def publish_mqtt(config) -> tuple[bool, str]:
    # Read all MQTT settings from the config.
    host = get_str(config, "mqtt", "host", required=True)
    port = get_int(config, "mqtt", "port", default=1883)
    username = get_str(config, "mqtt", "username", default="")
    password = get_str(config, "mqtt", "password", default="")
    password_env = get_str(config, "mqtt", "password_env", default="")
    topic = get_str(config, "mqtt", "topic", required=True)
    # Allow the topic to include placeholders like {safe_hostname}.
    topic = render_template(topic, config)

    # Build message and client ID after reading MQTT connection settings.
    message = build_mqtt_message(config)
    client_id = get_mqtt_client_id(config)
    qos = get_int(config, "mqtt", "qos", default=1)
    retain = get_bool(config, "mqtt", "retain", default=False)
    connect_timeout = get_float(config, "mqtt", "connect_timeout", default=10.0)
    publish_timeout = get_float(config, "mqtt", "publish_timeout", default=10.0)

    # Resolve password from config or environment before connecting.
    real_password = get_password(password, password_env)

    # Event object lets the main thread wait until on_connect has fired.
    connected_event = threading.Event()
    # Dict is used so the callback can update the connection result.
    connect_result = {"rc": None}

    # Create a paho client with the generated or configured client_id.
    client = make_mqtt_client(client_id)

    # Only enable MQTT username/password auth when username is set.
    if username:
        client.username_pw_set(username, real_password)

    # Callback called by paho-mqtt after the broker accepts or rejects connection.
    def on_connect(client, userdata, flags, reason_code, properties=None):
        rc = reason_code_to_int(reason_code)
        connect_result["rc"] = rc
        connected_event.set()

    client.on_connect = on_connect

    try:
        # Start the TCP/MQTT connection to the broker.
        client.connect(host, port, keepalive=30)
        # Start the paho network loop so callbacks and publish handling work.
        client.loop_start()

        # Wait for on_connect, but do not wait forever.
        if not connected_event.wait(connect_timeout):
            return False, "Timed out waiting for MQTT connection."

        # Non-zero return code means the broker rejected the connection.
        if connect_result["rc"] != 0:
            return False, f"MQTT broker rejected connection. RC={connect_result['rc']}"

        # Publish the payload to the configured topic.
        info = client.publish(
            topic,
            payload=message,
            qos=qos,
            retain=retain,
        )

        # Immediate publish errors are reported here.
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return False, f"MQTT publish failed. RC={info.rc}"

        # Wait until paho confirms the message was sent.
        wait_for_publish_compatible(info, publish_timeout)

        # If still not published after waiting, treat it as a timeout.
        if not info.is_published():
            return False, "MQTT publish timed out."

        return True, "MQTT message published successfully."

    except Exception as e:
        return False, f"MQTT publish failed: {e}"

    # Always try to disconnect and stop the network loop, even after errors.
    finally:
        try:
            client.disconnect()
            client.loop_stop()
        except Exception:
            pass


# Locate the sendmail binary.
# A custom path from config wins; otherwise common system paths and PATH are checked.
def find_sendmail(path: str | None) -> str | None:
    # A manually configured sendmail path is trusted first.
    if path:
        return path

    # These are common locations for sendmail-compatible binaries.
    for possible_path in ["/usr/sbin/sendmail", "/usr/bin/sendmail"]:
        if os.path.exists(possible_path):
            return possible_path

    return shutil.which("sendmail")


# Build the email body and headers for success or failure notifications.
# This function only creates the message; another function actually sends it.
def build_mail_message(config, mail_type: str, details: str) -> EmailMessage:
    hostname = get_config_hostname(config)

    action = get_str(config, "power", "action", required=True)

    # Include MQTT topic/message in the mail body for troubleshooting.
    mqtt_topic = render_template(
        get_str(config, "mqtt", "topic", default=""),
        config,
    )
    mqtt_message = build_mqtt_message(config)
    
    # Check which mail backend the config selected.
    backend = get_str(config, "mail", "backend", default="sendmail")
    mail_to = get_str(config, "mail", "to", required=True)
    mail_from = get_str(config, "mail", "from", default="")
    extra_body = get_str(config, "mail", "extra_body", default="")

    # For SMTP, default sender can be the SMTP username.
    if not mail_from and backend == "smtp":
        mail_from = get_str(config, "smtp", "username", default="")

    # Final fallback sender address for local sendmail/Postfix.
    if not mail_from:
        mail_from = f"root@{hostname}"
    # Choose subject template based on success or failure.
    if mail_type == "success":
        subject = get_str(
            config,
            "mail",
            "success_subject",
            default="{hostname}: SUCCESS MQTT before {action}",
        )
    # Failure path: optionally send failure mail and maybe abort.
    else:
        subject = get_str(
            config,
            "mail",
            "failure_subject",
            default="{hostname}: FAILURE MQTT/power action",
        )

    # Allow mail subject to use placeholders like {hostname} and {action}.
    subject = render_template(subject, config)

    # Plain-text mail body with the most useful status information.
    body = f"""Power action script status: {mail_type.upper()}

Host: {hostname}
Action: {action}

MQTT topic: {mqtt_topic}
MQTT message: {mqtt_message}

Details:
{details}
"""

    # Optional extra static text from the config is appended to the message.
    if extra_body:
        body += f"""

Extra info:
{extra_body}
"""

    # Build a standard Python EmailMessage object.
    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg["Subject"] = subject
    msg.set_content(body)

    return msg


# Send mail using local sendmail/Postfix.
# This is useful when the server already has local mail delivery configured.
def send_mail_sendmail(config, msg: EmailMessage, mail_type: str) -> bool:
    # Read optional custom sendmail path from config.
    sendmail_path = get_str(config, "sendmail", "path", default="")
    sendmail_bin = find_sendmail(sendmail_path)

    if not sendmail_bin:
        print("ERROR: Could not find sendmail. Install postfix or set [sendmail] path.")
        return False

    try:
        # Feed the complete mail message to sendmail -t.
        subprocess.run(
            [sendmail_bin, "-t"],
            input=msg.as_bytes(),
            check=True,
            capture_output=True,
        )

        print(f"{mail_type.capitalize()} mail sent using sendmail.")
        return True

    # systemctl returned a non-zero exit code.
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else ""
        print(f"ERROR: Failed to send {mail_type} mail using sendmail. Exit code: {e.returncode}")

        if stderr:
            print(stderr)

        return False

    except Exception as e:
        print(f"ERROR: Failed to send {mail_type} mail using sendmail: {e}")
        return False


# Send mail directly through an SMTP server.
# Supports normal STARTTLS on port 587 and SSL SMTP when configured.
def send_mail_smtp(config, msg: EmailMessage, mail_type: str) -> bool:
    # Read SMTP server settings from config.
    host = get_str(config, "smtp", "host", default="smtp.gmail.com")
    port = get_int(config, "smtp", "port", default=587)
    username = get_str(config, "smtp", "username", required=True)
    password = get_str(config, "smtp", "password", default="")
    password_env = get_str(config, "smtp", "password_env", default="")
    use_ssl = get_bool(config, "smtp", "ssl", default=False)
    use_starttls = get_bool(config, "smtp", "starttls", default=True)
    timeout = get_float(config, "smtp", "timeout", default=20.0)

    real_password = get_password(password, password_env)

    # SMTP cannot continue without a resolved password.
    if not real_password:
        print("ERROR: SMTP password missing. Set [smtp] password or password_env.")
        return False

    try:
        # SMTP_SSL connects with TLS from the beginning.
        if use_ssl:
            context = ssl.create_default_context()

            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as server:
                server.login(username, real_password)
                server.send_message(msg)

        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()

                # STARTTLS upgrades the connection before login.
                if use_starttls:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                    server.ehlo()

                server.login(username, real_password)
                server.send_message(msg)

        print(f"{mail_type.capitalize()} mail sent using SMTP.")
        return True

    except Exception as e:
        print(f"ERROR: Failed to send {mail_type} mail using SMTP: {e}")
        return False


# Pick the configured mail backend and send the prepared email.
# [mail] backend decides whether sendmail or SMTP is used.
def send_mail(config, mail_type: str, details: str) -> bool:
    backend = get_str(config, "mail", "backend", default="sendmail")
    # Build the message once, then pass it to the selected sender.
    msg = build_mail_message(config, mail_type, details)

    if backend == "sendmail":
        return send_mail_sendmail(config, msg, mail_type)

    if backend == "smtp":
        return send_mail_smtp(config, msg, mail_type)

    print(f"ERROR: Unknown mail backend: {backend}")
    return False


# Perform the configured power action.
# action=none is notification-only mode and deliberately runs no systemctl command.
# In dry_run mode, shutdown/reboot only print the command instead of executing it.
def run_power_action(config):
    action = get_str(config, "power", "action", required=True)
    # none intentionally stops after MQTT/mail and never calls systemctl.
    if action == "none":
        print("No power action configured (action=none). MQTT/mail processing completed.")
        return

    # dry_run is a safety option for testing without actually powering off.
    dry_run = get_bool(config, "power", "dry_run", default=False)

    if action == "shutdown":
        command = ["systemctl", "poweroff"]
    elif action == "reboot":
        command = ["systemctl", "reboot"]
    else:
        raise ValueError(f"Unknown action: {action}")

    # In dry-run mode the script stops before running systemctl.
    if dry_run:
        print(f"DRY-RUN: Would run: {' '.join(command)}")
        return

    print(f"Running: {' '.join(command)}")
    subprocess.run(command, check=True)


def redact_watchtower_text(text, config):
    """Remove known mail/MQTT secrets and URL credentials before forwarding diagnostics."""
    text = str(text)
    secrets = [os.environ.get('WATCHTOWER_NOTIFICATION_EMAIL_SERVER_PASSWORD', '')]
    for section in ('mqtt', 'smtp'):
        secrets.append(get_password(get_str(config, section, 'password', default=''),
                                    get_str(config, section, 'password_env', default='')))
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, '[redacted]')
    text = re.sub(r'(\w+://)[^\s/@]+:[^\s/@]+@', r'\1[redacted]@', text)
    return re.sub(r'(?i)(password[=:]\s*)[^\s,;]+', r'\1[redacted]', text)


def inspect_watchtower_output(output, returncode, config):
    """Restore the strict session check and extract explicit container failures, without guessing names."""
    sessions, errors, failed_containers = [], [], []
    warning = False
    for line in output.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue  # Compose progress is plain text; absence of a session still fails.
        if not isinstance(record, dict):
            continue
        message = str(record.get('msg', ''))
        level = str(record.get('level', '')).lower()
        warning = warning or level in ('warning', 'warn')
        if message == 'Session done':
            sessions.append(record)
        # Watchtower logs failed image checks at INFO rather than ERROR.
        match = re.match(r'^Unable to update container "([^"\r\n]+)": (.*)', message)
        if level in ('error', 'fatal', 'panic') or match:
            detail = message
            if record.get('error'):
                detail += ': ' + str(record['error'])
            detail = redact_watchtower_text(detail, config)
            errors.append(detail)
            name = match.group(1) if match else record.get('container')
            if isinstance(name, str) and name:
                entry = {'name': redact_watchtower_text(name, config), 'error': detail}
                for field in ('container_id', 'image'):
                    if isinstance(record.get(field), str):
                        entry[field] = redact_watchtower_text(record[field], config)
                if entry not in failed_containers:
                    failed_containers.append(entry)

    session = sessions[0] if len(sessions) == 1 else {}
    valid = bool(session) and all(type(session.get(k)) is int and session[k] >= 0
                                  for k in ('Scanned', 'Updated', 'Failed'))
    valid = valid and session['Updated'] <= session['Scanned']
    reasons = []
    if returncode != 0:
        reasons.append(f'Compose/Watchtower exited with code {returncode}')
    if not valid:
        reasons.append('Missing, duplicate or invalid completed-session summary')
    elif session['Failed']:
        reasons.append(f"Watchtower reported {session['Failed']} failed container update(s)")
    if errors:
        reasons.append('Watchtower logged an error or an unsuccessful container update')
    if failed_containers:
        reasons.append('Containers: ' + ', '.join(dict.fromkeys(x['name'] for x in failed_containers)))
    elif reasons:
        reasons.append('Failed container names unavailable in output')

    failed = bool(reasons)
    title = get_str(config, 'report', 'title', default='auto')
    if not title or title.lower() == 'auto':
        title = get_config_hostname(config) + ': Watchtower update'
    else:
        title = render_template(title, config)
    error = '; '.join(reasons)
    diagnostic = '\n'.join(errors) if errors else (output.strip() if failed else '')
    diagnostic = redact_watchtower_text(diagnostic, config)
    # Keep the existing HA/Pushover text fields short; complete logs remain in the journal.
    report = {
        'status': 'failure' if failed else 'success',
        'title': redact_watchtower_text(title, config)[:120],
        'exit_code': (returncode or 1) if failed else 0,
        'warning': warning,
        'error': error[:240], 'stderr': diagnostic[:500] if errors else diagnostic[-500:],
        'event': 'watchtower_completed', 'host': get_config_hostname(config),
        'compose_exit_code': returncode,
        'scanned': session['Scanned'] if valid else None,
        'updated': session['Updated'] if valid else None,
        'failed': session['Failed'] if valid else None,
        'failed_containers': [{k: v[:400] for k, v in c.items()} for c in failed_containers[:20]],
        'details_truncated': len(error) > 240 or len(diagnostic) > 500 or
                             len(failed_containers) > 20 or
                             any(len(v) > 400 for c in failed_containers for v in c.values()),
    }
    return report


def parse_compose_exit_code(output, service):
    """Return the completed Compose service exit code from `docker compose ps --format json`."""
    text = (output or '').strip()
    if not text:
        return None

    records = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            records.extend(item for item in parsed if isinstance(item, dict))
        elif isinstance(parsed, dict):
            records.append(parsed)
    except ValueError:
        # Some Compose versions emit one JSON object per line instead of one array.
        for line in text.splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                records.append(item)

    matching = [record for record in records if record.get('Service') == service]
    if not matching and len(records) == 1:
        matching = records
    if len(matching) != 1:
        return None

    value = matching[0].get('ExitCode')
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r'-?\d+', value.strip()):
        return int(value.strip())
    return None


def report_watchtower(config, compose_file, service='watchtower'):
    """Inspect the completed systemd-owned Compose job and publish exactly one outcome report."""
    if get_str(config, 'power', 'action', required=True) != 'none':
        config_error('Watchtower report mode requires [power] action = none; Home Assistant owns shutdown')
    if get_str(config, 'mqtt', 'message', default='auto').lower() not in ('', 'auto'):
        config_error('Watchtower report mode requires [mqtt] message = auto')
    if get_bool(config, 'mqtt', 'retain', default=False):
        config_error('Watchtower report mode requires [mqtt] retain = false')
    if not service or service.startswith('-'):
        config_error('Watchtower Compose service must be nonempty and not start with a dash')

    # systemd already ran and waited for Compose. This post-start phase only reads
    # the completed container status and logs; it never starts, pulls, or restarts it.
    ps_command = ['/usr/bin/docker', 'compose', '-f', compose_file,
                  'ps', '-a', '--format', 'json', service]
    logs_command = ['/usr/bin/docker', 'compose', '-f', compose_file,
                    'logs', '--no-color', '--no-log-prefix', service]

    ps_output = ''
    ps_rc = 1
    try:
        ps_result = subprocess.run(ps_command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace')
        ps_output, ps_rc = ps_result.stdout or '', ps_result.returncode
    except OSError as error:
        ps_output = f'Could not inspect Docker Compose service status: {error}'

    compose_exit_code = parse_compose_exit_code(ps_output, service) if ps_rc == 0 else None
    if compose_exit_code is None:
        compose_exit_code = ps_rc if ps_rc != 0 else 1

    log_output = ''
    logs_rc = 1
    try:
        logs_result = subprocess.run(logs_command, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding='utf-8', errors='replace')
        log_output, logs_rc = logs_result.stdout or '', logs_result.returncode
    except OSError as error:
        log_output = f'Could not read Docker Compose service logs: {error}'

    # If log retrieval itself fails, make the completed job unverifiable even if
    # Compose reported exit 0. Include inspection diagnostics in the bounded report.
    output = log_output
    if logs_rc != 0:
        output = (log_output + '\n' + ps_output).strip()
        if compose_exit_code == 0:
            compose_exit_code = logs_rc or 1

    print(redact_watchtower_text(output, config), flush=True)
    report = inspect_watchtower_output(output, compose_exit_code, config)
    config.watchtower_report = report

    try:
        mqtt_ok, details = publish_mqtt(config)
    except Exception as error:
        mqtt_ok, details = False, f'MQTT reporting failed: {error}'
    print(redact_watchtower_text(details, config), flush=True)

    mail_type = 'failure' if report['status'] == 'failure' or not mqtt_ok else 'success'
    mail_ok = True
    if get_bool(config, 'mail', 'on_' + mail_type, default=False):
        try:
            mail_ok = send_mail(config, mail_type, details)
        except Exception as error:
            mail_ok = False
            print(redact_watchtower_text(f'Mail reporting failed: {error}', config))

    # ExecStartPost returns failure when the update/report was unsuccessful so
    # systemd still exposes a failed unit even though ExecStart is prefixed with '-'.
    return 0 if report['status'] == 'success' and mqtt_ok and mail_ok else 1


# Parse command-line arguments.
# The config file path is required so the script knows what settings to use.
def parse_args():
    # Create the command-line parser shown when using --help.
    parser = argparse.ArgumentParser(
        description="Send MQTT, then optionally shutdown/reboot, using a config file."
    )

    # Require the path to the config file.
    parser.add_argument(
        "-c",
        "--config",
        required=True,
        help="Path to config file.",
    )

    parser.add_argument('--watchtower-compose', metavar='FILE', help='Inspect the completed Watchtower Compose job at FILE and publish its verified outcome; this does not start Docker.')
    parser.add_argument('--watchtower-service', default='watchtower', help='Compose service name for Watchtower mode (default: watchtower).')
    return parser.parse_args()


# Main program flow:
# 1. Parse arguments.
# 2. Load and validate config.
# 3. Publish MQTT.
# 4. Send optional mail.
# 5. Wait if configured.
# 6. Run shutdown/reboot, or do nothing when action=none.
def main():
    # Read command-line arguments first.
    args = parse_args()
    # Load and validate config before doing any external actions.
    config = load_config(args.config)
    if getattr(args, 'watchtower_compose', None):
        sys.exit(report_watchtower(config, args.watchtower_compose, args.watchtower_service))

    mail_on_success = get_bool(config, "mail", "on_success", default=False)
    mail_on_failure = get_bool(config, "mail", "on_failure", default=False)

    # These flags decide whether to continue or abort after MQTT/mail failures.
    continue_on_mqtt_fail = get_bool(config, "power", "continue_on_mqtt_fail", default=False)
    continue_on_mail_fail = get_bool(config, "power", "continue_on_mail_fail", default=False)

    action = get_str(config, "power", "action", required=True)

    # Optional delay gives Home Assistant/mail time before shutdown/reboot.
    # There is no reason to wait in notification-only mode because no power action follows.
    delay_before_action = get_float(config, "power", "delay_before_action", default=1.0)

    # Send the MQTT message before doing the power action.
    mqtt_ok, mqtt_details = publish_mqtt(config)

    print(mqtt_details)

    # Success path: optionally send success mail.
    if mqtt_ok:
        if mail_on_success:
            mail_ok = send_mail(config, "success", mqtt_details)

            if not mail_ok:
                if mail_on_failure:
                    send_mail(config, "failure", "Success mail failed after MQTT succeeded.")

                if not continue_on_mail_fail:
                    print("Aborting power action because success mail failed.")
                    sys.exit(1)

    else:
        if mail_on_failure:
            send_mail(config, "failure", mqtt_details)

        if not continue_on_mqtt_fail:
            print("Aborting power action because MQTT publish failed.")
            sys.exit(1)

    # Wait only when a real power action will follow.
    # action=none finishes immediately after MQTT/mail processing.
    if action != "none" and delay_before_action > 0:
        time.sleep(delay_before_action)

    try:
        run_power_action(config)

    except subprocess.CalledProcessError as e:
        details = f"Power action failed with exit code {e.returncode}"
        print(f"ERROR: {details}")

        if mail_on_failure:
            send_mail(config, "failure", details)

        sys.exit(e.returncode)

    except Exception as e:
        details = f"Power action failed: {e}"
        print(f"ERROR: {details}")

        if mail_on_failure:
            send_mail(config, "failure", details)

        sys.exit(1)


# Only run main() when this file is executed directly.
# This prevents the script from running automatically if imported by another Python file.
if __name__ == "__main__":
    main()
