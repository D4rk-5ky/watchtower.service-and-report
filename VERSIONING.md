# Versioning

The current package version is stored in `VERSION`. The application also exposes
`--version`. Use this one canonical change log (case-insensitive Windows
filesystems cannot also maintain a separate `versioning.md`).

## Rules

- Every new released version increments the patch component by one.
- After `0.0.99`, the next version is `0.1.0`, never `0.0.100`.
- In general, when patch is 99, increment minor and reset patch to 0.
- Record every code, configuration, documentation, and packaging change here.
- Keep README focused on current usage, and update the complete configuration
  example and function/command map with every release.
- Preserve required current project files; do not bundle original snapshots.
  Exclude bytecode, caches, build output, and temporary files. Verify the archive
  against the supplied file inventory, accounting for authorized moves/removals.

## 0.0.16 — 2026-09-17

- Base this release on the supplied archive's VERSION/MANIFEST/history (0.0.15), incrementing exactly once to 0.0.16. The archive's Python file instead declared 1.1.0 and lacked the Watchtower commands used by its service/tests; reconcile the executable version and restore the missing reporting path in the existing script. Preserve every original file path, including reference YAMLs and the root unit despite older exclusion tests.
- Match Syncerate's common MQTT JSON keys and types: status, success, title/name, job, exit_code, warning, error, stderr, and skipped_datasets. Identify completed Watchtower jobs with job=watchtower and phase=completed; retain host/event/action, dry-run, version/timestamp, message/comment and specific update diagnostics. Ordinary power success remains readiness, never proof of completed shutdown.
- Restore action=none, optional MQTT/mail channel switches, ordinary report fields and strict custom JSON validation. Reuse existing config/template/mail/power functions and preserve the supplied subprocess MQTT publisher, its hard deadline, non-retained messages, secret-safe worker failures and abort/continuation gates. Retain forced JSON on failure/preview paths.
- Restore completed-job JSON/LogFmt inspection with one valid Session done, strict integer counters, zero failed updates, no error/failed-container logs, and exit zero. Add bounded redacted diagnostics; reject malformed logs, ambiguous/running Compose state and invalid marker pairs. Inspection never starts containers; each Docker command times out after 30 seconds.
- Restore --watchtower-compose, --watchtower-service, --watchtower-since-file and --watchtower-exit-code-file, with paired marker validation and fail-closed handling before historical-log access. Add --version. Keep the systemd pull-once/current-run-marker flow; synchronize the retained root unit to the systemd unit.
- Preserve the supplied script's safe dry run (no delay/power or notifications by default). At the user's request, expose independent mqtt.publish_dry_run and mail.send_dry_run options; both default false and remain subordinate to master switches. Preview MQTT is marked dry_run/phase; preview emails receive [DRY-RUN] subjects. Mail event selection and failures work in opted-in previews.
- Add HomeAssistant/jonsbo-daily-with-watchtower.yaml based on the pasted daily automation: after CleanUpIn success send start_watchtower; only a matching completed non-preview Watchtower success sends shutdown_delay. Keep existing schedule/entities/backup commands; guard source host, job, phase, success boolean and exit code. Preserve original reference automations. Add preview protection to the generic manual automation's final shutdown gate.
- Add a full JonsBo config with the matching host/topic, action=none, live MQTT and disabled mail. Retain safe previews in both generic configs. All three examples include the same 48 options and corrected timeout/dry-run comments.
- Rewrite README for current installation/usage, all flags and options, the external listener mapping, exact chain, preview behavior, report guarantees and limitations. Regenerate the map of every runtime/test function and operational command. Refresh verification and SHA-256 manifest against the actual supplied ZIP inventory.
- Update all original regression tests to exercise the supplied bounded transport/return-code API, preserved file inventory and actual preview semantics instead of nonexistent Paho-client helpers or stale removal expectations. Add consumer-contract, independent preview opt-ins, worker retention/deadline, redaction, marker failure, and JonsBo branch tests. No test failures are hidden with new skips.
- Package the full project without bytecode, cache, build output, dependencies or scratch files. No live broker, mail account, Docker host, power command or Home Assistant instance is changed.

