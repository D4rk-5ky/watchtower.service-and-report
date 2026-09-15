# Verification — 0.0.4

Checked on 2026-09-15 using Python 3.12.14 on Windows.

## Passed

- All 23 shipped offline tests pass. Existing JSON and power-safety tests remain;
  new tests exercise both relocated INIs, their commented JSON templates, local
  sendmail routing, SMTP STARTTLS command order, implicit TLS, environment-based
  credentials, empty-password rejection, SMTP error aborts, and full simulated
  MQTT/mail/delay/shutdown-dry-run order.
- Both application and test Python files compile in memory. No bytecode is
  written into the release. Application and service bytes match 0.0.3 exactly.
- Both INIs contain exactly all 41 supported section/option pairs, derived from
  the application syntax tree. Supplied SMTP values match after removing pasted
  Markdown escapes; extra_body names the actual script and report options were
  added. Placeholder credentials are not real credentials.
- The sendmail INI and supplied Home Assistant automation are byte-exact moves
  from 0.0.3. There are no original snapshots, old reference directory, or root INIs.
- All 27 application functions and 25 test methods/helpers are documented in
  commented_code_map.md. All config options and both setup paths are in README.
  The requested disclaimer remains directly below the README title.
- The real CLI still reports missing Paho and exits 1 on this machine. Help and
  argument parsing pass with the suite's in-memory Paho stand-in.
- Every previous package file is accounted for as retained, moved, or an explicitly
  removed snapshot; the SMTP example is the only added project file.

## Archive verification

The final ZIP has exactly 12 files. Its path inventory, duplicate absence, CRC,
file sizes and SHA-256 values are checked. The manifest accounts for the original
three supplied filenames and every 0.0.3 path, including authorized snapshot
removals and moves. It contains metadata only, not copies of old files. Its own
size/hash are null to avoid circular hashing; the external ZIP checksum includes
all archive bytes. No caches, bytecode, temporary files, or prior archives are
included. Old release ZIPs remain separate from the current project release.

## Not fully tested

- No live SMTP server/account or sendmail service was used. SMTP/TLS/login/send
  behavior was checked with mocks, so real credentials, server acceptance,
  certificate negotiation and recipient delivery still need live verification.
- Paho is unavailable locally. Real broker connections, authentication, QoS,
  retained-message handling and subscriber behavior were not tested.
- No Home Assistant engine was run. Its supplied YAML is a regular automation,
  not a parameterized blueprint; it was moved unchanged and was not installed.
- No Docker/systemd operation, shutdown, or reboot was executed. The external
  compose.yml and success.sh are still not supplied.

## Reproduce offline checks

From the extracted project directory:

```sh
python3 -B -m unittest discover -s tests -v
python3 -c "from pathlib import Path; p = Path('mqtt_power_action_none.py'); compile(p.read_bytes(), str(p), 'exec'); print('Syntax OK')"
```

The first runs the included suite with bytecode disabled, discovers tests in
tests/, and prints each result. The second checks syntax in memory without
executing the application or importing Paho. The tests send no real mail/MQTT.

The SMTP example intentionally retains shutdown + dry_run=true: normal use sends
real MQTT/mail, waits 10 seconds, and prints the poweroff command. Dry-run does
not suppress receiving automations. Keep both continuation flags false to abort
the later power path after MQTT or success-mail failure. All pre-existing runtime
limitations described in README remain; no runtime code changed in this release.
