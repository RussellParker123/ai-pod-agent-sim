"""Maps our internal product_type -> real Etsy taxonomy_id / Printful variant_id.

These IDs are specific to your actual Etsy shop category structure and the
exact Printful blank products you choose to sell. The values below are
reasonable starting points but are NOT guaranteed to match your shop/catalog
choices — confirm and replace them before going live:

- Etsy taxonomy ids: GET https://openapi.etsy.com/v3/application/seller-taxonomy/nodes
  (search the response for "Mugs", "T-shirts", "Tote Bags", etc.)
- Printful catalog variant ids: GET https://api.printful.com/products
  (pick the exact blank + size + color you want to sell)
"""

# Etsy seller-taxonomy node ids (placeholders — verify against the taxonomy
# endpoint above for your shop's exact categories).
PRODUCT_TAXONOMY = {
    "mug": 1633,
    "tshirt": 1313,
    "tote": 2090,
}

# Printful catalog variant ids (placeholders — verify against the Printful
# catalog for the exact blank/size/color you intend to sell).
PRODUCT_PRINTFUL_VARIANT = {
    "mug": 1320,
    "tshirt": 4012,
    "tote": 10386,
}
