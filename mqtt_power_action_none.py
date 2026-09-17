#!/usr/bin/env python3
from __future__ import annotations

# This script sends an MQTT message before performing a shutdown or reboot.
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

__version__ = "1.1.0"


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
# shutdown becomes server_shutdown, reboot becomes server_reboot.
def get_event_name_for_action(action: str) -> str:
    # Translate the config action into the actual systemctl command.
    if action == "shutdown":
        return "server_shutdown"

    if action == "reboot":
        return "server_reboot"

    config_error("[power] action must be either shutdown or reboot")


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


# Build the MQTT payload.
# If [mqtt] message is auto or empty, use the cleanup-compatible JSON contract.
def build_mqtt_report(config, exit_code=0, error=None, warning=False,
                      phase="before_action") -> dict:
    """Cleanup-compatible status fields, plus explicit power-action semantics.

    Success is a pre-action notification, never proof that the host powered off.
    """
    hostname = get_config_hostname(config)
    action = get_str(config, "power", "action", required=True)
    stderr = (getattr(error, "stderr", "") or getattr(error, "stdout", "") or "")
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    dry_run = get_bool(config, "power", "dry_run", default=False)
    return {
        "status": "success" if exit_code == 0 else "failure",
        "title": render_template(get_str(config, "report", "title", default="")
                                 or "{hostname}: {action}", config),
        "name": "mqtt-power-action",
        "job": render_template(get_str(config, "report", "job", default="")
                               or "{safe_hostname}-{action}", config),
        "exit_code": exit_code,
        "warning": bool(warning),
        "error": str(error) if error is not None else "",
        "stderr": stderr[-4096:],
        "command": action,
        "dry_run": dry_run,
        "comment": get_str(config, "report", "comment", default=""),
        "version": __version__,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event": get_event_name_for_action(action),
        "host": hostname,
        "action": action,
        "phase": "dry_run" if dry_run else phase,
        "message": (str(error) if error is not None else
                    f"Would request {action}; dry run only." if dry_run else
                    f"Ready to request {action}; this does not confirm completion."),
    }


def build_mqtt_message(config, report=None) -> str:
    # "auto" means the script generates the JSON payload itself.
    configured_message = get_str(config, "mqtt", "message", default="auto")

    # Empty message is treated the same as auto.
    if configured_message.lower() == "auto" or configured_message.strip() == "":
        return json.dumps(report if report is not None else build_mqtt_report(config),
                          separators=(",", ":"))

    return render_template(configured_message, config)


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
    try:
        files_read = config.read(path)
    except (configparser.Error, OSError, UnicodeError):
        config_error("Could not parse/read config file (expected INI format)")

    # If no file was read, the path is probably wrong or unreadable.
    if not files_read:
        config_error(f"Could not read config file: {path}")

    action = get_str(config, "power", "action", required=True)

    if action not in ["shutdown", "reboot"]:
        config_error("[power] action must be either shutdown or reboot")

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
    delay = get_float(config, "power", "delay_before_action", default=1.0)
    if not math.isfinite(delay) or delay < 0:
        config_error("[power] delay_before_action must be finite and nonnegative")
    for key in ("dry_run", "continue_on_mqtt_fail", "continue_on_mail_fail"):
        get_bool(config, "power", key)
    get_bool(config, "mqtt", "publish_dry_run")
    get_mqtt_client_id(config)
    build_mqtt_message(config)
    build_mqtt_report(config)

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

    return config


# Publish in a subprocess, as in CleanUpInSyncoidSnapshots. This bounds DNS,
# connection and acknowledgement stalls, not just the MQTT callback wait.
def publish_mqtt(config, report=None, force_report=False) -> tuple[bool, str]:
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
        "message": (json.dumps(report, separators=(",", ":")) if force_report
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
# In dry_run mode, it only prints the command instead of shutting down/rebooting.
def run_power_action(config):
    action = get_str(config, "power", "action", required=True)
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
    subprocess.run(command, check=True, capture_output=True, text=True)


# Parse command-line arguments.
# The config file path is required so the script knows what settings to use.
def parse_args():
    # Create the command-line parser shown when using --help.
    parser = argparse.ArgumentParser(
        description="Send MQTT before shutdown/reboot using a config file."
    )

    # Require the path to the config file.
    parser.add_argument(
        "-c",
        "--config",
        required=True,
        help="Path to config file.",
    )

    return parser.parse_args()


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
    if get_bool(config, "mail", "on_failure", default=False):
        try_send_mail(config, "failure", str(error))
    return exit_code


def main():
    args = parse_args()
    config = load_config(args.config)
    dry_run = get_bool(config, "power", "dry_run", default=False)
    if dry_run:
        # No mail or system commands in a preview. MQTT requires explicit opt-in.
        report = build_mqtt_report(config)
        print(json.dumps(report, indent=2))
        ok, details = publish_mqtt(config, report, force_report=True)
        print(details)
        run_power_action(config)
        return 0 if ok else 1

    warning = False
    # Finish fallible mail preparation before publishing readiness to HA.
    if get_bool(config, "mail", "on_success", default=False):
        if not try_send_mail(config, "success", "Preparing to publish MQTT and request the power action."):
            if not get_bool(config, "power", "continue_on_mail_fail", default=False):
                return report_failure(config, "Aborting power action because success mail failed.")
            warning = True
            if get_bool(config, "mail", "on_failure", default=False):
                try_send_mail(config, "failure", "Success mail failed; continuing as configured.")

    mqtt_ok, mqtt_details = publish_mqtt(config, build_mqtt_report(config, warning=warning))
    print(mqtt_details)
    if not mqtt_ok:
        if not get_bool(config, "power", "continue_on_mqtt_fail", default=False):
            return report_failure(config, "Aborting power action: " + mqtt_details)
        warning = True
        if get_bool(config, "mail", "on_failure", default=False):
            try_send_mail(config, "failure", mqtt_details + " Continuing as configured.")

    try:
        delay = get_float(config, "power", "delay_before_action", default=1.0)
        if delay > 0:
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
