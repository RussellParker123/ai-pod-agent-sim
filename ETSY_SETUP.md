# Etsy Integration Setup

Simulation is the default. To publish, first run the simulation, review and approve designs in the Review page, then publish that saved run. Live publication prompts for confirmation (skip with `--yes`).

## 1. Register an Etsy app
1. Create/sign in to your Etsy account and open your shop.
2. Go to https://www.etsy.com/developers/register and create an app.
3. Note the app **keystring** (`ETSY_API_KEY`) and **shared secret** (`ETSY_API_SECRET`).
4. Wait for personal/commercial access approval if required.

## 2. Get credentials
- `ETSY_SHOP_ID`: numeric shop id (`GET /v3/application/users/me`, or `GET /shops?shop_name=...`).
- `ETSY_ACCESS_TOKEN`: complete the OAuth 2.0 authorization-code (PKCE) flow with scopes `listings_w listings_r transactions_r shops_r`. See https://developers.etsy.com/documentation/essentials/authentication.

```bash
cp .env.example .env   # then fill in values
pip install -r requirements.txt
```
No banking info is needed in this project; Etsy handles payments.

## 3. Run
```bash
python -m app.sim.run_simulation                       # simulation only
python -m app.sim.run_simulation --publish-run run_YYYYMMDD_HHMMSS.json --real --draft-only  # reviewed real drafts
python -m app.sim.run_simulation --publish-run run_YYYYMMDD_HHMMSS.json --real              # reviewed active listings
```
Real publishing is rejected unless a saved run is selected. Etsy API failures stop publication and are reported as failures; they are not represented as simulated listings.

## Security
- Never commit `.env` or `.env.local` (both are in `.gitignore`); never paste keys into code, issues or logs. The setup wizard does not print entered credentials.
- Rotate keys/tokens if exposed. Access tokens expire (~1 hour); refresh with `EtsyClient.refresh_access_token`.

## Rate limiting
Etsy limits requests per second/day. The client retries HTTP 429/5xx with exponential backoff (honoring `Retry-After`).
Etsy charges a listing fee (~$0.20) per listing, and requires disclosing AI-generated content.

## Example output (`marketplace_listings` in the run JSON)
```json
{"design_id": "D001", "marketplace": "etsy", "mode": "real",
 "listing_id": 1234567890, "url": "https://www.etsy.com/listing/1234567890", "status": "draft", "note": ""}
```
