# Temporary product sharing

**Goal:** A large share-icon button on the existing selection page creates a temporary HTTPS URL for read-only viewing, with copy, expiry and stop controls. User approved this design and implementation in conversation; proceed without another approval gate.

**Architecture:** Keep the owner server on loopback with its existing Host/Origin/token protection. A separate loopback HTTP listener receives Cloudflare Quick Tunnel traffic and serves only an explicit public product projection and approved images. It has no selection, sharing-control, database or file-browsing endpoints. Share lifetime is bounded and owned by the selection service; subprocesses are reaped on stop, expiry and shutdown.

**Scope:** Share this page's frozen candidates and displayed prices. Do not transmit source filenames, locators, annotations/evidence, private tokens or current choices. Reuse the existing card renderer in a read-only mode. No accounts, independent customer choices or remote PPT generation. One-hour default; owner may choose 15 minutes or 4 hours. A configured HTTPS public endpoint must return the expected session probe before a URL is reported ready. Temporary provider availability is not guaranteed.

## Tasks

- [x] Lock and verify the official Windows cloudflared binary; run a synthetic connectivity probe. Respect a scoped download proxy; do not change global VPN/firewall settings.
- [x] Test public field allowlist, HTTP read-only isolation, control Origin checks, duplicate start, expiry, cancellation and unexpected child exit; implement snapshot/server/manager modules.
- [x] Extend local HTTP controls and add accessible share dialog with local DOM updates, copy fallback, progress and plain-language failures. Keep selections responsive and unchanged.
- [x] Verify real desktop/mobile UI, external read-only viewing with synthetic products, stop/expiry, existing selection regressions and subprocess cleanup. Independent ordinary-speed GPT-6 Sol review if useful.
- [x] Update pool/deployment guides and Windows bundle support.
- [ ] Run public audit, sync code and refresh the Windows Release.

Review found that sealing a selection ended a still-valid share. A regression test reproduced it; the owner service now retains the independent share lifetime after sealing, while explicit session close still revokes it. Real Edge checks covered desktop 1280×900 and mobile 390×844, approved image loading, clipboard, anonymous read-only viewing, rejected writes, preserved choices, stable card DOM, revocation and no console/page errors. Tests use synthetic data only; recipient network availability is not universally verified.

## Review focus

1. Sharing must never forward the private owner endpoint, even with a guessed path or POST body.
2. Start/stop races and a cancelled download cannot leave an active public listener or tunnel.
3. Provider startup text is not proof that the externally reachable product page works.
4. Sharing near the local service deadline remains usable for the stated lifetime; owner shutdown still closes it.
5. Public data is an explicit field projection; images are confined to approved pool assets, and malicious source text stays text in the browser.
