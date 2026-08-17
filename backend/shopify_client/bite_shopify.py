#!/usr/bin/env python3
"""
bite_shopify.py - shared Shopify Admin API client.

Used by the one-off migration script and by the Product Manager app, so the
create/update logic lives in exactly one place.

Reads STORE_DOMAIN / ACCESS_TOKEN / API_VERSION from config.py.

MetafieldDefinitionUpdate caveat:
  Several input fields (notably deprecated useAsCollectionCondition, and some
  capability toggles) default to OFF when omitted. Any metafieldDefinitionUpdate
  that is not deliberately changing a capability must echo the live value back
  (see append_choice). Omitting smartCollectionCondition while smart collections
  reference the definition yields CAPABILITY_CANNOT_BE_DISABLED.
"""

import json
import time

import requests

try:
    from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION
except ImportError:  # allow import for inspection without config present
    STORE_DOMAIN = ACCESS_TOKEN = API_VERSION = None


class ShopifyError(RuntimeError):
    pass


class Shopify:
    def __init__(self, domain=None, token=None, api_version=None):
        self.domain = str(domain or STORE_DOMAIN or "").replace(
            "https://", "").replace("http://", "").rstrip("/").strip()
        self.token = token or ACCESS_TOKEN
        self.api_version = (api_version or API_VERSION or "").strip()
        if not self.domain or not self.token:
            raise ShopifyError("STORE_DOMAIN / ACCESS_TOKEN not configured")
        if not self.api_version:
            raise ShopifyError(
                "API_VERSION not configured (set SHOPIFY_API_VERSION / config.API_VERSION)"
            )
        self._cache = {}

    # ------------------------------------------------------------------ core
    @property
    def endpoint(self):
        return f"https://{self.domain}/admin/api/{self.api_version}/graphql.json"

    def gql(self, query, variables=None, retries=4):
        """POST a GraphQL query. Retries on throttling and 5xx."""
        for attempt in range(retries):
            resp = requests.post(
                self.endpoint,
                headers={"X-Shopify-Access-Token": self.token,
                         "Content-Type": "application/json"},
                json={"query": query, "variables": variables or {}},
                timeout=45,
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            payload = resp.json()
            errors = payload.get("errors")
            if errors:
                throttled = any(
                    (e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors)
                if throttled and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise ShopifyError(f"GraphQL errors: {errors}")
            return payload["data"]
        raise ShopifyError(f"giving up after {retries} attempts")

    @staticmethod
    def _check(result, label):
        """Raise on userErrors. Every mutation goes through here."""
        errs = result.get("userErrors") or []
        if errs:
            raise ShopifyError(f"{label}: {errs}")
        return result

    # ------------------------------------------------------------------ shop
    def shop_gid(self):
        if "shop_gid" not in self._cache:
            self._cache["shop_gid"] = self.gql("{ shop { id } }")["shop"]["id"]
        return self._cache["shop_gid"]

    def online_store_publication_id(self):
        """GID of the Online Store sales channel, for publish/unpublish."""
        if "pub" not in self._cache:
            data = self.gql("""
              { publications(first: 25) { edges { node { id name } } } }
            """)
            for edge in data["publications"]["edges"]:
                if edge["node"]["name"] == "Online Store":
                    self._cache["pub"] = edge["node"]["id"]
                    break
            else:
                raise ShopifyError("Online Store publication not found")
        return self._cache["pub"]

    # --------------------------------------------------- metafield definitions
    def metafield_definition(self, namespace, key, owner_type="PRODUCT"):
        """
        Returns {'id', 'choices', 'smart_collection_condition'} or None.

        smart_collection_condition is capabilities.smartCollectionCondition.enabled
        (bool). Cached with the definition so append_choice can echo it without
        a second round trip.
        """
        ck = ("mfdef", namespace, key, owner_type)
        if ck in self._cache:
            return self._cache[ck]
        data = self.gql("""
          query($ns: String!, $key: String!, $owner: MetafieldOwnerType!) {
            metafieldDefinitions(first: 1, namespace: $ns, key: $key, ownerType: $owner) {
              edges {
                node {
                  id name key
                  validations { name value }
                  capabilities {
                    smartCollectionCondition { enabled }
                  }
                }
              }
            }
          }
        """, {"ns": namespace, "key": key, "owner": owner_type})
        edges = data["metafieldDefinitions"]["edges"]
        if not edges:
            self._cache[ck] = None
            return None
        node = edges[0]["node"]
        choices = []
        for v in node.get("validations") or []:
            if (v.get("name") or "").lower() == "choices":
                raw = v.get("value")
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, ValueError):
                    parsed = []
                if isinstance(parsed, list):
                    choices = [str(x) for x in parsed]
        caps = (node.get("capabilities") or {}).get("smartCollectionCondition") or {}
        out = {
            "id": node["id"],
            "choices": choices,
            "smart_collection_condition": bool(caps.get("enabled")),
        }
        self._cache[ck] = out
        return out

    def append_choice(self, namespace, key, value, owner_type="PRODUCT"):
        """
        Append one value to a definition's choices list. Idempotent.

        For custom.subcategory_2: if the Shopify creation placeholder BLANK is
        present, replace it with the new value instead of appending (so the
        placeholder never occupies a real slot or shows in the product UI).

        metafieldDefinitionUpdate: omitted capability fields can default to OFF.
        Always echo capabilities.smartCollectionCondition.enabled from the live
        definition — never force true (subcategory_2 must stay off). Prefer the
        modern `capabilities` input; do not send deprecated useAsCollectionCondition.
        """
        definition = self.metafield_definition(namespace, key, owner_type)
        if definition is None:
            raise ShopifyError(f"no definition {namespace}.{key}")
        existing = list(definition["choices"] or [])
        value = str(value).strip()
        if not value:
            raise ShopifyError("choice value is empty")
        if any(str(c).strip() == value for c in existing):
            return {"added": False, "count": len(existing)}

        replaced_placeholder = False
        if key == "subcategory_2":
            for i, c in enumerate(existing):
                if str(c).strip().upper() == "BLANK":
                    updated = list(existing)
                    updated[i] = value
                    replaced_placeholder = True
                    break
            else:
                updated = existing + [value]
        else:
            updated = existing + [value]

        if not replaced_placeholder and len(existing) >= 128:
            raise ShopifyError(
                f"{namespace}.{key} is full ({len(existing)}/128) - use the overflow field"
            )
        if len(updated) > 128:
            raise ShopifyError(f"{namespace}.{key} would exceed 128 choices")

        # Echo current smart-collection capability (see module note / tests).
        sc_enabled = bool(definition.get("smart_collection_condition"))
        result = self.gql("""
          mutation($def: MetafieldDefinitionUpdateInput!) {
            metafieldDefinitionUpdate(definition: $def) {
              updatedDefinition { id }
              userErrors { field message code }
            }
          }
        """, {"def": {
            "namespace": namespace,
            "key": key,
            "ownerType": owner_type,
            "capabilities": {
                "smartCollectionCondition": {"enabled": sc_enabled},
            },
            "validations": [{"name": "choices", "value": json.dumps(updated)}],
        }})["metafieldDefinitionUpdate"]
        self._check(result, "metafieldDefinitionUpdate")
        self._cache.pop(("mfdef", namespace, key, owner_type), None)
        return {
            "added": True,
            "replaced_placeholder": replaced_placeholder,
            "count": len(updated),
        }

    def set_definition_choices(self, namespace, key, choices, owner_type="PRODUCT"):
        """
        Replace the choices validation list. Echoes smartCollectionCondition.enabled.
        """
        definition = self.metafield_definition(namespace, key, owner_type)
        if definition is None:
            raise ShopifyError(f"no definition {namespace}.{key}")
        sc_enabled = bool(definition.get("smart_collection_condition"))
        result = self.gql(
            """
          mutation($def: MetafieldDefinitionUpdateInput!) {
            metafieldDefinitionUpdate(definition: $def) {
              updatedDefinition { id }
              userErrors { field message code }
            }
          }
        """,
            {
                "def": {
                    "namespace": namespace,
                    "key": key,
                    "ownerType": owner_type,
                    "capabilities": {
                        "smartCollectionCondition": {"enabled": sc_enabled},
                    },
                    "validations": [
                        {"name": "choices", "value": json.dumps(list(choices))}
                    ],
                }
            },
        )["metafieldDefinitionUpdate"]
        self._check(result, "metafieldDefinitionUpdate")
        self._cache.pop(("mfdef", namespace, key, owner_type), None)
        return {"count": len(choices), "smart_collection_condition": sc_enabled}

    def strip_blank_choices(self, namespace, key, owner_type="PRODUCT"):
        """Remove BLANK placeholder entries; echo capability (do not force on)."""
        definition = self.metafield_definition(namespace, key, owner_type)
        if definition is None:
            return {"stripped": False, "reason": "missing"}
        before = list(definition.get("choices") or [])
        after = [c for c in before if str(c).strip().upper() != "BLANK"]
        if after == before:
            return {
                "stripped": False,
                "count": len(after),
                "smart_collection_condition": bool(
                    definition.get("smart_collection_condition")
                ),
            }
        self.set_definition_choices(namespace, key, after, owner_type)
        return {
            "stripped": True,
            "removed": len(before) - len(after),
            "count": len(after),
            "smart_collection_condition": bool(
                definition.get("smart_collection_condition")
            ),
        }

    def ensure_list_choice_definition(
        self,
        namespace,
        key,
        *,
        name: str,
        smart_collection_condition: bool,
        owner_type="PRODUCT",
    ):
        """
        Ensure a list.single_line_text_field definition with choices validation.
        Creates if missing; enables smartCollectionCondition when requested.
        Does not insert BLANK placeholders.
        """
        existing = self.metafield_definition(namespace, key, owner_type)
        if existing is not None:
            if smart_collection_condition and not existing.get(
                "smart_collection_condition"
            ):
                result = self.gql(
                    """
                  mutation($def: MetafieldDefinitionUpdateInput!) {
                    metafieldDefinitionUpdate(definition: $def) {
                      updatedDefinition { id }
                      userErrors { field message code }
                    }
                  }
                """,
                    {
                        "def": {
                            "namespace": namespace,
                            "key": key,
                            "ownerType": owner_type,
                            "capabilities": {
                                "smartCollectionCondition": {"enabled": True},
                            },
                        }
                    },
                )["metafieldDefinitionUpdate"]
                self._check(result, "metafieldDefinitionUpdate")
                self._cache.pop(("mfdef", namespace, key, owner_type), None)
                existing = self.metafield_definition(namespace, key, owner_type)
            return existing

        result = self.gql(
            """
          mutation($def: MetafieldDefinitionInput!) {
            metafieldDefinitionCreate(definition: $def) {
              createdDefinition { id }
              userErrors { field message code }
            }
          }
        """,
            {
                "def": {
                    "name": name,
                    "namespace": namespace,
                    "key": key,
                    "type": "list.single_line_text_field",
                    "ownerType": owner_type,
                    "validations": [{"name": "choices", "value": "[]"}],
                    "capabilities": {
                        "smartCollectionCondition": {
                            "enabled": bool(smart_collection_condition),
                        },
                    },
                }
            },
        )["metafieldDefinitionCreate"]
        self._check(result, "metafieldDefinitionCreate")
        self._cache.pop(("mfdef", namespace, key, owner_type), None)
        created = self.metafield_definition(namespace, key, owner_type)
        if created is None:
            raise ShopifyError(f"failed to create definition {namespace}.{key}")
        return created

    def collection_detail(self, collection_id):
        """Title, SEO, description, ruleSet for metadata panel / rule rewrites."""
        data = self.gql(
            """
          query($id: ID!) {
            collection(id: $id) {
              id handle title descriptionHtml
              seo { title description }
              ruleSet {
                appliedDisjunctively
                rules {
                  column relation condition
                  conditionObject {
                    ... on CollectionRuleMetafieldCondition {
                      metafieldDefinition { id namespace key }
                    }
                  }
                }
              }
            }
          }
        """,
            {"id": collection_id},
        )
        return data.get("collection")

    def set_collection_rules(self, collection_id, *, applied_disjunctive, rules_input):
        result = self.gql(
            """
          mutation($input: CollectionInput!) {
            collectionUpdate(input: $input) {
              collection { id }
              userErrors { field message }
            }
          }
        """,
            {
                "input": {
                    "id": collection_id,
                    "ruleSet": {
                        "appliedDisjunctively": bool(applied_disjunctive),
                        "rules": rules_input,
                    },
                }
            },
        )["collectionUpdate"]
        return self._check(result, "collectionUpdate")

    def products_with_choice_value(self, namespace, key, value, *, limit=500):
        """
        Scan products whose list/single metafield contains `value`.
        Returns list of {id, title, metafield_id, mf_type, all_values}.
        """
        out = []
        cursor = None
        needle = str(value).strip()
        while True:
            data = self.gql(
                """
              query($cursor: String, $ns: String!, $key: String!) {
                products(first: 50, after: $cursor) {
                  pageInfo { hasNextPage endCursor }
                  edges {
                    node {
                      id title
                      metafield(namespace: $ns, key: $key) { id type value }
                    }
                  }
                }
              }
            """,
                {"cursor": cursor, "ns": namespace, "key": key},
            )
            block = data["products"]
            for edge in block["edges"]:
                node = edge["node"]
                mf = node.get("metafield") or {}
                vals = self._parse_mf_list(mf.get("value"), mf.get("type"))
                if needle not in vals:
                    continue
                out.append(
                    {
                        "id": node["id"],
                        "title": node.get("title") or "",
                        "metafield_id": mf.get("id"),
                        "mf_type": mf.get("type") or "",
                        "all_values": vals,
                    }
                )
                if len(out) >= limit:
                    return out
            if not block["pageInfo"]["hasNextPage"]:
                break
            cursor = block["pageInfo"]["endCursor"]
        return out

    @staticmethod
    def _parse_mf_list(raw, mf_type):
        if raw is None or raw == "":
            return []
        if isinstance(raw, list):
            return [str(x) for x in raw]
        s = str(raw)
        if (mf_type or "").startswith("list.") or s.startswith("["):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except (TypeError, ValueError):
                pass
        return [s]

    def set_product_metafield_list(self, owner_id, namespace, key, values, mf_type):
        result = self.gql(
            """
          mutation($mf: [MetafieldsSetInput!]!) {
            metafieldsSet(metafields: $mf) {
              metafields { id }
              userErrors { field message code }
            }
          }
        """,
            {
                "mf": [
                    {
                        "ownerId": owner_id,
                        "namespace": namespace,
                        "key": key,
                        "type": mf_type or "list.single_line_text_field",
                        "value": json.dumps(list(values)),
                    }
                ]
            },
        )["metafieldsSet"]
        return self._check(result, "metafieldsSet")

    # ------------------------------------------------------------- metafields
    def set_shop_metafield(self, namespace, key, value, mf_type="json"):
        result = self.gql("""
          mutation($mf: [MetafieldsSetInput!]!) {
            metafieldsSet(metafields: $mf) {
              metafields { id namespace key type updatedAt }
              userErrors { field message code }
            }
          }
        """, {"mf": [{"ownerId": self.shop_gid(), "namespace": namespace,
                      "key": key, "type": mf_type,
                      "value": value if isinstance(value, str)
                      else json.dumps(value, ensure_ascii=False, separators=(",", ":"))}]})
        return self._check(result["metafieldsSet"], "metafieldsSet")["metafields"][0]

    def get_shop_metafield(self, namespace, key):
        data = self.gql("""
          query($ns: String!, $key: String!) {
            shop { metafield(namespace: $ns, key: $key) { id type value updatedAt } }
          }
        """, {"ns": namespace, "key": key})
        return data["shop"]["metafield"]

    # ------------------------------------------------------------ collections
    def all_collections(self):
        """Every collection, paginated. Returns a list of dicts."""
        out, cursor = [], None
        while True:
            data = self.gql("""
              query($cursor: String) {
                collections(first: 100, after: $cursor) {
                  pageInfo { hasNextPage endCursor }
                  edges { node {
                    id handle title productsCount { count }
                    seo { title description }
                    ruleSet { appliedDisjunctively
                      rules { column relation condition conditionObject {
                        ... on CollectionRuleMetafieldCondition {
                          metafieldDefinition { id namespace key }
                        } } } }
                  } }
                }
              }
            """, {"cursor": cursor})
            block = data["collections"]
            for e in block["edges"]:
                out.append(e["node"])
            if not block["pageInfo"]["hasNextPage"]:
                return out
            cursor = block["pageInfo"]["endCursor"]

    def collection_by_handle(self, handle):
        """
        Load collection by handle, including Online-Store-unpublished ones.

        Uses collections(query: "handle:…") — NOT collectionByHandle, which can
        resolve against the Online Store publication and return null when the
        Online Store channel is off.
        """
        h = (handle or "").strip()
        if not h:
            return None
        data = self.gql(
            """
          query($q: String!) {
            collections(first: 1, query: $q) {
              edges {
                node {
                  id
                  handle
                  title
                  productsCount { count }
                }
              }
            }
          }
        """,
            {"q": f"handle:{h}"},
        )
        edges = ((data.get("collections") or {}).get("edges")) or []
        if not edges:
            return None
        node = edges[0].get("node") or {}
        if (node.get("handle") or "") != h:
            return None
        # Publication flag needed by Phase 7; separate from handle search.
        node["publishedOnPublication"] = self.is_published_online_store(node["id"])
        return node

    def collection_by_id(self, collection_id):
        data = self.gql("""
          query($id: ID!, $pub: ID!) {
            collection(id: $id) {
              id handle title
              productsCount { count }
              publishedOnPublication(publicationId: $pub)
            }
          }
        """, {"id": collection_id, "pub": self.online_store_publication_id()})
        return data["collection"]

    def published_product_count(self, collection_id):
        """
        Count products in the collection that are published to the Online Store.

        Raw Collection.productsCount includes drafts/unpublished products and must
        not drive publish/unpublish decisions (would re-open empty storefront pages).
        """
        numeric = str(collection_id).rsplit("/", 1)[-1]
        data = self.gql(
            """
          query($q: String) {
            productsCount(query: $q) { count }
          }
        """,
            {"q": f"collection_id:{numeric} AND published_status:published"},
        )
        return int(((data.get("productsCount") or {}) or {}).get("count") or 0)

    def is_published_online_store(self, collection_id):
        data = self.gql("""
          query($id: ID!, $pub: ID!) {
            collection(id: $id) {
              publishedOnPublication(publicationId: $pub)
            }
          }
        """, {"id": collection_id, "pub": self.online_store_publication_id()})
        col = data.get("collection") or {}
        return bool(col.get("publishedOnPublication"))

    def handle_available(self, handle):
        return self.collection_by_handle(handle) is None

    def collection_update(self, collection_id, handle=None, title=None,
                          seo_title=None, seo_description=None, description_html=None):
        payload = {"id": collection_id}
        if handle is not None:
            payload["handle"] = handle
        if title is not None:
            payload["title"] = title
        if description_html is not None:
            payload["descriptionHtml"] = description_html
        seo = {}
        if seo_title is not None:
            seo["title"] = seo_title
        if seo_description is not None:
            seo["description"] = seo_description
        if seo:
            payload["seo"] = seo
        result = self.gql("""
          mutation($input: CollectionInput!) {
            collectionUpdate(input: $input) {
              collection { id handle }
              userErrors { field message }
            }
          }
        """, {"input": payload})["collectionUpdate"]
        return self._check(result, "collectionUpdate")["collection"]

    def collection_create(self, title, handle, rules, seo_title=None,
                          seo_description=None, description_html=None, disjunctive=False):
        """rules: list of (definition_gid, value) tuples, ANDed by default."""
        payload = {
            "title": title,
            "handle": handle,
            "ruleSet": {
                "appliedDisjunctively": disjunctive,
                "rules": [{
                    "column": "PRODUCT_METAFIELD_DEFINITION",
                    "relation": "EQUALS",
                    "condition": value,
                    "conditionObjectId": definition_gid,
                } for definition_gid, value in rules],
            },
        }
        if description_html is not None:
            payload["descriptionHtml"] = description_html
        seo = {}
        if seo_title:
            seo["title"] = seo_title
        if seo_description:
            seo["description"] = seo_description
        if seo:
            payload["seo"] = seo
        result = self.gql("""
          mutation($input: CollectionInput!) {
            collectionCreate(input: $input) {
              collection { id handle }
              userErrors { field message }
            }
          }
        """, {"input": payload})["collectionCreate"]
        return self._check(result, "collectionCreate")["collection"]

    # ---------------------------------------------------------- publications
    def set_published(self, collection_id, published):
        pub = self.online_store_publication_id()
        if published:
            result = self.gql("""
              mutation($id: ID!, $input: [PublicationInput!]!) {
                publishablePublish(id: $id, input: $input) {
                  publishable { availablePublicationsCount { count } }
                  userErrors { field message }
                }
              }
            """, {"id": collection_id, "input": [{"publicationId": pub}]})["publishablePublish"]
            return self._check(result, "publishablePublish")
        result = self.gql("""
          mutation($id: ID!, $input: [PublicationInput!]!) {
            publishableUnpublish(id: $id, input: $input) {
              publishable { availablePublicationsCount { count } }
              userErrors { field message }
            }
          }
        """, {"id": collection_id, "input": [{"publicationId": pub}]})["publishableUnpublish"]
        return self._check(result, "publishableUnpublish")

    # -------------------------------------------------------------- redirects
    def create_redirect(self, from_path, to_path):
        """from_path/to_path are site-relative, e.g. /collections/old-handle."""
        result = self.gql("""
          mutation($redirect: UrlRedirectInput!) {
            urlRedirectCreate(urlRedirect: $redirect) {
              urlRedirect { id path target }
              userErrors { field message }
            }
          }
        """, {"redirect": {"path": from_path, "target": to_path}})["urlRedirectCreate"]
        return self._check(result, "urlRedirectCreate")["urlRedirect"]


if __name__ == "__main__":
    import sys
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    print(
        f"[ok] stdio encoding stdout={getattr(sys.stdout, 'encoding', None)!r} "
        f"stderr={getattr(sys.stderr, 'encoding', None)!r}",
        flush=True,
    )
    s = Shopify()
    print("shop:", s.shop_gid())
    print("online store publication:", s.online_store_publication_id())
    for key in ("custom_category", "subcategory", "subcategory_2"):
        try:
            d = s.metafield_definition("custom", key)
        except Exception as exc:
            print(f"[error] custom.{key}: READ_FAILED - {exc}")
            continue
        if d is None:
            print(f"custom.{key}: MISSING")
        else:
            choices = d.get("choices") or []
            real = [c for c in choices if str(c).strip().upper() != "BLANK"]
            n = len(choices)
            if n == 0:
                print(f"custom.{key}: EMPTY (0 choices, definition exists)  {d['id']}")
            elif key == "subcategory_2" and not real and n:
                print(
                    f"custom.{key}: PLACEHOLDER_ONLY (BLANK x{n}, no real choices)  {d['id']}"
                )
            else:
                print(
                    f"custom.{key}: {d['id']}  ({len(real)} real / {n} listed)  "
                    f"smartCollectionCondition={d.get('smart_collection_condition')}"
                )
