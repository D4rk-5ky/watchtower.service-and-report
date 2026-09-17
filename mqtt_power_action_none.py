#!/usr/bin/env python3
from __future__ import annotations

# Report completed Watchtower jobs, or notify before an optional shutdown/reboot.
# It can also send success/failure mail through either local sendmail/Postfix or SMTP.
# The behavior is controlled by an external config file passed with -c / --config.

# Standard library imports used for config parsing, mail, networking,
# subprocess calls, timing, and command-line arguments.
import argparse
import configparser
import datetime
import math
import os
import shutil
import smtplib
import socket
import ssl
import subprocess
import sys
import time
from email.message import EmailMessage
import json
import re
import shlex

__version__ = "0.0.17"


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


def feature_enabled(config, section):
    """Omitted channels are disabled; existing sections default to enabled."""
    return config.has_section(section) and get_bool(config, section, "enabled", True)


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
        else:
            safe += "-"

    safe = safe.strip("-_")

    if not safe:
        return "unknown-host"

    return safe


# Convert the configured power action into the event name sent to Home Assistant.
# shutdown becomes server_shutdown, reboot becomes server_reboot.
def get_event_name_for_action(action: str) -> str:
    # Translate the config action into the actual systemctl command.
    if action == "none":
        return "success"

    if action == "shutdown":
        return "server_shutdown"

    if action == "reboot":
        return "server_reboot"

    config_error("[power] action must be none, shutdown, or reboot")


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


def encode_mqtt_report(report):
    """Validate the consumer contract and serialize strict, UTF-8 JSON."""
    if not isinstance(report, dict) or report.get("status") not in ("success", "failure"):
        config_error("MQTT message must be a JSON object with status success or failure")
    for key, kind in {"exit_code": int, "warning": bool, "success": bool,
                      "title": str, "name": str, "job": str, "error": str,
                      "stderr": str}.items():
        if key in report and type(report[key]) is not kind:
            config_error(f"MQTT field {key} must be {kind.__name__}")
    if "success" in report and report["success"] != (report["status"] == "success"):
        config_error("MQTT success must agree with status")
    try:
        return json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError):
        config_error("MQTT message must contain finite JSON values")


def build_mqtt_report(config, exit_code=None, error=None, warning=None,
                      phase="before_action") -> dict:
    """Use Syncerate's typed status fields without claiming power completion."""
    hostname = get_config_hostname(config)
    action = get_str(config, "power", "action", required=True)
    status = get_str(config, "report", "status", "success").lower()
    if status not in ("success", "failure"):
        config_error("[report] status must be success or failure")
    if exit_code is None:
        configured_code = get_str(config, "report", "exit_code", "auto").lower()
        exit_code = (0 if status == "success" else 1) if configured_code in ("", "auto") else get_int(config, "report", "exit_code")
    status = "success" if exit_code == 0 else "failure"
    title = get_str(config, "report", "title", "auto")
    if title.lower() in ("", "auto"):
        title = "{hostname}: {action}"
    title = render_template(title, config)
    stderr = ((getattr(error, "stderr", "") or getattr(error, "stdout", "") or "")
              if error is not None else get_str(config, "report", "stderr", ""))
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    dry_run = get_bool(config, "power", "dry_run", False)
    return {
        "status": status, "success": status == "success",
        "title": title, "name": title,
        "job": render_template(get_str(config, "report", "job", "") or "mqtt-power-action", config),
        "exit_code": exit_code,
        "warning": get_bool(config, "report", "warning", False) if warning is None else bool(warning),
        "error": str(error) if error is not None else get_str(config, "report", "error", ""),
        "stderr": stderr[-4000:], "skipped_datasets": [],
        "command": action, "dry_run": dry_run,
        "comment": get_str(config, "report", "comment", ""),
        "version": __version__,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event": get_event_name_for_action(action), "host": hostname, "action": action,
        "phase": "dry_run" if dry_run else ("reported_result" if action == "none" else phase),
        "message": (str(error) if error is not None else
                    "Dry run only; no local action requested." if dry_run else
                    "Caller-supplied job result." if action == "none" else
                    f"Ready to request {action}; this does not confirm completion."),
    }


def build_mqtt_message(config, report=None, force_auto=False) -> str:
    """Reuse one serializer for ordinary, custom, mail, and verified Watchtower reports."""
    runtime_report = getattr(config, "watchtower_report", None)
    if runtime_report is not None:
        return encode_mqtt_report(runtime_report)
    configured = get_str(config, "mqtt", "message", "auto")
    if force_auto or configured.lower() in ("", "auto"):
        return encode_mqtt_report(report if report is not None else build_mqtt_report(config))
    try:
        report = json.loads(render_template(configured, config))
    except ValueError:
        config_error("[mqtt] message must render to valid JSON")
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


