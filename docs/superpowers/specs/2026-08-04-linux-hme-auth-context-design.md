# Linux HME Authentication Context Repair

## Goal

Restore Hide My Email generation for the existing pure-Linux SRP and 2FA flow. The application must obtain and preserve the iCloud web authentication context required by the maildomain service without importing browser cookies or using a headless browser.

## Confirmed Failure

Current generation requests return one of these responses:

- HTTP 401 with `Forbidden`
- HTTP 403 with an empty body
- JSON error `Missing X-APPLE-WEBAUTH-USER cookie`

The existing login can complete SRP and 2FA, but authentication success is recorded before the resulting iCloud web session is proven usable by the HME service. Accounts initially configured for China also remain on China endpoints when `accountLogin` returns `domainToUse=iCloud.com`.

## Architecture

### Region Resolution

`ICloudSession` will normalize Apple's `domainToUse` value and update all region-dependent endpoints. When `accountLogin` redirects an account from China to global iCloud, token exchange is repeated against the resolved setup service so the session cookies and bootstrap data belong to the final region.

### HME Service Context

The maildomain host will be resolved in this order:

1. `webservices.maildomainws.url`
2. `userPartition`, converted to `pNNN-maildomainws.icloud.com` or `.icloud.com.cn`
3. `webservices.premiummailsettings.url` for compatibility
4. the existing `p68` default

The HME client will receive the final DSID, normalized client ID, origin, language, and resolved service URL from the validated session.

### Request Protocol

HME requests will match the current upstream captured web-client contract:

- `clientBuildNumber=2626Build17`
- `clientMasteringNumber=2626Build17`
- a consistent Chrome 150 User-Agent and client hints
- region-correct Origin, Referer, language, and `langCode`
- JSON encoded through the HTTP client's structured `json` argument while preserving the web client's `text/plain` content type

The application will stop random fingerprint rotation. Rotating to mutually inconsistent browser profiles cannot repair an account-bound authentication failure and makes the request context differ from the login session.

### Authentication Validation

After setup validation, the session must have a DSID and `X-APPLE-WEBAUTH-USER`. If either is missing, generation will stop with an actionable authentication error. The application will not retry HME requests that cannot become valid through waiting.

### Error Handling

HTTP status, content type, and response preview remain available for diagnostics. HTTP 401 and 403, plus the `Missing X-APPLE-WEBAUTH-USER cookie` response, are classified as authentication-context failures. Generation stops after the first failed batch instead of looping indefinitely. Only explicit Apple rate-limit errors enter cooldown handling.

## Compatibility

- Existing dashboard login and 2FA flows remain unchanged.
- Existing saved sessions remain loadable; endpoint resolution is refreshed during authentication validation.
- Both global iCloud and iCloud China remain supported.
- No browser-cookie import or headless-browser dependency is introduced.

## Tests

Offline tests will cover:

- Apple domain normalization and endpoint switching
- global and China maildomain host resolution from `userPartition`
- preference for `webservices.maildomainws`
- current build number and internally consistent browser headers
- missing HME authorization context
- HTTP 401/403 classification
- generation termination on non-rate-limit failures

The full test suite, Python compilation, and Docker image build will be run before completion. A real Apple account is still required to prove the external service accepts the repaired session.