## 0.0.15 — 2026-09-16

- Fix false Watchtower failure reports on production hosts using Watchtower 1.7.1 default `Auto` console logging. In non-TTY Docker output, Watchtower emits LogFmt lines such as `msg="Session done" Failed=0 Scanned=2 Updated=0`; 0.0.14 only parsed JSON and therefore rejected an otherwise successful run.
- Add `parse_watchtower_log_record()` to accept either JSON or Watchtower LogFmt/Auto lines, using shell-style quote parsing for fields such as `msg="Session done"` and normalizing `Scanned`, `Updated`, and `Failed` to strict integers.
- Keep the existing strict result gate unchanged after parsing: one completed session, exit code zero, valid non-negative counters, `Updated <= Scanned`, `Failed == 0`, and no explicit error/failed-update records.
- Keep `WATCHTOWER_LOG_FORMAT: json` in the supplied Compose example as the recommended deterministic setting, but no longer require it; existing production Compose files using Watchtower's default Auto/LogFmt output now work.
- Add production-log regressions for successful LogFmt output and failed LogFmt summaries while retaining JSON coverage.
- Preserve the current-run timestamp/exit-code correlation, single-pull systemd flow, optional MQTT/mail behavior, shared-topic HA flow, teardown behavior, redaction, and all 14 project files.

## 0.0.14 — 2026-09-16

- Fix duplicate Watchtower image pulls. `ExecStartPre` remains the single explicit `docker compose pull watchtower`; `ExecStart` now uses `docker compose up --pull never ...`, and the Compose example no longer declares `pull_policy: always`.
- Fix false current-run update reports caused by replaying historical logs from an older `watchtower` container. The unit now creates a per-invocation start timestamp under `/run/mqtt-power-action/`, and `ExecStartPost` requests only logs newer than that marker.
- Capture the actual current `docker compose up` exit code in a per-run runtime file. The reporter uses that value instead of trusting possibly stale `docker compose ps` state from a previous container.
- Fail closed when a requested run marker is missing, empty, or invalid. The reporter never falls back to unbounded historical logs in the systemd flow.
- Add `--watchtower-since-file` and `--watchtower-exit-code-file` CLI options used by the packaged systemd service. Manual legacy report mode without those options retains the old `docker compose ps` fallback.
- Add regressions for current-run log scoping, stale-state avoidance, missing-marker fail-closed behavior, single-pull service wiring, and current-run exit-code capture. Test count increases from 43 to 45.
- Preserve optional MQTT/mail behavior, shared-topic Home Assistant flow, `mode: restart`, redaction, teardown, and all existing safety gates.

## 0.0.13 — 2026-09-16

- Change `HomeAssistant/watchtower-manual-update.yaml` from `mode: single` to `mode: restart` so a new manual invocation replaces a still-running previous invocation instead of being rejected. Remove the now-unneeded `max_exceeded: silent` setting.
- Move the packaged systemd unit from the project root to `systemd/watchtower.service`. Update installation instructions, config comments, tests, verification, and manifest paths while keeping the installed unit name `/etc/systemd/system/watchtower.service` unchanged.
- Remove both Syncerate-related Home Assistant reference YAMLs from the release: `HomeAssistant/syncerate-all-servers.yaml` and the chained Syncerate example `HomeAssistant/home-assistant-automation.yaml`. They were reference material for creating/processing MQTT messages and are not part of the Watchtower project.
- Replace the removed reference-consumer regression with release-layout checks that verify the service subfolder, absence of a root duplicate, and absence of the excluded Syncerate reference YAMLs.
- Preserve the systemd pull → run/wait → post-report → teardown flow, shared-topic Watchtower JSON handling, optional MQTT/mail behavior, strict Watchtower result verification, redacted examples, and all other required project files.

## 0.0.12 — 2026-09-16