def describe_config_parse_error(error, path: str) -> str:
    """Return a useful INI error without echoing config values or secrets."""
    line = getattr(error, "lineno", None)
    location = f" at line {line}" if line else ""

    if isinstance(error, configparser.DuplicateOptionError):
        return (f"Duplicate option '{error.option}' in section [{error.section}]{location} of {path}. "
                "Each option may appear only once.")
    if isinstance(error, configparser.DuplicateSectionError):
        return (f"Duplicate section [{error.section}]{location} of {path}. "
                "Each section may appear only once.")
    if isinstance(error, configparser.MissingSectionHeaderError):
        return f"Expected an INI section header such as [server] before{location} of {path}."
    if isinstance(error, configparser.ParsingError):
        line_numbers = [str(item[0]) for item in getattr(error, "errors", []) if item]
        suffix = f" at line(s) {', '.join(line_numbers)}" if line_numbers else location
        return f"Could not parse INI syntax{suffix} of {path}."
    return f"Could not parse config file as INI: {path}."


# Load and validate the config file before any MQTT, mail, or power action happens.
# This catches invalid options early instead of failing halfway through execution.
def load_config(path: str):
    # Keep ConfigParser's strict duplicate detection. Conflicting duplicate values
    # must fail closed instead of silently choosing one of them.
    config = configparser.ConfigParser(interpolation=None, strict=True)

    # config.read() returns a list of files successfully loaded. UTF-8 keeps
    # configured host names/comments deterministic across system locales.
    try:
        files_read = config.read(path, encoding="utf-8")
    except configparser.Error as error:
        config_error(describe_config_parse_error(error, path))
    except UnicodeError:
        config_error(f"Could not decode config file as UTF-8: {path}")
    except OSError:
        config_error(f"Could not read config file: {path}")

    # If no file was read, the path is probably wrong or unreadable.
    if not files_read:
        config_error(f"Could not read config file: {path}")

    action = get_str(config, "power", "action", required=True)

    if action not in ["none", "shutdown", "reboot"]:
        config_error("[power] action must be none, shutdown, or reboot")

    delay = get_float(config, "power", "delay_before_action", 1.0)
    if not math.isfinite(delay) or delay < 0:
        config_error("[power] delay_before_action must be finite and nonnegative")
    for key in ("dry_run", "continue_on_mqtt_fail", "continue_on_mail_fail"):
        get_bool(config, "power", key)
    build_mqtt_message(config, force_auto=True)
    if feature_enabled(config, "mqtt"):
        # MQTT QoS must be one of the official MQTT levels.
        qos = get_int(config, "mqtt", "qos", default=1)

        if qos not in [0, 1, 2]:
            config_error("[mqtt] qos must be 0, 1, or 2")

        host = get_str(config, "mqtt", "host", required=True)
        if "\x00" in host:
            config_error("[mqtt] host cannot contain NUL")
        topic = render_template(get_str(config, "mqtt", "topic", required=True), config)
        if not topic or any(char in topic for char in "+#\x00") or len(topic.encode("utf-8")) > 65535:
            config_error("[mqtt] topic must be nonempty, without wildcards or NUL, and at most 65535 UTF-8 bytes")
        port = get_int(config, "mqtt", "port", default=1883)
        if not 1 <= port <= 65535:
            config_error("[mqtt] port must be between 1 and 65535")
        if get_bool(config, "mqtt", "retain", default=False):
            config_error("[mqtt] retain must be false for power status reports")
        for key in ("timeout", "connect_timeout", "publish_timeout"):
            value = get_float(config, "mqtt", key, default=10.0)
            if not math.isfinite(value) or value <= 0:
                config_error(f"[mqtt] {key} must be a finite positive number")
        get_bool(config, "mqtt", "publish_dry_run")
        get_mqtt_client_id(config)
        build_mqtt_message(config)


    if feature_enabled(config, "mail"):
        get_bool(config, "mail", "send_dry_run", False)
        backend = get_str(config, "mail", "backend", "sendmail")
        if backend not in ("sendmail", "smtp"):
            config_error("[mail] backend must be sendmail or smtp")
        active = get_bool(config, "mail", "on_success") or get_bool(config, "mail", "on_failure")
        if active:
            get_str(config, "mail", "to", required=True)
        if active and backend == "smtp":
            get_str(config, "smtp", "username", required=True)
            if not (get_str(config, "smtp", "password", "") or get_str(config, "smtp", "password_env", "")):
                config_error("[smtp] password or password_env is required")
            port = get_int(config, "smtp", "port", 587)
            timeout = get_float(config, "smtp", "timeout", 20.0)
            if not 1 <= port <= 65535 or not math.isfinite(timeout) or timeout <= 0:
                config_error("[smtp] port/timeout invalid")
            get_bool(config, "smtp", "ssl")
            get_bool(config, "smtp", "starttls", True)

    return config


