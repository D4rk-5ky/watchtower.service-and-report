# Commented code and command map — 0.0.16

Current implementation: one runtime Python file, reusing shared config, JSON, MQTT, mail and power helpers. The supplied Syncerate project is a contract reference, not a runtime dependency.

## Runtime functions

| Function | What it does and why |
| --- | --- |
| `config_error` | Print a controlled configuration failure and exit 2 before external actions. |
| `get_str` | Read and strip a string with required/default handling so all settings share validation rules. |
| `get_int` | Reuse get_str and validate integer configuration values. |
| `get_float` | Reuse get_str and validate decimal delays/timeouts. |
| `get_bool` | Read configparser booleans consistently and reject malformed values. |
| `feature_enabled` | Omitted channels are disabled; existing sections default to enabled. |
| `get_password` | Use a direct password first, otherwise the named environment variable, without duplicating precedence logic. |
| `get_config_hostname` | Use the configured friendly host, falling back to the OS hostname for consistent identities. |
| `make_safe_id` | Normalize host text for MQTT client identifiers. |
| `get_event_name_for_action` | Map none/shutdown/reboot to legacy event names independently of the completed-job status. |
| `render_template` | Expand only the documented hostname/action/event placeholders; fail on malformed templates. |
| `encode_mqtt_report` | Validate the consumer contract and serialize strict, UTF-8 JSON. |
| `build_mqtt_report` | Use Syncerate's typed status fields without claiming power completion. |
| `build_mqtt_message` | Reuse one serializer for ordinary, custom, mail, and verified Watchtower reports. |
| `get_mqtt_client_id` | Generate a hostname-based ID or expand a custom template for the broker connection. |
| `load_config` | Read INI without interpolation; validate power/report settings and enabled transports before side effects. |
| `publish_mqtt` | Honor master/preview switches; reuse report serialization and pass credentials through stdin to a bounded child. DNS/connect/publish stalls cannot block indefinitely. |
| `publish_worker` | Read the private JSON request and call Paho single with retain=False; keep optional Paho dependency and network work inside the child. |
| `find_sendmail` | Choose explicit sendmail path, common system paths or PATH without shell interpolation. |
| `build_mail_message` | Build headers/body with report JSON, optional extra text, and a DRY-RUN subject marker so previews are identifiable. |
| `send_mail_sendmail` | Feed message bytes to sendmail -t and report delivery-command success/failure. |
| `send_mail_smtp` | Use SMTP/SMTP_SSL, optional STARTTLS and authentication; fail without connecting when the resolved password is missing. |
| `send_mail` | Honor master and preview switches, then reuse one message builder and route to the chosen mail backend. |
| `run_power_action` | No-op for none; print rather than execute in previews; otherwise call systemctl poweroff/reboot. |
| `redact_watchtower_text` | Remove configured secrets and common credential forms before forwarding logs. |
| `parse_watchtower_log_record` | Accept JSON and LogFmt logs; never coerce JSON booleans into counters. |
| `inspect_watchtower_output` | Fail closed unless exactly one complete session and zero failures are verified. |
| `_read_runtime_text` | Read a small runtime marker without executing its contents. |
| `parse_compose_exit_code` | Handle Compose object/array/JSON-lines output; require one stopped service. |
| `report_watchtower` | Inspect only the finished run, then attempt one non-retained result report. |
| `parse_args` | Document config, version, Compose service and paired run-marker flags; reject invalid mode combinations early. |
| `try_send_mail` | Mail failures must not prevent an MQTT failure report. |
| `report_failure` | Build a forced JSON failure, attempt MQTT and optional failure email, and preserve the original error exit code. |
| `main` | Dispatch verified Watchtower mode or ordinary readiness/power mode. Enforce independent preview opt-ins and notification abort/continuation gates. |

The entry-point guard handles the private worker switch in its own process and exits nonzero without exposing worker exception details. All normal execution exits with the result from `main()`.

## Files

