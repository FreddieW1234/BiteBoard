# Bite Promotions product feed API

For trade customers who want our catalogue on their own website.

## This is a daily feed, not a live API

Pull the feed **once a day** from a scheduled job on your server, store the
result, and serve your website from your own copy. **Never call this API while
a visitor is loading a page.** Our catalogue changes at most daily, and the feed
is limited to 60 requests per key per hour.

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
      "product_size": "80 x 40mm",
      "origination": 50,
      "options": {
        "colours": { "product": [{ "name": "Gold", "code": "g" }] },
        "custom": [{ "name": "Wrapper", "choices": ["Matt", "Gloss"] }]
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
