# Verification — 0.0.15

Verification was performed on the release source tree without contacting a real MQTT broker, SMTP server, Docker daemon, Home Assistant instance, or issuing a real host power command.

## Completed checks

- `python3 -m unittest discover -s tests -v`
  - Result: **47 tests passed**.
  - Docker, MQTT, mail, and power operations are mocked where external I/O would otherwise occur.
  - New optional-channel regressions cover MQTT-only, mail-only, both channels disabled, both optional sections omitted, missing Paho while MQTT is disabled, disabled-feature settings being ignored, and Watchtower success/failure behavior when no external output channel is enabled.
  - Current-run regressions verify `--since` log scoping, captured Compose exit-code use, and fail-closed behavior when the timestamp marker is unavailable.
  - New production-format regressions verify Watchtower 1.7.1 default Auto/LogFmt `Session done` output is parsed successfully and that LogFmt summaries with failed updates still fail strictly.
  - Existing regressions still cover report JSON validation, MQTT/mail/power failure gates, sendmail and SMTP backends, systemd command wiring, completed-Watchtower inspection, shared-topic Home Assistant host filtering, `mode: restart`, and shutdown-only-after-success behavior.
- `python3 -m py_compile mqtt_power_action_none.py tests/test_mqtt_reports.py tests/test_watchtower_flow.py`
  - Result: **passed**.
- YAML parsing with PyYAML for the shipped `HomeAssistant/watchtower-manual-update.yaml` and `compose.example.yaml`.
  - Result: **passed**.
- INI parsing with `configparser` for both complete example configs.
  - Result: **passed**; each example contains **43 active options**.
  - Both contain explicit `mqtt.enabled = true` and `mail.enabled = true` examples with comments explaining how to disable or omit each optional feature.
- Paho-independent CLI checks were run with `python3 -S`, which excludes site packages:
  - `python3 -S mqtt_power_action_none.py --help` displayed all four flag/forms without requiring `paho-mqtt`.
  - A temporary minimal config containing only `[power]` with `action = none` ran successfully with no `[mqtt]` or `[mail]` section. Output confirmed MQTT was disabled and no power action was performed.
- Static/unit tests verify the systemd-owned phases remain exactly:
  - `ExecStartPre`: `docker compose ... pull watchtower`
  - `ExecStartPre`: also resets/creates per-run marker state, then performs the only Watchtower pull
  - `ExecStart`: `docker compose ... up --pull never --abort-on-container-exit --exit-code-from watchtower watchtower`, capturing that command's exit code
  - `ExecStartPost`: Python reporter uses the current-run timestamp and exit-code marker, so historical logs cannot satisfy success
  - `RemainAfterExit=no`: the completed oneshot does not stay `active (exited)`
  - `ExecStop`: `docker compose ... down` during stop/teardown
- `systemd-analyze verify ./systemd/watchtower.service` was attempted.
  - The checker reached the unit but this build container has no `docker.service` and no `/usr/bin/docker` executable.
  - It therefore reported those missing environment dependencies; no separate unit syntax error was reported.
- Privacy/redaction scan across the project tree found no private IPv4 addresses, known prior personal host/device/account labels, or non-placeholder email addresses. Remaining addresses use reserved/example values such as `sender@example.com` and `receiver@example.com`.
- The release file inventory is compared against 0.0.13 during manifest generation. All 14 files from 0.0.13 remain present at the same paths; modified files are explicitly recorded in the manifest and no unrelated file is removed.
- Final staging is checked for `__pycache__`, `.pyc`, `.pyo`, build cache, and temporary files before ZIP creation.

## Optional-channel behavior verified

- `[mqtt] enabled = false` makes MQTT a successful no-op. Broker/topic/QoS/custom-message settings are not validated, a Paho client is never created, and `paho-mqtt` is not required.
- Omitting the entire `[mqtt]` section also disables MQTT. For backward compatibility, an existing `[mqtt]` section without the new `enabled` option remains enabled.
- `[mail] enabled = false` makes mail a successful no-op. Mail backend, recipient, sendmail, and SMTP settings are not used and cannot fail the run.
- Omitting the entire `[mail]` section also disables mail. For backward compatibility, an existing `[mail]` section without the new `enabled` option remains enabled.
- Mail-only mode still includes the automatic result JSON but does not consume an unused MQTT custom message/template.
- In Watchtower report mode, disabled notification channels are neutral: verified Watchtower success returns success even if both MQTT and mail are disabled; failed/unverifiable Watchtower completion still returns failure to systemd.

## What was not fully tested

- No real Watchtower container was run in this build environment. The new parser is tested against the production LogFmt shape supplied from Watchtower 1.7.1, but the target host should still run the service once after installation.
- No real current-run `docker compose logs --since ...` or runtime-marker flow was exercised against the target Docker daemon; command construction and fail-closed behavior are covered offline.
- No real MQTT broker, sendmail/Postfix installation, or SMTP provider was contacted.
- No Home Assistant automation was imported/executed in a live Home Assistant instance. YAML and relevant Jinja/control-flow branches are checked offline.
- No real shutdown/reboot was performed.
- Native `systemd-analyze verify` cannot complete successfully in this build container because Docker/systemd Docker dependencies are absent. Run it again on the target host after editing paths.

## Recommended target-host checks

For the normal MQTT-enabled Watchtower workflow:

```sh
sudo systemd-analyze verify /etc/systemd/system/watchtower.service
sudo systemctl daemon-reload
sudo systemctl start watchtower.service
sudo systemctl status watchtower.service
sudo journalctl -u watchtower.service -n 100 --no-pager
```

To test optional modes safely, first keep `power.action = none`, then try one configuration at a time:

```ini
[mqtt]
enabled = true

[mail]
enabled = false
```

```ini
[mqtt]
enabled = false

[mail]
enabled = true
```

```ini
[mqtt]
enabled = false

[mail]
enabled = false
```

When MQTT is enabled, temporarily subscribe in Home Assistant to the chosen shared result topic and confirm the JSON contains at least `status` and `host`. When MQTT is disabled, no MQTT result is expected; use the systemd exit/status and, if enabled, email reporting instead.
