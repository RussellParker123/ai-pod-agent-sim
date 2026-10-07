# Etsy Setup Wizard Guide

Run: `python -m app.setup.etsy_wizard` (or `python app/setup/etsy_wizard.py`).

## Steps
1. **Create an Etsy seller account** at https://www.etsy.com/sell. Etsy requires identity verification and a payout method; this cannot be automated.
2. **Register a developer app** at https://www.etsy.com/developers (name: "AI POD Agent Simulator"). Note the Keystring (API key) and Shared secret.
3. **Generate an OAuth token.** Open the authorization URL, approve access, and exchange the `code` in the redirect URL for an access token (Etsy uses OAuth 2.0 with PKCE; see https://developers.etsy.com/documentation/essentials/authentication).
4. **Enter credentials**: `ETSY_API_KEY`, `ETSY_API_SECRET`, `ETSY_SHOP_ID`, `ETSY_ACCESS_TOKEN`. Secrets are hidden as you type.
5. **Validation**: the wizard calls Etsy's shop endpoint to confirm the token works.
6. **Test listing** (optional): creates a draft titled `TEST: AI Art - <timestamp>`; you may delete it or keep the draft.
7. **Save**: writes `.env` (or `.env.local`) with owner-only permissions after confirmation.

## Finding your Shop ID
Call `GET https://openapi.etsy.com/v3/application/users/me` (with your token and `x-api-key`); it returns `shop_id`. 

## Security
- Never commit `.env` to Git; the wizard warns if it is not in `.gitignore`.
- Credentials are masked (first/last 4 characters) when displayed.

## Troubleshooting
- **Network error**: check your internet connection.
- **401/403**: wrong API key or expired token. Access tokens expire after about an hour; use your refresh token (`grant_type=refresh_token` at `https://api.etsy.com/v3/public/oauth/token`) or repeat step 3.
- **429**: Etsy rate limits requests per second and per day; wait and retry.
- **Permission denied writing .env**: `chmod u+w .env` or run with appropriate rights, or choose to print credentials instead.