| File | Purpose |
| --- | --- |
| `.gitignore` | Original repository ignore settings, preserved. |
| `mqtt_power_action_none.py` | Runtime CLI/reporting application. |
| `watchtower.service` | Preserved root unit path; synchronized with the systemd copy. |
| `systemd/watchtower.service` | Canonical installation source for pull → run → inspect/report → normal teardown. |
| `compose.example.yaml` | Dedicated one-shot Watchtower stack with info/JSON logging and optional native email. |
| `configs/config-sendmail-none.example.ini` | All 48 options with sendmail selected, no local action, safe preview default. |
| `configs/config-smtp.example.ini` | All 48 options with SMTP selected, no local action, safe preview default. |
| `configs/config-jonsbo-watchtower.example.ini` | All 48 options with JonsBo host/topic, real MQTT, disabled email and no local action. |
| `HomeAssistant/home-assistant-automation.yaml` | Original supplied reference retained byte-for-byte; not the new chain. |
| `HomeAssistant/syncerate-all-servers.yaml` | Original supplied generic consumer retained byte-for-byte. |
| `HomeAssistant/watchtower-manual-update.yaml` | Alternative shared-topic manual flow with readiness, timeout and final non-preview success gate. |
| `HomeAssistant/jonsbo-daily-with-watchtower.yaml` | Requested chain extension: CleanUpIn → Watchtower → shutdown; rejects previews and mismatched/incomplete Watchtower reports. |
| `README.md` | Current usage, install instructions, all CLI flags and all 48 config options. |
| `VERSION` | Canonical release version; matches executable --version. |
| `VERSIONING.md` | Canonical cumulative history; case-insensitive systems cannot also store a distinct versioning.md. |
| `commented_code_map.md` | This complete function/command map. |
| `VERIFICATION.md` | Actual release checks and environment limitations. |
| `MANIFEST.json` | Original-ZIP comparison, final per-file SHA-256 and explicit null self-hash. |

## Operational commands and flags

| Command/directive | What it does and why |
| --- | --- |
| `python3 … --help / -h` | Show every public flag without loading configuration. |
| `python3 … --version / cat VERSION` | Read executable/package version without external actions. |
| `python3 … -c PATH / --config PATH` | Choose the full INI for ordinary reporting/readiness and optional power. |
| `--watchtower-compose FILE` | Inspect the finished job using this Compose file; forbids local power actions. |
| `--watchtower-service NAME` | Select the Compose service, default watchtower. |
| `--watchtower-since-file FILE` | Read a timezone-aware start timestamp; requires the exit-code marker. |
| `--watchtower-exit-code-file FILE` | Read this invocation's Compose exit code; requires the timestamp marker. |
| `--mqtt-publish` | Private child-process switch: reads broker/request data from stdin, never command-line secrets. |
| `docker compose -f FILE ps --all --format json SERVICE` | Manual marker-less fallback to inspect one stopped container exit code. |
| `docker compose -f FILE logs --no-color --no-log-prefix [--since TIME] SERVICE` | Read parseable completed-run logs, scoped to the service invocation when markers exist. |
| `Requires=docker.service; After=docker.service network-online.target; Wants=network-online.target` | Require Docker and order startup after network readiness. |
| `Type=oneshot; RemainAfterExit=no` | Wait for update/report and allow a subsequent fresh start after normal completion. |
| `RuntimeDirectory=mqtt-power-action; RuntimeDirectoryMode=0755` | Create the per-run marker directory under /run. |
| `WorkingDirectory=/opt/watchtower` | Choose the dedicated Compose project directory. |
| `ExecStartPre: rm -f marker files` | Discard stale runtime markers before each invocation. |
| `ExecStartPre: date --iso-8601=seconds > start marker` | Record invocation time before Docker work, enabling --since log filtering. |
| `ExecStartPre: docker compose … pull watchtower` | Pull once. Leading - lets the existing local image be tried if pull fails. |
| `ExecStart: docker compose … up --pull never --abort-on-container-exit --exit-code-from watchtower watchtower` | Run/wait for the one-shot job without pulling twice. Shell captures its actual exit status into the marker and exits 0 so post-reporting runs. |
| `ExecStartPost: python3 … --watchtower-compose … --watchtower-since-file … --watchtower-exit-code-file …` | Verify the captured invocation and notify through enabled channels; return the final unit gate. |
| `ExecStop: docker compose … down` | Tear down the dedicated stack on normal stop. Startup/post-start failures can skip this hook. |
| `TimeoutStartSec=0; TimeoutStopSec=120` | Allow long updates and bound normal stop to 120 seconds. |
| `WantedBy=multi-user.target` | Defines the installation target if the user chooses to enable boot startup; instructions only start on demand. |
| `sudo install -m 644 systemd/watchtower.service /etc/systemd/system/watchtower.service` | Install the edited unit with standard readable permissions. |
| `systemctl daemon-reload` | Reload the edited installed unit. |
| `systemd-analyze verify …` | Validate native unit wiring without starting the update. |
| `systemctl start / stop / status watchtower.service` | Run one job, request a stop, or inspect status. |
| `journalctl -u watchtower.service -n 100 --no-pager` | Read the last 100 unit log messages for diagnostics. |
| `systemctl poweroff / reboot` | Ordinary-mode local power commands; blocked by dry_run and never reached in Watchtower mode. |
| `sendmail -t` | Read email recipients from headers and accept the prepared message on stdin. |
| `python3 -m unittest discover -s tests -v` | Run offline regressions, including mocked external operations and a fake-Paho subprocess. |
| `python3 -m py_compile …` | Compile all Python sources to check syntax; omit generated bytecode from release archives. |
| `HA mqtt.publish start_watchtower` | External listener must start the Watchtower service; the reporter does not subscribe to commands. |
| `HA mqtt.publish shutdown_delay` | External listener performs delayed shutdown only after the JonsBo Watchtower result gate. |
| `HA backup/cleanup mqtt.publish commands` | Preserve start_asusn14e_weekly, start_rpi5_weekly, start_snapbeforewatchtower_cleanup and start_cleanupinsyncoidsnapshots_cleanup in the existing sequence. |
| `HA switch.turn_on / notify.pushover / persistent_notification.create` | Wake the configured host or report readiness/result/timeout through the existing HA channels. |
| `HA script.example_host_shutdown_ping_check_loop` | Generic manual example's external shutdown script, protected by its final success guard. |

