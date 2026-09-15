# Versioning

The current package version is stored in `VERSION`. The application has no
`--version` command. Use this one canonical change log (case-insensitive Windows
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
