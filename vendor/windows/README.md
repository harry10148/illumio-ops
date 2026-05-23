# Vendored Windows binaries

## nssm-2.24.zip

- **Source:** https://nssm.cc/release/nssm-2.24.zip
- **Released:** 2014-07-31
- **SHA256:** `727d1e42275c605e0f04aba98095c38a8e1e46def453cdffce42869428aa6743`
- **Purpose:** Windows service manager (wraps illumio-ops as a Windows service)
- **License:** Public domain (per nssm.cc)
- **Replacement candidate:** WinSW (https://github.com/winsw/winsw) — actively maintained.
  Migration tracked separately; nssm 2.24 is stable for current needs.

## Verification

To re-verify integrity:

```sh
sha256sum vendor/windows/nssm-2.24.zip
```

Output must match the SHA256 above. If it doesn't, the file has been altered
since this README was committed.