- Make script-level MQTT and mail independent optional features. Add `mqtt.enabled` and `mail.enabled` master switches to both complete config examples.
- Preserve backward compatibility: an existing `[mqtt]` or `[mail]` section without the new `enabled` option remains enabled, while omitting the whole optional section disables that feature.
- When MQTT is disabled, skip broker/topic/QoS/custom-message validation and publishing entirely. `paho-mqtt` is no longer a hard import-time dependency; it is required only when MQTT is enabled.
- When mail is disabled, skip all mail backend/recipient/SMTP/sendmail validation and delivery. Disabled mail cannot trigger `continue_on_mail_fail` or make a run fail.
- Keep disabled channels neutral in both ordinary mode and Watchtower `ExecStartPost`. A verified successful Watchtower job succeeds even when both notification channels are disabled; a failed/unverifiable Watchtower job still fails systemd even with no external notification transport.
- Keep mail-only reporting useful and independent from MQTT configuration: email includes the automatic result JSON while showing MQTT as disabled, and unused MQTT custom templates do not affect mail-only mode.
- Change example/default mail subjects to generic report wording so mail-only mode does not falsely claim that MQTT was sent.
- Expand both full INI examples from 41 to 43 active options, with comments explaining the new switches and omitted-section behavior.
- Add regressions for MQTT-only, mail-only, both-disabled, omitted optional sections, missing Paho with MQTT disabled, ignored disabled-feature settings, and Watchtower result behavior with no output channels. The offline suite is now 43 tests.
- Preserve the systemd pull → run/wait → post-report → teardown flow, strict Watchtower result verification, Home Assistant shared-topic behavior when MQTT is enabled, privacy redaction, all previous project files, and clean packaging rules.

## 0.0.11 — 2026-09-16

- Replace the Home Assistant success/failure wait pair with one MQTT result trigger. The Watchtower automation now receives one matching report and reads `payload_json.status` itself to decide success, failure, or unknown.
- Change the supplied Watchtower result topic to one shared example topic, `homeassistant/watchtower/status`, in both complete 41-option INI examples and the HA examples. Multiple hosts can publish to this one topic because automatic JSON already includes the reporting `host`.
- Keep host safety/correlation in the manual Watchtower flow: its single wait trigger filters the shared result topic by the expected JSON `host`, so a report from another machine cannot authorize that host's shutdown.
- Rewrite the generic all-servers consumer to use one MQTT trigger for every host, normalize JSON `status`, and optionally branch by JSON `host` for different follow-up actions without adding host-specific subscriptions.
- Update the chained-job HA example to use one shared sync-result topic and payload `job` to distinguish job A from job B instead of separate result topics; replace old machine-specific example command payloads with neutral `start_example_*` placeholders.
- Preserve the systemd-owned Watchtower lifecycle, strict completed-job verification, MQTT report format, Python code, mail behavior, power safety gates, `RemainAfterExit=no`, and all prior required project files.
- Update README current usage, the complete command/code map, offline regression tests, verification report, manifest, privacy checks, and clean release archive.

## 0.0.10 — 2026-09-16

- Change `watchtower.service` from `RemainAfterExit=yes` to `RemainAfterExit=no` so a completed one-shot no longer stays `active (exited)`.
- Preserve the existing systemd-owned order exactly: `ExecStartPre` pulls, `ExecStart` runs/waits, and `ExecStartPost` inspects the completed Watchtower job and publishes MQTT success/failure before cleanup.
- Keep the existing `ExecStop=docker compose down`. With the non-remaining oneshot, the completed service proceeds into its stop phase after reporting, so the dedicated Compose project is torn down and a successful run finishes inactive/stopped.
- Repeat/manual test runs can therefore use `systemctl start watchtower.service` again instead of requiring `restart` solely to clear an `active (exited)` state.
- Preserve Python application behavior, both 41-option config examples, Home Assistant automations, reporting safety gates, redaction, and all prior project files.
- Update README current usage, the complete command/code map, service regression expectation, verification report, manifest, and clean release archive.

## 0.0.9 — 2026-09-16

