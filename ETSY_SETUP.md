# Etsy Integration Setup

Simulation is the default. Real Etsy calls only happen with `--real`, after a confirmation prompt (skip with `--yes`).

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
python -m app.sim.run_simulation --real --draft-only   # real drafts
python -m app.sim.run_simulation --real                # real active listings
python -m app.sim.run_simulation --real --revenue-goal 1000000000  # repeat until paid USD sales reach $1B
```
If an API call fails, that design falls back to a simulated listing.
The revenue-goal mode requires `transactions_r`, publishes a new active batch
only after confirmation, and checks paid, non-cancelled USD receipt subtotals.
It waits 24 hours between batches by default; use `--cycle-delay-seconds` to
change the interval. Stop it with Ctrl+C.

## Security
- Never commit `.env` (it is in `.gitignore`); never paste keys into code, issues or logs.
- Rotate keys/tokens if exposed. Access tokens expire (~1 hour); refresh with `EtsyClient.refresh_access_token`.

## Rate limiting
Etsy limits requests per second/day. The client retries HTTP 429/5xx with exponential backoff (honoring `Retry-After`).
Etsy charges a listing fee (~$0.20) per listing, and requires disclosing AI-generated content.

## Example output (`marketplace_listings` in the run JSON)
```json
{"design_id": "D001", "marketplace": "etsy", "mode": "real",
 "listing_id": 1234567890, "url": "https://www.etsy.com/listing/1234567890", "status": "draft", "note": ""}
```
