# Security

Privato guards access to people's email, calendars, files and chats, so we take reports seriously.

## Reporting a vulnerability

Please don't open a public issue. Report it privately on GitHub: **Security → Report a vulnerability** on this repository. Include what an attacker could reach, and steps to reproduce.

We'll acknowledge your report within a few days, keep you posted while we fix it, and credit you in the release notes unless you'd rather we didn't.

## Scope

This repository, and the hosted service at `app.privato.dev` and `api.privato.dev`. Especially interesting:

- an AI app reading data outside its grant, or after it ended
- getting around an approval, a revocation or a filter
- reaching another person's data, accounts or approvals
- getting instructions in an email, file or tool result past the injection check

While testing, use your own accounts only. No denial-of-service, spam, or social engineering of people.

## Supported versions

Fixes go into the latest release.