- Restore the requested systemd-owned Watchtower flow instead of letting the Python reporter run the update itself: `ExecStartPre` pulls Watchtower, `ExecStart` runs/waits for the one-shot Compose service, and `ExecStartPost` reads the completed result and publishes MQTT success/failure.
- Use systemd's leading `-` prefix on the pull/run phases so a non-zero Docker/Watchtower result does not skip `ExecStartPost`; the post reporter becomes the final unit success/failure gate.
- Reuse the existing strict Watchtower JSON parser and MQTT/mail helpers. Add Compose `ps --format json` exit-code parsing and completed-job `logs --no-log-prefix` inspection; the reporter never starts/pulls/restarts Watchtower in report mode.
- Keep strict success requirements: exit 0, exactly one valid `Session done`, valid non-negative counters, `Updated <= Scanned`, `Failed == 0`, and no Watchtower error/failed-update records. Unverifiable completion remains failure.
- Require JSON/info Watchtower logging in the Compose example so the post-run parser can verify the finished session.
- Preserve ordinary MQTT/mail/power behavior and its safety gates; Watchtower report mode still requires `power.action = none`, automatic JSON, and non-retained MQTT.
- Redact identifying infrastructure details from all shipped examples/tests/docs: replace local IPs, host/device names, account labels, personal MQTT topics/entity IDs, and non-placeholder email values with generic example data.
- Rewrite README for current behavior only, update the full code/command map, update verification/tests, and keep both 41-option INI examples complete.
- Keep the same required project files, regenerate manifest/checksums, and package a clean archive without bytecode/cache/temp files.

## 0.0.8 — 2026-09-16

- Restore the strict Watchtower completion check inside mqtt_power_action_none.py,
  with --watchtower-compose FILE and optional --watchtower-service NAME. Keep a
  single runtime Python file and reuse existing MQTT, encoding, config and mail helpers.
- Capture a foreground one-time Compose run with image pull and forced JSON/info
  logging; report handled launch, pull, process, logged-update and unverifiable
  completion failures as well as verified success. One final MQTT publish attempt.
- Require exit zero, exactly one valid Session done, Failed zero, valid counters,
  and no error/fatal/panic or INFO-level Unable to update container record.
- Add dynamically computed compatible status/title/exit_code/warning/error/stderr
  fields, summary counters, Compose exit code, bounded failed_containers details
  and truncation flag. Redact known secrets/common credential patterns. Unknown
  container names are explicitly unavailable, not inferred from adjacent log lines.
- Require action none, message auto and retain false before Docker. No local
  power action in checked mode; job failure cannot be hidden by continuation flags.
  Ordinary reporter behavior remains unchanged. Runtime reports never rewrite INIs.
- Select success/failure mail from job and MQTT outcomes in checked mode, using
  existing sendmail/SMTP routing. No failure-to-success report retry.
- Move the unit's work into one ExecStart of the existing Python script; remove
  separate pull and success-only post hook so handled failures can publish too.
  Preserve requested remain-active and Compose down-on-stop settings.
- Add supplied all-servers HA consumer with one Watchtower result-topic trigger;
  preserve all its original triggers/actions and the existing two automations.
- Keep all 41 active INI settings unchanged, updating comments for checked mode.
  Update README, full function/command map, regression tests, verification,
  original/prior manifest accounting and clean ZIP.

## 0.0.7 — 2026-09-16

- Simplify the requested runtime to systemd, Docker Compose and the existing
  mqtt_power_action_none.py with one directly named config file.
- Remove run_watchtower_once.py and its runner-specific tests from this release
  at the user's request to eliminate the extra layer; retain original necessary
  files, both INIs, both HA automations and their regression tests.
- Replace the runner with foreground Compose up --exit-code-from watchtower
  watchtower; keep image pull first and run the reporter only after exit zero.
- Restore requested RemainAfterExit=yes and ExecStop=compose down behavior.
  Document restart for repeat jobs and dedicated-project scope of teardown.
- Remove REPORT_CONFIG/WATCHTOWER_COMPOSE_FILE/EnvironmentFile indirection and
  runner prechecks. Use explicit Compose filename and complete -c INI path.
- Explicitly document the simplified success guarantee: Watchtower exit zero
  may include individual update failures; no session/log verifier remains.
- Keep reporter implementation and all active INI values unchanged. Update
  config comments and Compose password instructions to use a local Compose .env.
