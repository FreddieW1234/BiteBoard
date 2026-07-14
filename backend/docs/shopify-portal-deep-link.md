# Shopify portal page — deep-link setup

Production update emails link to:

`https://bitepromotions.uk/pages/portal?order=SHOPIFY_ORDER_ID&item=OFFICE_ITEM_ID&proof=proof-v1.pdf`

The Shopify page embeds the portal iframe. Query params on the **store page** must reach the iframe so the portal can expand the order and open the proof.

## Option A — Add script (easiest)

On your `/pages/portal` theme template, after the portal iframe:

```html
<script src="https://bitepromotionsportal.co.uk/static/bite_portal_parent_deep_link.js" defer></script>
```

Replace the host with your deployed portal URL if different.

This forwards `order`, `item`, and `proof` from the Shopify page URL into the iframe `src`.

## Option B — Liquid iframe URL

Append params when building the iframe `src`:

```liquid
{% assign portal_base = 'https://bitepromotionsportal.co.uk/portal' %}
{% if customer %}
  {% capture portal_src %}{{ portal_base }}?customer_id={{ customer.id }}&email={{ customer.email | url_encode }}&shop_url={{ shop.url | url_encode }}{% if request.params.order %}&order={{ request.params.order | url_encode }}{% endif %}{% if request.params.item %}&item={{ request.params.item | url_encode }}{% endif %}{% if request.params.proof %}&proof={{ request.params.proof | url_encode }}{% endif %}{% endcapture %}
  <iframe src="{{ portal_src }}" ...></iframe>
{% endif %}
```

## Klaviyo email

Use `{{ event.portal_url }}` on the CTA button. Full HTML: `backend/templates/klaviyo/production_update_email.html`.

Events sent **before** this deploy won't have `portal_url`; use the default fallback or re-send a test.