# Preserve the supplied bounded subprocess publisher. This bounds DNS,
# connection and acknowledgement stalls, not just the MQTT callback wait.
def publish_mqtt(config, report=None, force_report=False) -> tuple[bool, str]:
    if not feature_enabled(config, "mqtt"):
        return True, "MQTT disabled by configuration."
    if (get_bool(config, "power", "dry_run", default=False)
            and not get_bool(config, "mqtt", "publish_dry_run", default=False)):
        return True, "DRY-RUN: MQTT publishing skipped."
    request = {
        "host": get_str(config, "mqtt", "host", required=True),
        "port": get_int(config, "mqtt", "port", default=1883),
        "username": get_str(config, "mqtt", "username", default=""),
        "password": get_password(
            get_str(config, "mqtt", "password", default=""),
            get_str(config, "mqtt", "password_env", default="")),
        "topic": render_template(get_str(config, "mqtt", "topic", required=True), config),
        "message": (encode_mqtt_report(report) if force_report
                    else build_mqtt_message(config, report)),
        "client_id": get_mqtt_client_id(config),
        "qos": get_int(config, "mqtt", "qos", default=1),
    }
    timeout = get_float(config, "mqtt", "timeout", default=(
        get_float(config, "mqtt", "connect_timeout", default=10.0)
        + get_float(config, "mqtt", "publish_timeout", default=10.0)))
    try:
        result = subprocess.run(
            [sys.executable, "-B", os.path.abspath(__file__), "--mqtt-publish"],
            input=json.dumps(request), text=True, encoding="utf-8",
            capture_output=True, timeout=timeout, check=False,
        )
        if result.returncode:
            # Library errors may contain credentials: do not echo worker output.
            return False, ("MQTT publish failed; check paho-mqtt installation, "
                           "broker and credentials.")
        return True, "MQTT message published successfully."
    except subprocess.TimeoutExpired:
        return False, "MQTT publish timed out."
    except Exception:
        return False, "Could not start MQTT publisher."


def publish_worker():
    from paho.mqtt.publish import single

    request = json.load(sys.stdin)
    auth = None
    if request["username"]:
        auth = {"username": request["username"], "password": request["password"]}
    single(request["topic"], payload=request["message"], hostname=request["host"],
           port=request["port"], client_id=request["client_id"], qos=request["qos"],
           retain=False, auth=auth)


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
    mqtt_topic = (render_template(get_str(config, "mqtt", "topic", ""), config)
                  if feature_enabled(config, "mqtt") else "disabled")
    mqtt_message = build_mqtt_message(config, force_auto=not feature_enabled(config, "mqtt"))

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
            default="{hostname}: Ready for {action}",
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
    msg["Subject"] = ("[DRY-RUN] " if get_bool(config, "power", "dry_run", False) else "") + subject
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
    if not feature_enabled(config, "mail") or (get_bool(config, "power", "dry_run", False)
            and not get_bool(config, "mail", "send_dry_run", False)):
        return True
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
# In dry_run mode, it only prints the command instead of shutting down/rebooting.
def run_power_action(config):
    action = get_str(config, "power", "action", required=True)
    # dry_run is a safety option for testing without actually powering off.
    dry_run = get_bool(config, "power", "dry_run", default=False)

    if action == "none":
        print("No local power action requested.")
        return
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
    subprocess.run(command, check=True, capture_output=True, text=True)


def redact_watchtower_text(text, config):
    """Remove configured secrets and common credential forms before forwarding logs."""
    text = str(text)
    for section in ("mqtt", "smtp"):
        for secret in (get_str(config, section, "password", ""),
                       os.environ.get(get_str(config, section, "password_env", ""), "")):
            if secret:
                text = text.replace(secret, "[redacted]")
    text = re.sub(r"(://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", text)
    return re.sub(r'''(?i)((?:password|passwd|token|secret)\s*[=:]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)''',
                  r"\1[redacted]", text)