- Update README current usage, operational disclaimer risks, full function/command
  map, tests, verification, original/prior-file manifest accounting and clean ZIP.

## 0.0.6 — 2026-09-16

- Replace detached Compose startup with run_watchtower_once.py: run the existing
  Watchtower service as a foreground one-time job, wait for exit, and require a
  complete JSON session with zero failures before success reporting. Reject
  error-level logs and missing/invalid/duplicate session summaries even on exit 0.
- Reuse the reporter's configuration functions. Preflight notification-only,
  automatic, non-retained success reporting before Docker; leave the original
  reporter implementation and its general-purpose power/mail safety behavior intact.
- Use the supplied /opt/mycompose directory and docker-compose.yaml filename.
  Keep reporter/config paths under /opt/mqtt-power-action.
  Make the oneshot repeatable and remove Compose down so updated workloads stay up.
- Add a cleaned Compose example from the supplied service; retain run-once,
  cleanup, image, timezone and email settings, replacing the pasted app password
  with a required environment variable. No actual credentials are packaged.
- Add the Watchtower HA automation: one generic readiness sensor, bounded
  wake attempts, four-minute stability and an explicit outer stop-if-not-ready.
  Keep Sunday 17:30 disabled. Parse JSON success/failure, stop on failure/timeout,
  and put both original shutdown actions behind a final success guard.
- Preserve command/result/shutdown topics and the external shutdown script.
  Retain the separate original backup automation unchanged.
- Set both INIs to the Watchtower result topic and action none; update comments
  while keeping all 41 options, dry-run, mail and MQTT failure defaults intact.
- Update README current usage and top disclaimer's operational risks, complete
  function/command map, offline regressions, verification, manifest and clean ZIP.

## 0.0.5 — 2026-09-15

- Integrate watchtower.service directly with the existing Python reporter at
  /opt/mqtt-power-action/mqtt_power_action_none.py.
- Replace the missing external success.sh reference with an absolute Python
  ExecStartPost command. Keep report failures visible as activation failures.
- Select exactly one of the two configs via REPORT_CONFIG; default to sendmail.
  Document the SMTP alternative and optional configs/report.env password file.
- Keep the external Compose stack separate. Use the user's requested placeholder
  /location/for/wathctower/compose file through WATCHTOWER_COMPOSE_FILE, and its
  parent directory as WorkingDirectory; apply -f consistently to pull/up/down.
- Add readability prechecks for the script, selected INI and Compose file before
  changing containers. No Python application behavior or config active values
  changed; preserve original dry-run, failure gates, QoS, retain, and mail defaults.
- Update both INI header comments, README installation paths/service commands and
  risk description, commented code map, verification, manifest and archive hashes.
- Add offline service-integration tests to map Linux install paths to the shipped
  files and exercise the post-start report with both selected configs and mocked I/O.
- Keep existing Compose lifecycle commands/options and service dependencies,
  oneshot/remain-active behavior, and timeout settings. No Compose file is invented.

## 0.0.4 — 2026-09-15

- Remove the bundled `originals/` snapshots as explicitly requested. Existing
  release archives remain separate; the current release includes no snapshots.
- Relocate the current sendmail INI to `configs/config-sendmail-none.example.ini`
  without changing any bytes; no duplicate INI remains at the root.
- Add `configs/config-smtp.example.ini`, based on the user's supplied SMTP INI.
  Normalize pasted Markdown escapes in names, placeholders, and email addresses;
  correct custom JSON to include status and escape literal template braces; add
  all six report options and an explicit password_env option (41 options total).
- Preserve the supplied SMTP host/port, placeholder credentials, shutdown action,
  dry-run, delay, MQTT and failure-abort settings. Correct explanatory comments
  and use the actual script filename in extra_body.
- Move the supplied Home Assistant automation byte-for-byte to
  `HomeAssistant/home-assistant-automation.yaml`; remove the old reference path.
- Update all active README/code-map paths, both-backend setup instructions, and
  verification details. Keep the user's disclaimer at the very top of README.
- Update tests to use the current layout without original snapshots. Add seven
  tests for both INIs, sendmail routing, STARTTLS, implicit TLS, environment/missing
  passwords, SMTP failure aborts, and complete simulated SMTP dry-run order.
