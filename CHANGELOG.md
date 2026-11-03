# Changelog

Notable changes to Privato. Versions follow [semantic versioning](https://semver.org); each `vX.Y.Z` tag becomes a GitHub release with the notes below.

## [0.2.0] - 2026-11-02

- **Renamed from nonce to Privato.** The Python package is now `privato`, settings are `PRIVATO_*`, and new keys start with `privato_`. `NONCE_*` settings and `nonce_` keys keep working, so connected apps don't need to reconnect. You'll be signed out of the dashboard once.
- **New address.** The hosted service moved to privato.dev, with the API at `api.privato.dev`. Apps connected through the old address keep working.
- **A clearer README** that explains what Privato does before how it works.

## [0.1.0] - 2026-11-01

The first release.

- **Grants, not credentials.** AI apps ask Privato for a short, filtered pass to Gmail, Google Calendar, Google Drive or Slack. Privato makes every call itself, so apps never hold your tokens, and every search runs inside the grant's filter.
- **Checks on every step.** Each request, each search inside a grant, and each item an app reads is checked: access is allowed, held for you, denied, or ended the moment an app drifts, crawls or reaches for sensitive data. Emails that try to instruct the AI are withheld.
- **Modes and offline hours.** Cautious, Standard or Relaxed per app; nothing goes through on its own during offline hours.
- **Tasks.** Requests made for one question are grouped, so one Allow covers them and one Stop ends them.
- **Several accounts** of each kind, with the app recommending which to use and you choosing before you allow.
- **Your own connectors.** Add an MCP server or HTTP API; Privato keeps its key and puts every call through the same approvals.
- **Connect any MCP app** (ChatGPT, Claude, Cursor and others) with OAuth 2.1, or a key for apps that can't sign in.
- **Pluggable detectors.** Signals come from OpenAI's Decisions API with your own key, an HTTP service, or a Python class; with none, every request comes to you.
- **Detector benchmark.** 52 labeled cases scored through the real policy, to compare detectors.
- **Phone approvals.** Installable dashboard with push notifications; text messages behind a setting.
- **Guided setup** for new users.

[0.1.0]: https://github.com/roe-ai/Privato/releases/tag/v0.1.0