## Test functions and methods

Every method below runs offline. Transport/power methods use mocks except the explicitly named fake-Paho worker test, which starts a real local child with no network implementation.

### `tests/test_mqtt_reports.py`

| Function/method | Check or helper purpose |
| --- | --- |
| `ReportTests.setUp` | Load a fresh app with an in-memory Paho stand-in and example config. |
| `ReportTests.assert_config_error` | Require a controlled config exit instead of a traceback or side effect. |
| `ReportTests.test_default_report` | Automatic output is an object with exactly the documented typed fields. |
| `ReportTests.test_auto_without_report_section` | Automatic defaults work without maintaining an original config snapshot. |
| `ReportTests.test_status_independent_of_action` | Both job outcomes work with every action while preserving legacy events. |
| `ReportTests.test_escaping_and_failure_details` | Quotes, Unicode, slashes, braces and newlines survive the JSON round trip. |
| `ReportTests.test_custom_object_and_title_fallback` | Custom payloads replace report settings and allow the consumer's name/job keys. |
| `ReportTests.test_commented_custom_example` | The shipped commented template actually renders to consumer-compatible JSON. |
| `ReportTests.test_invalid_custom_payloads` | Plain text, arrays, missing/unknown status, bad types and nonfinite JSON fail. |
| `ReportTests.test_invalid_auto_settings` | Invalid automatic status/code/warning are config errors. |
| `ReportTests.test_invalid_report_stops_before_io` | Even continuation flags cannot publish or execute power with invalid JSON. |
| `ReportTests.test_published_payload_and_shared_topic` | Either outcome uses the configured topic and bounded worker transport. |
| `ReportTests.test_optional_mqtt_disabled_needs_no_paho_or_mqtt_settings` | Disabled MQTT is a dependency-free no-op and ignores unused MQTT settings. |
| `ReportTests.test_optional_mail_disabled_ignores_unused_mail_settings` | Disabled mail ignores backend/recipient/SMTP settings and never sends. |
| `ReportTests.test_omitted_optional_sections_are_disabled` | A config may omit both optional output sections entirely. |
| `ReportTests.test_mqtt_only_mode_never_sends_mail` | mail.enabled=false leaves MQTT and the later power path independent. |
| `ReportTests.test_mail_only_mode_needs_no_mqtt_transport` | Mail-only mode bypasses the MQTT worker and retains the power gate. |
| `ReportTests.test_none_and_dry_run_guards` | Every original action/dry-run combination retains its command suppression. |
| `ReportTests.test_failure_gates` | Notification failures abort power unless the matching explicit override is set. |
| `ReportTests.test_dry_run_skips_delay_and_notifications` | The supplied Python preview skips delay as well as mail/MQTT/power by default. |
| `ReportTests.test_power_failure_is_reported_by_mail` | A rejected power command retains its exit code and reports failure to MQTT/mail. |
| `ReportTests.test_mail_includes_same_json` | Mail troubleshooting context includes the exact generated report. |
| `ReportTests.test_both_config_examples_load` | Both distributed configs load through the app and produce the right JSON event. |
| `ReportTests.test_smtp_starttls_delivery` | The supplied SMTP config selects STARTTLS, logs in and sends the report email. |
| `ReportTests.test_smtp_ssl_and_environment_password` | Implicit TLS selects SMTP_SSL and accepts the configured password environment. |
| `ReportTests.test_smtp_missing_password_never_connects` | An absent resolved environment password fails before any SMTP connection. |
| `ReportTests.test_smtp_failure_aborts_power` | Real SMTP routing under mocks preserves abort-before-power behavior. |
| `ReportTests.test_smtp_full_notification_order` | Mail readiness is completed before publishing readiness for a power action. |
| `ReportTests.test_sendmail_example_routes_to_sendmail` | The relocated sendmail config still uses the local sender and valid report bytes. |
| `ReportTests.service_settings` | Read shipped unit directives/variables for static wiring checks, not systemd emulation. |
| `ReportTests.service_arguments` | Expand the unit's braced variables as single arguments to inspect file references. |
| `ReportTests.test_service_report_paths_and_config_selection` | ExecStartPost resolves the shipped reporter and either config independently of cwd. |
| `ReportTests.test_service_systemd_owned_lifecycle` | The unit keeps pull/up/report phases in ExecStartPre/ExecStart/ExecStartPost. |
| `ReportTests.test_service_report_invocation_for_both_backends` | Run the post-start reporter with fake completed Compose status/logs for both mail configs. |
| `ReportTests.test_cli_parser` | Verify both config flags plus help/error exits with Paho import stubbed. |
### `tests/test_syncerate_compatibility.py`

