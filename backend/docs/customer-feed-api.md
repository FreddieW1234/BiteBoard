# Bite Promotions product feed API

For trade customers who want our catalogue on their own website.

## This is a daily feed, not a live API

Pull the feed **once a day** from a scheduled job on your server (for example a
nightly cron task), save the products into your own database, and have your
website show products from that copy. **Your website's pages should never call
this API themselves.** If a page called it every time it was viewed, a busy day
would use up the limit of 60 requests per key per hour and your product pages
would stop loading. Our catalogue only changes once a day, so a daily pull is
always up to date.

## Setup

Set two environment variables on the server that runs your nightly job:

```
BITE_API_URL=https://api.bitepromotions.co.uk
BITE_API_KEY=bite_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Keep the URL in configuration rather than in your code, so a future address
change is a config edit. Your job then calls `$BITE_API_URL/api/v1/feed` with
the key, and keeps the last `ETag` it received (in a file or your database, not
an environment variable) to send back as `If-None-Match`.

## Authentication

Every request needs your key in the `Authorization` header:

```
Authorization: Bearer bite_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Keep the key on your server. Never put it in browser JavaScript or a public
code repository. If it leaks, ask us to revoke it and we will issue a new one.
Any authentication problem returns `401` with no further detail.

## Endpoints

### `GET https://api.bitepromotions.co.uk/api/v1/ping`

Checks your key without downloading the catalogue.

```json
{ "ok": true, "price_list": "trade", "generated_at": "2026-09-24T03:15:12Z" }
```

### `GET https://api.bitepromotions.co.uk/api/v1/feed`

The full catalogue with **your** prices. Send `Accept-Encoding: gzip`.
The response has an `ETag`. Send it back as `If-None-Match` on your next pull;
if nothing has changed you get `304 Not Modified` and no body.

```json
{
  "generated_at": "2026-09-24T03:15:12Z",
  "currency": "GBP",
  "prices_include_vat": false,
  "product_count": 487,
  "products": [
    {
      "id": "8123456789",
      "handle": "personalised-mini-chocolate-bar",
      "sku": "CHOC-MINI-001",
      "title": "Personalised Mini Chocolate Bar",
      "description": "…",
      "product_type": "Chocolate",
      "url": "https://bitepromotions.co.uk/products/personalised-mini-chocolate-bar",
      "updated_at": "2026-09-20T14:02:11Z",
      "categories": ["Chocolate"],
      "subcategories": ["Bars"],
      "sub_subcategories": [],
      "images": ["https://cdn.shopify.com/…"],
      "moq": 100,
      "case_quantity": 50,
      "lead_times": [
        { "min_qty": 1, "max_qty": 4999, "working_days": 10 },
        { "min_qty": 5000, "max_qty": 10000, "working_days": 15 }
      ],
      "unit_weight_g": 12,
      "product_size": "80mm * 40mm * 10mm",
      "diameter_mm": null,
      "artwork_guidelines_url": "https://cdn.shopify.com/…/Artwork_Guidelines.pdf",
      "artwork_templates_url": "https://cdn.shopify.com/…/CHOC-MINI-001_artwork_templates.zip",
      "stock_designs_url": null,
      "filters": { "size": ["Mini"] },
      "search_terms": [],
      "origination": 50,
      "options": {
        "colours": { "product": [{ "name": "Gold", "code": "g" }] },
        "custom": [{ "name": "Wrapper", "choices": ["Matt", "Gloss"] }],
        "choices": { "print": ["Outside Only", "Outside + Inside"] }
      },
      "prices_include_vat": false,
      "price_breaks": [
        { "min": 100, "max": 249, "price": 1.95 },
        { "min": 250, "max": 499, "price": 1.72 }
      ]
    }
  ]
}
```

- **All prices exclude VAT.** They are GBP per unit, before VAT. If your site
  shows prices including VAT, add VAT at the applicable rate before displaying
  them. `prices_include_vat` is `false` at the top of the response and on every
  product so this can't be missed.
- A product without prices for your account is left out of the feed. It never
  appears with a price of 0.
- Every product includes `id`, `handle`, `sku`, `title`, `url`, `updated_at`,
  prices, description, categories, images, ordering (MOQ, case quantity, lead
  times), size and weight (including `diameter_mm` and `packing_info`), options,
  filters (`brand`, `eco`, `packaging`, `size`) and `search_terms`, dietary,
  allergens, ingredients (ingredients, nutrition, shelf life), product info
  (`product_info`, what's inside, print and recycling info) and artwork files.
- Use `id` or `handle` to identify a product - a few products share a `sku`.
- `artwork_guidelines_url` (PDF), `artwork_templates_url` (ZIP of templates)
  and `stock_designs_url` are direct download links, or `null` if the product
  has none. You may link to them or copy the files to your own hosting.
- `options.choices` lists extra choices the product offers, e.g. `print`
  (outside only / outside + inside), `foil`, `mailer`, `mailer_packing`,
  `packaging`.
- `lead_times` has a third, smaller band (1-1,499 units) on products that
  have one.
- `product_size` is length * width * height in millimetres, e.g.
  `"78mm * 72mm * 27mm"`. Some products only have two dimensions. `shelf_life`
  is e.g. `"12 months"`, or occasionally text such as `"For best before see sachet"`.
- `dietary` says which diets a product is suitable for, as `true` / `false`, e.g.
  `{"vegan": false, "vegetarian": true, "halal": true}`. A diet not listed means
  we hold no information for it.
- `allergens` is a list in the order shown on our product pages, one row per
  allergen we hold a statement for:
  `[{"allergen": "Milk", "statement": "Milk present as an ingredient."}, …]`.
  Allergens are Celery, Cereals containing gluten, Crustaceans, Egg, Fish,
  Lupin, Milk, Molluscs, Mustard, Tree nuts, Peanuts, Sesame, Soya, and
  Sulphur dioxide and sulphites. Always check allergen information against the
  product itself before relying on it.
- A product can sit in more than one category, so the category fields are lists.
- `working_days` is usually a number, but may be text such as
  `"Contact Bite Promotions for a specific leadtime"`.
- Any field we have no value for is `null`, or an empty list for list fields.
- Image URLs point at Shopify's CDN. You may hotlink them or copy them to your
  own hosting.

## Status codes

| Code | Meaning |
|---|---|
| 200 | Feed or ping body |
| 304 | Unchanged since your last `ETag` |
| 401 | Key missing, invalid, revoked or expired |
| 429 | Over 60 requests this hour; wait for `Retry-After` seconds |
| 503 | Service starting or catalogue being prepared; retry after `Retry-After` seconds |

Your job must handle `503`: wait for the `Retry-After` seconds, then retry. The
first pull after a quiet period often gets one.
