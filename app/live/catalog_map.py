"""Maps our internal product_type -> real Etsy taxonomy_id / Printful variant_id.

These IDs are specific to your actual Etsy shop category structure and the
exact Printful blank products you choose to sell.

- Etsy taxonomy ids: GET https://openapi.etsy.com/v3/application/seller-taxonomy/nodes
  (search the response for "Mugs", "T-shirts", "Tote Bags", etc.) — verified
  live against your shop's taxonomy on 2026-10-08 (see values below).
- Printful catalog variant ids: GET https://api.printful.com/products
  (pick the exact blank + size + color you want to sell) — verified live
  against the Printful catalog API on 2026-10-08 (see values below).
"""

# Etsy seller-taxonomy node ids, verified live against
# GET /v3/application/seller-taxonomy/nodes on 2026-10-08:
#   mug    -> 1062  = Home & Living > Kitchen & Dining > Drink & Barware > Drinkware > Mugs
#   tshirt -> 482   = Clothing > Gender-Neutral Adult Clothing > Tops & Tees > T-shirts
#   tote   -> 190   = Bags & Purses > Totes
PRODUCT_TAXONOMY = {
    "mug": 1062,
    "tshirt": 482,
    "tote": 190,
}

# Printful catalog variant ids, verified live against GET /products and
# GET /products/variant/{id} on 2026-10-08:
#   mug    -> 1320  = White Glossy Mug, 11 oz
#   tshirt -> 4012  = Bella + Canvas 3001 Unisex Staple T-Shirt, White / M
#   tote   -> 10457 = Eco Tote Bag | Econscious EC8000, Black / One size
# (the previous tote placeholder, 10386, was actually a mis-copied t-shirt
# variant id, not a tote at all — fixed here.)
PRODUCT_PRINTFUL_VARIANT = {
    "mug": 1320,
    "tshirt": 4012,
    "tote": 10457,
}

# Printful catalog *product* ids (the parent blank each variant above
# belongs to) — needed for the Mockup Generator API, which operates per
# product rather than per variant. Verified live against
# GET /products/variant/{id} on 2026-10-08.
#   mug    -> 19  = White Glossy Mug
#   tshirt -> 71  = Bella + Canvas 3001 Unisex Staple T-Shirt
#   tote   -> 367 = Eco Tote Bag | Econscious EC8000
PRODUCT_PRINTFUL_PRODUCT = {
    "mug": 19,
    "tshirt": 71,
    "tote": 367,
}

# Confirmed catalog details for listing copy; other products retain their templates.
PRODUCT_CATALOG_DETAILS = {
    "tote": {"name": "Eco Tote Bag | Econscious EC8000", "size": "One size"},
}

# Real Printful per-unit blank cost (the "Price" shown on the catalog page
# for each variant above, e.g. $6.07 for the White Glossy Mug 11oz) — this
# is what pricing_agent's target-margin math is based off of, so it must
# track Printful's actual price, not a guess. Verified live against
# GET /products/variant/{id} on 2026-10-08 (previous placeholders had
# drifted quite far for tshirt/tote — tote in particular was ~55% under
# the real cost, which would have priced totes at a loss).
# Use the base catalog price, not the $13.91 Printful Growth account discount.
PRODUCT_UNIT_COSTS = {
    "mug": 6.07,
    "tshirt": 11.92,
    "tote": 15.87,
}

# Shipping weight/box dimensions for a calculated shipping profile — Etsy
# requires these on every physical listing that uses a "calculated"
# (vs. flat-rate) shipping profile. Conservative real-world packaged
# estimates for each Printful blank above; your actual package may run a
# bit lighter, but overestimating slightly just means Etsy shows a
# marginally higher calculated shipping cost to buyers, never a failure.
#   mug    -> ~1 lb (16 oz) boxed, roughly 4x4x4 in
#   tshirt -> ~6 oz in a poly mailer, roughly 12x9x1 in
#   tote   -> ~8 oz in a poly mailer, roughly 15x16x1 in
PRODUCT_SHIP_DIMENSIONS = {
    "mug": {"item_weight": 16, "item_length": 4, "item_width": 4, "item_height": 4},
    "tshirt": {"item_weight": 6, "item_length": 12, "item_width": 9, "item_height": 1},
    "tote": {"item_weight": 8, "item_length": 15, "item_width": 16, "item_height": 1},
}