def parse_watchtower_log_record(line):
    """Accept JSON and LogFmt logs; never coerce JSON booleans into counters."""
    try:
        record = json.loads(line)
        return record if isinstance(record, dict) else None
    except ValueError:
        pass
    try:
        record = dict(token.split("=", 1) for token in shlex.split(line) if "=" in token)
    except ValueError:
        return None
    if "msg" not in record or "level" not in record:
        return None
    for key in ("Scanned", "Updated", "Failed"):
        if key in record and re.fullmatch(r"[0-9]+", record[key]):
            record[key] = int(record[key])
    return record


def inspect_watchtower_output(output, returncode, config):
    """Fail closed unless exactly one complete session and zero failures are verified."""
    sessions, failures, diagnostics, errors = [], [], [], []
    warning = False
    for line in output.splitlines():
        if not line.strip():
            continue
        record = parse_watchtower_log_record(line)
        if record is None:
            errors.append("Unrecognized Watchtower log record")
            diagnostics.append(line)
            continue
        message = str(record.get("msg", ""))
        level = str(record.get("level", "")).lower()
        if message == "Session done":
            sessions.append(record)
        if level in ("warning", "warn"):
            warning = True
        if level in ("error", "fatal", "panic"):
            errors.append("Watchtower logged an error")
            diagnostics.append(message)
        if "Unable to update container" in message:
            match = re.search(r'''Unable to update container\s+["']([^"']+)["']''', message)
            failures.append({"name": match.group(1) if match else "unavailable", "error": message})
            errors.append("Watchtower could not update a container")
            diagnostics.append(message)
    counters = {"scanned": None, "updated": None, "failed": None}
    if len(sessions) != 1:
        errors.append("Expected exactly one completed Watchtower Session done record")
    else:
        session = sessions[0]
        valid = all(type(session.get(key)) is int and session[key] >= 0
                    for key in ("Scanned", "Updated", "Failed"))
        if not valid:
            errors.append("Invalid Watchtower session counters")
        else:
            counters = {key.lower(): session[key] for key in ("Scanned", "Updated", "Failed")}
            if session["Updated"] > session["Scanned"] or session["Failed"] > session["Scanned"]:
                errors.append("Inconsistent Watchtower session counters")
            if session["Failed"]:
                errors.append(f'{session["Failed"]} failed container update(s)')
    if type(returncode) is not int or returncode < 0:
        errors.append("Completed Compose exit code could not be verified")
    elif returncode != 0:
        errors.append(f"Compose exited with code {returncode}")
    success = not errors
    code = 0 if success else (returncode if type(returncode) is int and returncode > 0 else 1)
    # Metadata comes from the common builder; outcome fields always come from inspection.
    report = build_mqtt_report(config, exit_code=code, error="; ".join(dict.fromkeys(errors)),
                               warning=warning, phase="completed")
    title = get_str(config, "report", "title", "auto")
    report.update(title=(f"{get_config_hostname(config)}: Watchtower" if title.lower() in ("", "auto")
                         else render_template(title, config)), job="watchtower")
    diagnostic = redact_watchtower_text("\n".join(diagnostics), config)
    report.update(name=report["title"], phase="dry_run" if report["dry_run"] else "completed",
                  command="watchtower", compose_exit_code=returncode, **counters,
                  error=redact_watchtower_text(report["error"], config), stderr=diagnostic[-4000:],
                  failed_containers=[{"name": redact_watchtower_text(item["name"], config)[:256],
                                      "error": redact_watchtower_text(item["error"], config)[:1000]}
                                     for item in failures[:20]],
                  details_truncated=(len(diagnostic) > 4000 or len(failures) > 20 or
                                     any(len(item["name"]) > 256 or len(item["error"]) > 1000 for item in failures)),
                  message="Watchtower completed successfully." if success else "Watchtower failed or could not be verified.")
    return report


def _read_runtime_text(path, label):
    """Read a small runtime marker without executing its contents."""
    try:
        with open(path, encoding="utf-8") as handle:
            value = handle.read(4097).strip()
        if not value or len(value) > 4096:
            raise ValueError("empty or oversized marker")
        return value, None
    except (OSError, UnicodeError, ValueError):
        return None, f"Could not read {label} marker"