| Function/method | Check or helper purpose |
| --- | --- |
| `CompatibilityTests.setUp` | Reuse the original fixture without importing Paho or contacting any service. |
| `CompatibilityTests.test_syncerate_contract_for_success_failure_warning` | Match Syncerate's common keys/types while identifying Watchtower as the job. |
| `CompatibilityTests.test_dry_run_notification_matrix` | Every MQTT/mail opt-in combination is independent and never powers the host. |
| `CompatibilityTests.test_dry_run_failure_mail_and_disabled_master_switch` | Preview failure selects on_failure; master switches still override preview opt-ins. |
| `CompatibilityTests.test_worker_always_non_retained` | The actual Paho boundary hard-codes retain=False, as Syncerate JSON does. |
| `CompatibilityTests.test_worker_failure_deadline_and_secret_suppression` | Timeouts/start failures cannot hang or disclose captured credentials. |
| `CompatibilityTests.test_no_failure_can_be_overridden_in_watchtower_mode` | Continuation flags and report.status cannot turn an actual failed job into success. |
| `CompatibilityTests.test_bad_markers_never_read_historical_logs` | Missing timezone, invalid dates/codes, and absent files fail before Docker inspection. |
| `CompatibilityTests.test_malformed_logs_running_container_and_duplicate_services` | Ambiguous or incomplete data must not authorize continuation. |
| `CompatibilityTests.test_redaction_and_payload_bounds` | Large errors remain bounded after configured and generic secrets are removed. |
| `CompatibilityTests.test_marker_reader` | Marker reads reject empty/oversized/missing input and never execute text. |
| `CompatibilityTests.test_cli_markers_must_be_paired` | Reject partial runtime correlation and unrelated mode flags at CLI parsing. |
| `CompatibilityTests.test_real_worker_subprocess_with_fake_paho` | Execute the real worker with a fake Paho module; check wire data and hard timeout. |
| `CompatibilityTests.test_watchtower_preview_notification_matrix` | Watchtower previews obey both opt-ins and preserve completed-job verification. |
| `CompatibilityTests.test_custom_message_survives_ordinary_publish` | Generated readiness metadata must not silently replace a valid custom message. |
| `JonsBoTests.setUp` | Load the shipped automation and a minimal HA-compatible boolean filter. |
| `JonsBoTests.condition` | Evaluate the trigger/template subset used by result routing. |
| `JonsBoTests.commands` | Walk result guards/choose branches and collect emitted MQTT command payloads. |
| `JonsBoTests.test_cleanup_starts_watchtower_and_only_watchtower_success_shuts_down` | Protect the exact chain requested by the user, including failure/preview guards. |
| `JonsBoTests.test_topic_and_config_agree` | Ensure the supplied JonsBo publisher and consumer use the same host/topic. |
### `tests/test_watchtower_flow.py`