- No application Python or systemd service changes. Regenerate manifest and ZIP
  checksums with explicit accounting for moved, added, and removed paths.

## 0.0.3 — 2026-09-15

- Add the user's Disclaimer / Liability Notice, Disclaimer, and Data Loss
  Warning near the top of README, preserving the supplied general wording.
- Adapt only the operational risks and related testing guidance to MQTT-triggered
  automation, local shutdown/reboot, mail, and the bundled Docker Compose service.
  Do not claim this script directly creates or deletes ZFS snapshots.
- Explain that dry-run still sends MQTT/mail and can trigger receiving automations;
  this app has no generated execution plan, so configuration/automation/hook review
  is the relevant pre-run check.
- Update the code map's README description, verification report, package version,
  full archive manifest, and checksums. No application, service, config, test,
  original snapshot, or automation-reference changes.
- Preserve the full 0.0.2 inventory and all prior release archives.
- Put the notice immediately after the README title, before all usage content.
  The user requests the same policy for new shared GitHub projects and for
  previously worked-on projects when their chats are reopened.

## 0.0.2 — 2026-09-15

### Application code

- Reuse `build_mqtt_message`, config readers, hostname/event helpers, and template
  rendering to generate automation-compatible JSON reports with status, title,
  exit_code, warning, error, and stderr; retain event and host metadata.
- Add `encode_mqtt_report` to validate the JSON object contract and serialize
  with strict JSON numbers and correct escaping. Custom messages must now be
  JSON objects with success/failure status; plain text, legacy objects without
  status, wrong known-field types, and invalid JSON are rejected before publishing.
- Validate the report during config loading, before external side effects.
- Report defaults are success, hostname/action title, exit code 0 (1 for failure
  when auto), warning false, and empty error/output. Caller-supplied reports do
  not claim to measure the outcome of later MQTT/mail/power operations.
- Leave transport, mail routing, failure/continuation gates, dry-run semantics,
  power commands, and the original service behavior unchanged.

### Configuration, documentation, and verification

- Add all six `[report]` options to the complete config example (41 options total).
- Update custom JSON examples to include the automation's required status field.
- Explain the exact subscribed backup topics and the follow-up actions they
  trigger; retain the original active topic, QoS, retain, and safety values.
- Update current-use README, all-function/command map, and verification report.
- Add offline regression tests for JSON output, automation fields, validation
  before I/O, and unchanged power/failure behavior.
- Preserve every original input and the complete baseline inventory. Add the
  supplied automation verbatim under `reference/` for schema reference only;
  it is not installed or modified on Home Assistant.
- Regenerate the full ZIP inventory/hashes and external archive checksum.

## 0.0.1 — 2026-09-15

First documented baseline; the supplied project had no version metadata.
The user explicitly selected baseline 0.0.1. No earlier release is assumed.

### Application code and service

- No Python code changes. `mqtt_power_action_none.py` is byte-for-byte original.
- No service changes. `watchtower.service` is byte-for-byte original.
- Existing power actions, dry-run semantics, defaults, failure gates, mail
  behavior, and Paho compatibility paths are preserved.

### Configuration

- Keep every existing active configuration value unchanged.
- Add the eight supported SMTP options to the sendmail example; this section is
  inactive while `mail.backend = sendmail`.
- Correct custom JSON template escaping in the commented example.
- Clarify that dry-run still publishes/sends mail and still waits for the delay
  for shutdown/reboot; document timeout and JSON template limitations.

### Documentation and packaging

- Add current-use README with every CLI flag, all configuration options, exit
  behavior, and the supplied service's commands and deployment prerequisites.
- Add `commented_code_map.md` covering every function, nested callback, and
  application/service command, including the reason each exists.
- Add `VERSION`, this change log, `VERIFICATION.md`, and `MANIFEST.json`.
- Include exact copies of all three supplied files under `originals/`.
- Package the full supplied project and new release files in one clean ZIP.
- The referenced Compose file and success hook were not supplied; none were
  invented. Verification limitations are recorded in `VERIFICATION.md`.
