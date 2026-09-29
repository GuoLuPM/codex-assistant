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

- [x] Shared runtime configuration, locked build inputs and a reproducible bundle builder.
- [x] Installer, idempotence/overwrite protection, deployment check and concise handoff guide.
- [x] Clean-directory install using only bundled Python; file tampering and failure tests; synthetic pool/selection/PPT check.
- [x] Independent ordinary-speed Sol review, root/capability tests and privacy audit.

## Acceptance evidence (2026-09-29)

- 12 root tests and 49 catalog/pool tests passed. Tests cover changed payloads, unexpected files, unsafe paths, existing-code protection, saved environment preservation, invalid native executables and explicitly partial installations.
- Two fresh installations used the packaged Python 3.13.15 without system Python or Git. The second used Chinese and space-containing directory names. The optional 7890 HTTP proxy downloaded the pinned PDF wheel successfully.
- Synthetic XLSX import, renamed duplicate detection, exact source price/budget search, saved selection, PDF text extraction and one-slide PPT export passed. `ppt_verified=true` was returned only after reading back the exported product name and price.
- Repeating Setup reused both directories and preserved the local configuration and a private test file. A launcher invoked from another directory resolved the saved interpreter.
- Ordinary-speed GPT-6 Sol independently found configuration overwrite and file-only readiness gaps; both were fixed and verified. The package scan also caught and removed pip-generated auxiliary scripts containing build-machine paths.
- Public source/history audit passed. The candidate ZIP had 1,405 entries with no private source/configuration, personal machine paths or redistributed Codex components. The existing customer PPT hash was unchanged.

The final committed source is built into one `v0.1.0` ZIP. The GitHub Release records publication status, the source commit and the final asset SHA-256; it is the authoritative distribution record.
