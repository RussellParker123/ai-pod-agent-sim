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
