# Verification — 0.0.16

## Input inspection and release baseline

Inspected the complete Watchtower archive: runtime script, all tests, both service files, Compose/config/HA examples, README, code map, verification, manifest and release history. Compared the reporting implementation, config selection, app call sites, notification tests and HA JSON example in the supplied Syncerate archive. Treated the attached automation and old release notes as reference material, not instructions overriding the current request.

The input archive is internally inconsistent: VERSION, manifest and release history identify 0.0.15; the Python file declares 1.1.0, rejects action=none and does not implement its service's Watchtower arguments. Its old manifest describes a different Python file and omits files actually present. The initial supplied suite ran 47 tests with 8 failures, 48 errors (including subtest errors), and 3 skipped YAML/template tests in the original Python environment. These are baseline results, not the result for this release.

The package's established release sequence is authoritative: 0.0.15 → 0.0.16. The executable and VERSION now agree. No intermediate version was created. All 18 original file paths remain. The original input ZIPs were never modified.

## Completed checks

- **63 tests passed, zero failures/errors/skips**, using Python 3.12.14, PyYAML 6.0.3 and Jinja2 3.1.6.
- All four Python sources compiled successfully with bytecode directed outside the release tree.
- All five shipped YAML files parsed; JonsBo and generic manual success/failure guards evaluated with Jinja2 and controlled inputs.
- All three full INI examples contain the same 48 options. Every option is documented in README; all literal configuration reads and all runtime function names are accounted for in the examples/code map.
- Dependency-free CLI checks with `python -S`: help, version, missing/invalid arguments, missing config, local-only action=none, and both original generic safe-preview configurations.
- Full CLI current-run success and failure with a local fake Docker executable: marker parsing, --since wiring, report identity, status and process exit code. No Docker daemon was used.
- Real publisher child-process execution with a local fake Paho module: request reaches the worker, retain is false, payload is valid JSON, and an intentionally stalled publisher is killed by the configured hard deadline.
- Worker exception/nonzero-output paths suppress captured secret text; publish timeout cannot hang indefinitely.
- Runtime version and package VERSION both report 0.0.16. Root and systemd service files match byte-for-byte.

Tests cover both JSON and LogFmt Watchtower sessions, success with no updates, failed updates, warning success, invalid/missing/duplicate summaries, negative/boolean/string/inconsistent counters, explicit error/failed-container logs, bounded/redacted diagnostics, malformed logs, running/duplicate service state, bad/missing runtime markers, optional/omitted transport sections, safe local power suppression and notification failure gates.

Both ordinary and Watchtower previews are tested across all four MQTT/mail opt-in combinations. Default previews do not send either notification; selected channels send real test messages, master switches still disable them, and local power is never executed. Preview failures select failure mail, and preview email is clearly labeled.

JonsBo tests verify CleanUpIn success emits start_watchtower, matching completed Watchtower success emits shutdown_delay, and failure/unknown/preview/mismatched-host/mismatched-job/uncompleted/inconsistent success reports cannot authorize shutdown. Publisher/consumer topic agreement and the original Monday schedule are checked.

## Packaging verification

MANIFEST.json is regenerated from the actual supplied ZIP, not its stale manifest. Every original file is listed as unchanged/updated with original and current hashes/sizes; all added files are identified, with no removed paths. The manifest's own hash is null to avoid self-reference.

The final ZIP is reopened and checked for exact path equality with the release tree, all 18 original paths, byte-for-byte agreement, every recorded SHA-256/size, CRC integrity, one clean top-level directory, and no __pycache__, .pyc, .pyo, build/cache/dependency/temp files. An external SHA-256 checksum covers the entire archive, including its manifest.

Original .gitignore, original HomeAssistant/home-assistant-automation.yaml, original HomeAssistant/syncerate-all-servers.yaml, compose.example.yaml and systemd/watchtower.service remain byte-identical. Other original paths are updated intentionally and listed in the manifest. All three new files are included: the JonsBo config, JonsBo automation and compatibility test module.

## Not fully tested

- This macOS environment has no Docker executable/daemon or systemd-analyze. Native Linux service execution, container updates, actual image pulls, log formats beyond fixtures, and teardown behavior remain host tests. A startup/post-start failure may skip ExecStop; this release does not claim universal cleanup.
- No real broker/authentication/QoS delivery, SMTP/STARTTLS/SSL server, sendmail queue, power command, or Home Assistant instance was contacted or controlled. The real Paho library was not installed for these tests; its worker call boundary was exercised with a fake module.
- YAML parsing/Jinja branch evaluation is not full Home Assistant schema/runtime validation. Check the new automation in your installed HA release and verify the existing listener's start_watchtower/shutdown_delay commands before using the live chain.
- No run-ID correlation, replay suppression, duplicate-event deduplication, or missing-result timer was added to the daily event-driven chain. Preview guards, host/job identity, current-run log markers and non-retained publishing protect the intended path, but a replayed valid completion event remains an event. Use only the intended result publisher/topic.
- dry_run controls the reporter only. Starting the systemd unit still runs real Watchtower updates; use direct reporter invocations for notification previews.

The Syncerate reference project was read, not changed or repackaged.
