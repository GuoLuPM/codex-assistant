# Windows release bundle plan

**Goal:** Publish one reproducible Windows x64 ZIP and a Codex handoff guide for a computer without Python, Git or GitHub login.

**Design:** Bundle official embedded Python and pinned permissively licensed core wheels. Install code and runtime in separate D-drive directories with scoped configuration. Download the pinned PDF wheel directly from PyPI on the recipient device; discover that device's Codex PPT runtime instead of redistributing proprietary components. Keep the existing extraction, search, selection and PPT pipeline.

**Authorization:** User requested implementation and publication to Releases, including the handoff instructions. Continue through verification and publishing without a further approval step.

## Constraints and checks

- Only tracked public source plus hash-pinned official dependencies enters the ZIP; no pool, credentials, private configuration, Codex binaries or skill copies.
- Check every payload hash and reject path traversal/junctions. Existing nonempty installations are never silently overwritten; identical installations can resume.
- Default code D:\code\assistant; runtime D:\tools\codex-assistant. No global PATH, proxy, execution-policy or GitHub-account changes.
- Optional HTTP proxy is scoped to download operations. Failed PDF/PPT setup reports the missing capability instead of claiming completion.
- Read persisted environment configuration from any working directory, preserving explicit overrides and old setups.

## Work

- [ ] Shared runtime configuration, locked build inputs and a reproducible bundle builder.
- [ ] Installer, idempotence/overwrite protection, deployment check and concise handoff guide.
- [ ] Clean-directory install using only bundled Python; file tampering and failure tests; synthetic pool/selection/PPT check.
- [ ] Independent ordinary-speed Sol review, root/capability tests, privacy audit, code sync and one Release ZIP.