| Function/method | Check or helper purpose |
| --- | --- |
| `WatchtowerReportTests.setUp` | Prepare/evaluate setUp for isolated regression assertions. |
| `WatchtowerReportTests.report` | Prepare/evaluate report for isolated regression assertions. |
| `WatchtowerReportTests.test_session_gate_and_exit_codes` | Verify session gate and exit codes to protect the behavior named in this regression. |
| `WatchtowerReportTests.test_failed_container_details_and_redaction` | Verify failed container details and redaction to protect the behavior named in this regression. |
| `WatchtowerReportTests.test_default_logfmt_session_is_accepted` | Verify default logfmt session is accepted to protect the behavior named in this regression. |
| `WatchtowerReportTests.test_default_logfmt_failed_session_still_fails` | Verify default logfmt failed session still fails to protect the behavior named in this regression. |
| `WatchtowerReportTests.test_parse_compose_exit_code_shapes` | Verify parse compose exit code shapes to protect the behavior named in this regression. |
| `WatchtowerReportTests.test_reporter_reads_completed_job_without_starting_it` | Verify reporter reads completed job without starting it to protect the behavior named in this regression. |
| `WatchtowerReportTests.test_reporter_publishes_failure_for_failed_or_unverifiable_job` | Verify reporter publishes failure for failed or unverifiable job to protect the behavior named in this regression. |
| `WatchtowerReportTests.test_watchtower_both_output_channels_can_be_disabled` | Verified job status still controls systemd when MQTT and mail are both disabled. |
| `WatchtowerReportTests.test_reporting_failure_does_not_turn_job_into_success` | Verify reporting failure does not turn job into success to protect the behavior named in this regression. |
| `WatchtowerReportTests.test_current_run_markers_scope_logs_and_override_stale_container_state` | Systemd mode uses the captured current exit code and --since marker, never stale ps state. |
| `WatchtowerReportTests.test_missing_current_run_marker_fails_closed_without_replaying_history` | A missing requested timestamp must not fall back to unbounded historical container logs. |
| `WatchtowerReportTests.test_preflight_and_cli` | Verify preflight and cli to protect the behavior named in this regression. |
| `WatchtowerReportTests.test_release_layout_preserves_all_original_files` | Preserve every supplied project file, including service and automation references. |
| `AutomationTests.setUp` | Prepare/evaluate setUp for isolated regression assertions. |
| `AutomationTests.render_bool` | Prepare/evaluate render bool for isolated regression assertions. |
| `AutomationTests.condition` | Prepare/evaluate condition for isolated regression assertions. |
| `AutomationTests.walk_actions` | Prepare/evaluate walk actions for isolated regression assertions. |
| `AutomationTests.test_shutdown_only_after_success` | Verify shutdown only after success to protect the behavior named in this regression. |
| `AutomationTests.test_json_wait_matching_and_redacted_examples` | Verify json wait matching and redacted examples to protect the behavior named in this regression. |
| `AutomationTests.test_schedule_readiness_and_compose_logging` | Verify schedule readiness and compose logging to protect the behavior named in this regression. |
