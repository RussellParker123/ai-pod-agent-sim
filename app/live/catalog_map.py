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
#   tote   -> 10457 = Econscious EC8000 Organic Cotton Tote Bag, Black / One size
# (the previous tote placeholder, 10386, was actually a mis-copied t-shirt
# variant id, not a tote at all — fixed here.)
PRODUCT_PRINTFUL_VARIANT = {
    "mug": 1320,
    "tshirt": 4012,
    "tote": 10457,
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
