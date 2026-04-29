# Setting Up a GEE Service Account for CI

**TODO**: write full setup guide — see docs/build_guide.md Phase 2, Step 2.2

Steps:
1. Create service account in Google Cloud Console
2. Register it in GEE (code.earthengine.google.com → Assets → Service Accounts)
3. Export JSON key
4. Base64-encode: `base64 -i key.json | tr -d '\n'`
5. Add as GitHub secret `GEE_SERVICE_ACCOUNT_KEY`
