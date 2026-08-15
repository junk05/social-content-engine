# Meta callback contract (M0)

Status: `DOCUMENTED`; fixture-tested locally, not yet verified by a live Meta call.

Official evidence checked on 2026-08-15:

- Threads OAuth collection: https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api
- Meta Threads sample: https://github.com/fbsamples/threads_api
- Data deletion callback: https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback
- OAuth manual flow: https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow

The developer.facebook.com pages returned HTTP 429 during this review. The
official Meta Postman collection and `fbsamples` repository were therefore used
as additional primary evidence. Live Meta verification remains pending.

## OAuth redirect callback

- Route: `GET /meta/oauth/callback`
- Success parameters: `code`; `state` when it was supplied to authorization.
- Error parameters: `error`, optionally `error_reason` and `error_description`;
  `state` should still be checked when present.
- Local requirement: `state` must exactly match `META_OAUTH_STATE` using a
  constant-time comparison. Missing/mismatched state is rejected.
- Response: Meta does not require a special response body. This implementation
  returns a small JSON acknowledgement and never stores or logs the code.
- Token exchange: separate POST to `https://graph.threads.net/oauth/access_token`
  using the same `redirect_uri`; it is intentionally outside this callback.

## Deauthorization callback

- Route: `POST /meta/deauthorization`
- Content type: `application/x-www-form-urlencoded`
- Required parameter: `signed_request`.
- Verification: split `<signature>.<payload>`, base64url-decode, require payload
  `algorithm=HMAC-SHA256`, calculate HMAC-SHA256 over the encoded payload using
  `THREADS_APP_SECRET`, and compare signatures in constant time.
- Required payload field: `user_id`.
- Response: HTTP 200 acknowledgement. No special response schema was found in
  the official material; the local JSON body is an implementation contract.

## Data deletion request callback

- Route: `POST /meta/data-deletion`
- Content type, parameter, signature verification, and `user_id`: same as
  deauthorization.
- Required response: JSON object with `url` and alphanumeric
  `confirmation_code`.
- Local behavior: M0 does not persist OAuth user profiles or tokens. It records
  no personal deletion queue; the derived confirmation code is deterministic,
  opaque, and contains no user ID. `GET /meta/data-deletion/status?code=...`
  reports `completed` for a valid code.
- `META_PUBLIC_BASE_URL` must be the externally reachable HTTPS tunnel origin so
  the returned status URL is public.

## Security and limits

- Secrets are environment variables only and are never returned or logged.
- Request bodies larger than 64 KiB are rejected.
- Unknown routes/methods and malformed forms are rejected.
- This server is a temporary local M0 callback receiver, not production
  infrastructure.
