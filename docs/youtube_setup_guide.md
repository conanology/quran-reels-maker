# YouTube account setup and operational checks

Interactive authorization is an explicit operator action. Automatic jobs use existing credentials and fail if they cannot refresh noninteractively. Never put real client/token files in Git, screenshots, test fixtures or recovery artifacts.

1. Create/select a project in [Google Cloud Console](https://console.cloud.google.com/) and enable YouTube Data API v3.
2. Configure its OAuth consent/audience and permitted users according to the project's needs. Do not publish an OAuth application solely to work around a token problem; review Google's current verification/testing requirements.
3. Create an OAuth client suitable for an installed desktop application. Save its downloaded JSON as `client_secrets.json` in this repository's root.
4. Run `.\venv\Scripts\python.exe main.py setup-youtube` locally. Review the intended Google account/channel and requested permissions before authorizing.
5. Configure `YOUTUBE_EXPECTED_CHANNEL_ID` from the intended channel's actual ID, plus the Telegram review chat and exact `TELEGRAM_APPROVER_ID` for automatic publication.
6. Verify credentials/expiry and account identity through explicitly authorized checks before enabling automation. Saved JSON preserves expiry; local disconnect removes loadable local credential formats but does not claim remote revocation.

`auto --test` only generates. To intentionally make a private upload, use `upload <path> --privacy private`; that contacts and mutates the live account. Privacy/processing completion is confirmed before the client reports a processed/published result. Uncertain attempts must be reconciled instead of retried blindly.

Current account/project quota and verification restrictions must be checked in Google Cloud and the [official upload reference](https://developers.google.com/youtube/v3/docs/videos/insert). Do not infer daily upload capacity from historical unit-cost examples. OAuth guidance: [installed applications](https://developers.google.com/identity/protocols/oauth2/native-app), [YouTube authentication](https://developers.google.com/youtube/v3/guides/authentication).

For Actions, provide credential JSON through the named secrets and restore it via `scripts/ci_state.py credentials`; shell interpolation is not used. State bootstrap, domain/account review and artifact retention/recovery requirements are described in [README](../README.md). Credential refresh, account checks, remote revocation and uploads were not performed as part of the local remediation verification.