def parse_compose_exit_code(output, service):
    """Handle Compose object/array/JSON-lines output; require one stopped service."""
    try:
        try:
            records = json.loads(output)
            records = records if isinstance(records, list) else [records]
        except ValueError:
            records = [json.loads(line) for line in output.splitlines() if line.strip()]
        matches = [item for item in records if isinstance(item, dict) and item.get("Service") == service]
        if len(matches) != 1 or matches[0].get("State", "exited") not in ("exited", "dead"):
            return None
        code = matches[0].get("ExitCode")
        if type(code) is int and 0 <= code <= 255:
            return code
        if type(code) is str and re.fullmatch(r"[0-9]{1,3}", code) and int(code) <= 255:
            return int(code)
    except (ValueError, TypeError):
        pass
    return None


def report_watchtower(config, compose_file, service="watchtower", since_file=None, exit_code_file=None):
    """Inspect only the finished run, then attempt one non-retained result report."""
    if str(compose_file).startswith("WorkingDirectory="):
        config_error("--watchtower-compose expects only the Compose YAML path; "
                     "WorkingDirectory= is a separate systemd unit directive")
    if get_str(config, "power", "action", required=True) != "none":
        config_error("Watchtower reporting requires [power] action = none")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", service):
        config_error("Invalid Watchtower Compose service name")
    if bool(since_file) != bool(exit_code_file):
        config_error("Both Watchtower runtime markers are required together")
    if feature_enabled(config, "mqtt"):
        if get_bool(config, "mqtt", "retain") or get_str(config, "mqtt", "message", "auto").lower() not in ("", "auto"):
            config_error("Watchtower reporting requires mqtt.message = auto and mqtt.retain = false")
    base = ["docker", "compose", "-f", os.path.abspath(compose_file)]
    output, code, problems, since = "", None, [], None
    if since_file:
        since, problem = _read_runtime_text(since_file, "start timestamp")
        raw_code, code_problem = _read_runtime_text(exit_code_file, "Compose exit code")
        problems.extend(value for value in (problem, code_problem) if value)
        try:
            stamp = datetime.datetime.fromisoformat((since or "").replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("timezone required")
        except ValueError:
            problems.append("Invalid current-run start timestamp")
        if raw_code is not None and re.fullmatch(r"[0-9]{1,3}", raw_code) and int(raw_code) <= 255:
            code = int(raw_code)
        else:
            problems.append("Invalid current-run Compose exit code")
    if not problems:
        try:
            if not since_file:
                result = subprocess.run(base + ["ps", "--all", "--format", "json", service],
                                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
                code = parse_compose_exit_code(result.stdout, service) if result.returncode == 0 else None
            command = base + ["logs", "--no-color", "--no-log-prefix"]
            if since:
                command += ["--since", since]
            result = subprocess.run(command + [service], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=30, check=False)
            output = result.stdout
            if result.returncode:
                problems.append("Could not read completed Watchtower logs")
        except Exception:
            problems.append("Docker inspection failed or timed out")
    report = inspect_watchtower_output(output, code, config)
    if problems:
        report.update(status="failure", success=False, exit_code=code if code else 1,
                      error="; ".join(problems), message="Watchtower result could not be verified.")
    config.watchtower_report = report
    print(encode_mqtt_report(report))
    try:
        mqtt_ok, details = publish_mqtt(config)
    except Exception:
        mqtt_ok, details = False, "MQTT report could not be published."
    print(details)
    mail_ok = True
    kind = "success" if report["success"] and mqtt_ok else "failure"
    if (feature_enabled(config, "mail")
            and (not get_bool(config, "power", "dry_run", False) or get_bool(config, "mail", "send_dry_run", False))
            and get_bool(config, "mail", "on_" + kind)):
        mail_ok = try_send_mail(config, kind, details)
    # Continuation flags cannot override failed verification or failed reporting.
    return 0 if report["success"] and mqtt_ok and mail_ok else 1


# Parse command-line arguments.
# The config file path is required so the script knows what settings to use.
def parse_args():
    # Create the command-line parser shown when using --help.
    parser = argparse.ArgumentParser(
        description="Report completed Watchtower jobs or notify before an optional local power action."
    )

    # Require the path to the config file.
    parser.add_argument(
        "-c",
        "--config",
        required=True,
        help="Path to UTF-8 INI config; duplicate sections/options are rejected.",
    )

    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--watchtower-compose", metavar="FILE",
                        help="Inspect an already-finished Watchtower Compose job from this YAML path; never starts containers.")
    parser.add_argument("--watchtower-service", default="watchtower", metavar="NAME",
                        help="Compose service name to inspect (default: watchtower; requires --watchtower-compose when changed).")
    parser.add_argument("--watchtower-since-file", metavar="FILE",
                        help="Read this invocation's timezone-aware ISO-8601 start timestamp; must pair with --watchtower-exit-code-file.")
    parser.add_argument("--watchtower-exit-code-file", metavar="FILE",
                        help="Read this invocation's Compose exit code (0-255); must pair with --watchtower-since-file.")
    args = parser.parse_args()
    if bool(args.watchtower_since_file) != bool(args.watchtower_exit_code_file):
        parser.error("Both Watchtower runtime marker flags must be supplied together")
    if (args.watchtower_since_file or args.watchtower_service != "watchtower") and not args.watchtower_compose:
        parser.error("Watchtower options require --watchtower-compose")
    return args


def try_send_mail(config, mail_type, details):
    """Mail failures must not prevent an MQTT failure report."""
    try:
        return send_mail(config, mail_type, details)
    except Exception:
        print(f"ERROR: Could not prepare or send {mail_type} mail.")
        return False


def report_failure(config, error, exit_code=1, phase="aborted", warning=False):
    print(f"ERROR: {error}")
    report = build_mqtt_report(config, exit_code, error, warning, phase)
    if report["stderr"]:
        print(report["stderr"])
    # Failures always use the JSON contract, even with a legacy custom message.
    ok, details = publish_mqtt(config, report, force_report=True)
    print(details)
    if feature_enabled(config, "mail") and get_bool(config, "mail", "on_failure", default=False):
        try_send_mail(config, "failure", str(error))
    return exit_code


def main():
    args = parse_args()
    config = load_config(args.config)
    if getattr(args, "watchtower_compose", None):
        return report_watchtower(config, args.watchtower_compose, args.watchtower_service,
                                 args.watchtower_since_file, args.watchtower_exit_code_file)
    dry_run = get_bool(config, "power", "dry_run", default=False)
    if dry_run:
        # Each preview transport requires its own explicit opt-in; power stays blocked.
        report = build_mqtt_report(config)
        print(json.dumps(report, indent=2))
        ok, details = publish_mqtt(config, report, force_report=True)
        print(details)
        mail_ok = True
        kind = "success" if report["success"] and ok else "failure"
        if (feature_enabled(config, "mail") and get_bool(config, "mail", "send_dry_run", False)
                and get_bool(config, "mail", "on_" + kind)):
            mail_ok = try_send_mail(config, kind, "DRY-RUN: " + details)
        run_power_action(config)
        return 0 if ok and mail_ok else 1

    warning = get_bool(config, "report", "warning", False)
    # Finish fallible mail preparation before publishing readiness to HA.
    if feature_enabled(config, "mail") and get_bool(config, "mail", "on_success", default=False):
        if not try_send_mail(config, "success", "Preparing to publish MQTT and request the power action."):
            if not get_bool(config, "power", "continue_on_mail_fail", default=False):
                return report_failure(config, "Aborting power action because success mail failed.")
            warning = True
            if feature_enabled(config, "mail") and get_bool(config, "mail", "on_failure", default=False):
                try_send_mail(config, "failure", "Success mail failed; continuing as configured.")

    mqtt_ok, mqtt_details = publish_mqtt(config, build_mqtt_report(config, warning=warning))
    print(mqtt_details)
    if not mqtt_ok:
        if not get_bool(config, "power", "continue_on_mqtt_fail", default=False):
            return report_failure(config, "Aborting power action: " + mqtt_details)
        warning = True
        if feature_enabled(config, "mail") and get_bool(config, "mail", "on_failure", default=False):
            try_send_mail(config, "failure", mqtt_details + " Continuing as configured.")

    try:
        delay = get_float(config, "power", "delay_before_action", default=1.0)
        if get_str(config, "power", "action") != "none" and delay > 0:
            time.sleep(delay)
        run_power_action(config)
    except KeyboardInterrupt:
        return report_failure(config, "Power action interrupted.", 130, warning=warning)
    except subprocess.CalledProcessError as exc:
        # POSIX signal return codes are negative; expose a usable process exit code.
        exit_code = exc.returncode if exc.returncode > 0 else 128 - exc.returncode
        return report_failure(config, exc, exit_code, "action_failed", warning)
    except Exception as exc:
        return report_failure(config, exc, phase="action_failed", warning=warning)
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--mqtt-publish"]:
        try:
            publish_worker()
        except Exception:
            sys.exit(1)
    else:
        sys.exit(main())
