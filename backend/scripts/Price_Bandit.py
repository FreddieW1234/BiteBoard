import os
import sys
import time
import json
import requests
from decimal import Decimal, ROUND_HALF_UP

# -*- coding: utf-8 -*-

# Ensure parent directory (backend) is on sys.path so we can import config
PARENT_DIR = os.path.dirname(os.path.dirname(__file__))
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

# Centralized Shopify credentials
from config import STORE_DOMAIN, API_VERSION, ACCESS_TOKEN  # type: ignore

HEADERS = {
    "Content-Type": "application/json",
    "X-Shopify-Access-Token": ACCESS_TOKEN,
}

# Force UTF-8 stdout/stderr to safely print emojis on Windows consoles
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


print("=" * 60 + " \n[X] = Task failed/skipped/error occurred\n[+] = Task completed successfully\n" + "=" * 60, flush=True)


def safe_request(method, url, **kwargs):
    """Wrapper around requests with rate-limit handling (HTTP 429).

    Retries on 429 with a short backoff. Raises for other HTTP errors.
    """
    while True:
        response = requests.request(method, url, **kwargs)
        if response.status_code == 429:
            print("Rate limit exceeded, sleeping for 2 seconds...", flush=True)
            time.sleep(2)
            continue
        response.raise_for_status()
        return response


def _get_paginated(url):
    """Return list of items from a Shopify REST collection endpoint with Link pagination."""
    items = []
    while url:
        resp = safe_request("GET", url, headers=HEADERS)
        data = resp.json()
        # The caller will know top-level key; here we just return the json so they can pick
        items.append(data)
        link_header = resp.headers.get("Link")
        next_url = None
        if link_header:
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    next_url = part[part.find("<") + 1 : part.find(">")]  # noqa: E203
                    break
        url = next_url
    return items


def get_all_products():
    """Return list of products via REST, following Link pagination."""
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products.json?limit=250"
    collected = []
    for page in _get_paginated(url):
        collected.extend(page.get("products", []))
    return collected


def get_all_metafields(product_id):
    """Return list of metafields for a product via REST, following pagination."""
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json?limit=250"
    collected = []
    for page in _get_paginated(url):
        collected.extend(page.get("metafields", []))
    return collected


def get_metafields_by_keys(product_id, keys):
    """Return mapping key -> {id, value} filtered by namespace 'custom' and provided keys."""
    metafields = get_all_metafields(product_id)
    result = {}
    for mf in metafields:
        if mf.get("namespace") == "custom" and mf.get("key") in keys:
            result[mf["key"]] = {"id": mf.get("id"), "value": mf.get("value")}
    return result


def update_product_variants_graphql(product_id, variants, product_name, sku, colours=None):
    """Use GraphQL to update product variants when there are more than 100 variants."""
    graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
    
    try:
        # First, ensure the product has the correct options
        print(f"🔧 Ensuring product has correct options before creating variants...", flush=True)
        
        # Get current product options
        get_product_query = """
        query getProduct($id: ID!) {
            product(id: $id) {
                id
                options {
                    id
                    name
                    values
                }
            }
        }
        """
        
        get_product_variables = {
            "id": f"gid://shopify/Product/{product_id}"
        }
        
        get_product_response = requests.post(graphql_url, json={'query': get_product_query, 'variables': get_product_variables}, headers=HEADERS)
        
        if get_product_response.status_code != 200:
            print(f"❌ Failed to get product options: {get_product_response.status_code}", flush=True)
            return []
        
        product_data = get_product_response.json()
        if 'errors' in product_data:
            print(f"❌ Error getting product: {product_data['errors']}", flush=True)
            return []
        
        current_options = product_data.get('data', {}).get('product', {}).get('options', [])
        print(f"🔍 Current product options: {[opt.get('name') for opt in current_options]}", flush=True)
        
        # Determine required options
        if colours and len(colours) > 0:
            required_options = ["Colour", "Quantity", "Customer Type"]
        else:
            required_options = ["Quantity", "Customer Type"]
        
        # Check if we need to update options
        current_option_names = [opt.get('name') for opt in current_options]
        needs_option_update = set(required_options) != set(current_option_names)
        
        if needs_option_update:
            print(f"🔧 Product options need updating from {current_option_names} to {required_options}", flush=True)
            print(f"ℹ️ Using REST API for variant creation to handle option updates properly", flush=True)
            # Return empty list to force REST API usage
            return []
        
        # Use productVariantsBulkCreate mutation for bulk variant creation
        # Process variants in smaller batches to avoid timeout and rate limits
        batch_size = 25  # Reduced from 50 to handle large quantities better
        all_created_variants = []
        
        for i in range(0, len(variants), batch_size):
            batch_variants = variants[i:i + batch_size]
            print(f"🔄 Creating variants batch {i//batch_size + 1} ({len(batch_variants)} variants)...", flush=True)
            
            # Convert variants to GraphQL format for bulk creation
            variant_inputs = []
            for variant in batch_variants:
                variant_input = {
                    "price": str(variant.get("price"))
                }
                
                # Add option values with correct format: {"optionName": "...", "name": "..."}
                if colours and len(colours) > 0:
                    variant_input["optionValues"] = [
                        {"optionName": "Colour", "name": variant.get("option1", "")},
                        {"optionName": "Quantity", "name": variant.get("option2", "")},
                        {"optionName": "Customer Type", "name": variant.get("option3", "")}
                    ]
                else:
                    variant_input["optionValues"] = [
                        {"optionName": "Quantity", "name": variant.get("option1", "")},
                        {"optionName": "Customer Type", "name": variant.get("option2", "")}
                    ]
                
                variant_inputs.append(variant_input)
            
            # Use productVariantsBulkCreate mutation
            bulk_create_mutation = """
            mutation productVariantsBulkCreate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
                productVariantsBulkCreate(productId: $productId, variants: $variants) {
                    productVariants {
                        id
                        sku
                        price
                        selectedOptions {
                            name
                            value
                        }
                    }
                    userErrors {
                        field
                        message
                    }
                }
            }
            """
            
            bulk_create_variables = {
                "productId": f"gid://shopify/Product/{product_id}",
                "variants": variant_inputs
            }
            
            bulk_create_response = requests.post(graphql_url, json={'query': bulk_create_mutation, 'variables': bulk_create_variables}, headers=HEADERS)
            
            if bulk_create_response.status_code == 200:
                bulk_create_data = bulk_create_response.json()
                if 'errors' in bulk_create_data:
                    print(f"❌ Bulk create GraphQL errors: {bulk_create_data['errors']}", flush=True)
                    continue
                
                bulk_create_result = bulk_create_data.get('data', {}).get('productVariantsBulkCreate', {})
                if bulk_create_result.get('userErrors'):
                    print(f"❌ Bulk create user errors: {bulk_create_result['userErrors']}", flush=True)
                    # Don't continue if there are user errors - they indicate a problem with the data
                    # Instead, try to fix the issue or skip this batch
                    if any('Option does not exist' in str(error) for error in bulk_create_result['userErrors']):
                        print(f"⚠️ Option error detected - this may be due to missing product options", flush=True)
                    continue
                
                created_variants = bulk_create_result.get('productVariants', [])
                for variant in created_variants:
                    all_created_variants.append({
                        'id': variant.get('id', '').split('/')[-1],  # Extract numeric ID
                        'price': variant.get('price', ''),
                        'selectedOptions': variant.get('selectedOptions', [])
                    })
                
                print(f"✔️ Created {len(created_variants)} variants in batch {i//batch_size + 1}", flush=True)
            else:
                print(f"❌ Bulk create request failed: {bulk_create_response.status_code}", flush=True)
                print(f"❌ Response: {bulk_create_response.text}", flush=True)
            
            # Longer delay between batches for large quantities to avoid rate limits
            if i + batch_size < len(variants):
                import time
                # Increase delay for large batches
                delay = 2.0 if len(variants) > 100 else 1.0
                time.sleep(delay)
        
        print(f"✔️ Created {len(all_created_variants)} variants via GraphQL for {product_name} ({sku})", flush=True)
        
        # Now update SKU and other properties using REST API since productVariantsBulkCreate doesn't support them
        if all_created_variants:
            print(f"🔄 Updating variant SKUs and properties via REST API...", flush=True)
            for idx, created_variant in enumerate(all_created_variants):
                if idx >= len(variants):
                    break
                    
                variant_id = created_variant['id']
                original_variant = variants[idx]
                
                update_payload = {
                    "variant": {
                        "id": int(variant_id),
                        "sku": original_variant.get("sku"),
                        "weight": original_variant.get("weight", 0),
                        "weight_unit": original_variant.get("weight_unit", "g"),
                        "taxable": original_variant.get("taxable", True),
                        "inventory_policy": original_variant.get("inventory_policy", "continue"),
                        "requires_shipping": original_variant.get("requires_shipping", True)
                    }
                }
                
                update_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/variants/{variant_id}.json"
                update_response = requests.put(update_url, json=update_payload, headers=HEADERS)
                
                if update_response.status_code != 200:
                    print(f"⚠️ Failed to update variant {variant_id}: {update_response.text}", flush=True)
                
                # Add small delay to avoid rate limiting
                if idx % 10 == 0 and idx > 0:
                    import time
                    time.sleep(0.2)
            
            print(f"✔️ Updated {len(all_created_variants)} variant SKUs and properties", flush=True)
        
        return all_created_variants
        
    except Exception as e:
        print(f"❌ Error updating product variants via GraphQL for {product_name} ({sku}): {str(e)}", flush=True)
        import traceback
        traceback.print_exc()
        return []


def update_product_variants(product_id, variants, product_name, sku, colours=None):
    """PUT full product options + variants array. Returns updated variants list on success."""
    print(f"🔍 update_product_variants called with {len(variants)} variants", flush=True)
    
    # For existing products with option changes, always use REST API for reliability
    # GraphQL has limitations with option updates and variant deletion
    print(f"🔄 Using REST API for {len(variants)} variants (more reliable for option updates)", flush=True)
    
    # Use REST API with batching for large variant counts
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
    
    # Set up options based on whether colours exist
    if colours and len(colours) > 0:
        options = [{"name": "Colour"}, {"name": "Quantity"}, {"name": "Customer Type"}]
    else:
        options = [{"name": "Quantity"}, {"name": "Customer Type"}]
    
    # For REST API, we need to include option values when updating options
    # Get unique option values from variants
    option_values = {"Colour": set(), "Quantity": set(), "Customer Type": set()}
    for variant in variants:
        if variant.get("option1"):
            if colours and len(colours) > 0:
                option_values["Colour"].add(variant.get("option1", ""))
                option_values["Quantity"].add(variant.get("option2", ""))
                option_values["Customer Type"].add(variant.get("option3", ""))
            else:
                option_values["Quantity"].add(variant.get("option1", ""))
                option_values["Customer Type"].add(variant.get("option2", ""))
    
    print(f"🔍 Extracted option values: {dict(option_values)}", flush=True)
    
    # Build options with values
    options_with_values = []
    for option in options:
        option_name = option["name"]
        if option_name in option_values and option_values[option_name]:
            # Sort the values for consistency
            sorted_values = sorted(list(option_values[option_name]))
            options_with_values.append({
                "name": option_name,
                "values": sorted_values
            })
        else:
            options_with_values.append(option)
    
    print(f"🔧 Updating product with {len(options_with_values)} options and {len(variants)} variants", flush=True)
    print(f"🔍 Options: {[opt.get('name') for opt in options_with_values]}", flush=True)
    print(f"🔍 Options with values: {options_with_values}", flush=True)
    print(f"🔍 About to attempt variant creation...", flush=True)
    
    # Simple approach: Update product with ALL variants at once
    print(f"🔄 Updating product with ALL {len(variants)} variants at once", flush=True)
    
    # First, get the current product to preserve required fields like title and existing variants
    existing_variants = []
    try:
        get_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        get_resp = requests.get(get_url, headers=HEADERS, allow_redirects=False)
        
        # Handle redirects for GET request too
        if get_resp.status_code in [301, 302, 303, 307, 308]:
            redirect_url = get_resp.headers.get('Location', get_url)
            if redirect_url.startswith('/'):
                from urllib.parse import urlparse
                parsed = urlparse(get_url)
                redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
            get_resp = requests.get(redirect_url, headers=HEADERS)
        
        if get_resp.status_code == 200:
            current_product = get_resp.json().get("product", {})
            product_title = current_product.get("title", product_name)
            existing_variants = current_product.get("variants", [])
            print(f"🔍 Found {len(existing_variants)} existing variants on product", flush=True)
        else:
            product_title = product_name
    except Exception as e:
        print(f"⚠️ Could not fetch current product: {e}, using provided name", flush=True)
        product_title = product_name
    
    # If we have existing variants and we're trying to add new ones with different options,
    # we need to either update the existing ones or include them in the payload
    # For now, if there's only one existing variant and we're creating multiple new ones,
    # we'll update the first existing variant to match the first new variant, then add the rest
    clean_variants = []
    if len(existing_variants) == 1 and len(variants) > 1:
        # Update the existing variant to match the first new variant
        existing_variant = existing_variants[0]
        first_new_variant = variants[0].copy()
        # Keep the existing variant's ID but update its fields
        updated_variant = {
            "id": existing_variant.get("id"),
            "price": str(first_new_variant.get("price", "0.00")),
            "sku": first_new_variant.get("sku", ""),
            "option1": first_new_variant.get("option1"),
            "option2": first_new_variant.get("option2"),
            "option3": first_new_variant.get("option3"),
            "inventory_policy": first_new_variant.get("inventory_policy", "continue"),
            "requires_shipping": first_new_variant.get("requires_shipping", True),
            "weight": float(first_new_variant.get("weight", 0)),
            "weight_unit": first_new_variant.get("weight_unit", "g"),
            "taxable": first_new_variant.get("taxable", True),
        }
        clean_variants.append(updated_variant)
        # Add the rest as new variants (without IDs)
        for variant in variants[1:]:
            clean_variant = {k: v for k, v in variant.items() if k != 'id'}
            if 'price' in clean_variant:
                clean_variant['price'] = str(clean_variant['price'])
            if 'weight' in clean_variant:
                try:
                    clean_variant['weight'] = float(clean_variant['weight']) if clean_variant['weight'] else 0
                except (ValueError, TypeError):
                    clean_variant['weight'] = 0
            clean_variants.append(clean_variant)
    else:
        # Normal case: all variants are new (or we deleted existing ones)
        for variant in variants:
            clean_variant = {k: v for k, v in variant.items() if k != 'id'}  # Remove any 'id' field
            # Ensure price is a string
            if 'price' in clean_variant:
                clean_variant['price'] = str(clean_variant['price'])
            # Ensure weight is a number, not string
            if 'weight' in clean_variant:
                try:
                    clean_variant['weight'] = float(clean_variant['weight']) if clean_variant['weight'] else 0
                except (ValueError, TypeError):
                    clean_variant['weight'] = 0
            clean_variants.append(clean_variant)
    
    payload = {
        "product": {
            "id": product_id,
            "title": product_title,  # Required field for PUT requests
            "options": options_with_values,
            "variants": clean_variants,
        }
    }
    
    # Log the payload for debugging
    import json
    print(f"🔍 Payload being sent to Shopify: {json.dumps(payload, indent=2)}", flush=True)
    
    try:
        # Handle redirects for PUT requests
        resp = requests.put(url, headers=HEADERS, json=payload, allow_redirects=False)
        
        # If redirected, follow it silently
        if resp.status_code in [301, 302, 303, 307, 308]:
            redirect_url = resp.headers.get('Location', url)
            if redirect_url.startswith('/'):
                from urllib.parse import urlparse
                parsed = urlparse(url)
                redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
            resp = requests.put(redirect_url, headers=HEADERS, json=payload, allow_redirects=True)
        
        if resp.status_code == 200:
            result = resp.json().get("product", {})
            created_variants = result.get("variants", [])
            print(f"✔️ Product variants updated successfully for {product_name} ({sku})", flush=True)
            print(f"✔️ Created {len(created_variants)} variants total", flush=True)
            return created_variants
        elif resp.status_code == 422:
            print(f"❌ Validation error updating product variants for {product_name} ({sku}): {resp.status_code}", flush=True)
            print(f"❌ Response text: {resp.text}", flush=True)
            try:
                error_data = resp.json()
                print(f"❌ Error details: {error_data}", flush=True)
                # Check if it's a variant-related error
                if 'errors' in error_data:
                    errors = error_data['errors']
                    if 'variants' in errors:
                        print(f"⚠️ Variant-specific errors: {errors['variants']}", flush=True)
                    if 'options' in errors:
                        print(f"⚠️ Option-specific errors: {errors['options']}", flush=True)
            except:
                pass
        else:
            print(f"❌ Failed to update product variants for {product_name} ({sku}): {resp.status_code}", flush=True)
            print(f"❌ Response text: {resp.text}", flush=True)
            # Try to parse error details
            try:
                error_data = resp.json()
                if 'errors' in error_data:
                    print(f"❌ Error details: {json.dumps(error_data['errors'], indent=2)}", flush=True)
            except:
                pass
        return []
    except Exception as e:
        print(f"❌ Error updating product variants for {product_name} ({sku}): {str(e)}", flush=True)
        import traceback
        traceback.print_exc()
        return []


def band_label(band):
    return f"{band['min']}-{band['max']}"


def get_unit_weight_grams(metafields):
    unit_weight = metafields.get("unit_weight", {}).get("value")
    if unit_weight is not None:
        try:
            return int(unit_weight)
        except ValueError:
            print("❌ Unit weight metafield value is not a valid integer", flush=True)
    return 0


def get_sku(metafields):
    sku = metafields.get("sku", {}).get("value")
    return sku if sku else ""


def format_price(price):
    """Format price to 2 decimal places as string."""
    try:
        decimal_price = Decimal(str(price))
        formatted = decimal_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return str(formatted)
    except (ValueError, TypeError):
        return str(price)


def validate_band_structure(band):
    return isinstance(band, dict) and "min" in band and "max" in band and "price" in band


def parse_bands(value_str, product_name, field_name):
    try:
        data = json.loads(value_str)
    except Exception as e:
        print(f"❌ Error parsing {field_name} JSON for {product_name}: {e}", flush=True)
        return []
    if not isinstance(data, list):
        print(f"❌ Invalid data for {field_name} in {product_name}. Expected list.", flush=True)
        return []
    if not all(validate_band_structure(b) for b in data):
        print(f"❌ Invalid band structure in {field_name} for {product_name}. Each band must have min, max, price.", flush=True)
        return []
    
    # Convert string prices to floats for processing (so we can do calculations)
    for band in data:
        if "price" in band and isinstance(band["price"], str):
            try:
                band["price"] = float(band["price"])
            except (ValueError, TypeError):
                pass  # Keep original value if conversion fails
    
    return data


def collect_unique_band_labels(trade_bands, endc_bands):
    all_bands = (trade_bands or []) + (endc_bands or [])
    labels = set(band_label(b) for b in all_bands)
    try:
        return sorted(labels, key=lambda x: int(str(x).split("-")[0]))
    except Exception:
        return sorted(labels)


def build_variant_for_band(label, band, customer_type, sku, unit_weight, colour=None):
    variant = {
        "price": format_price(band["price"]),
        "inventory_management": None,
        "inventory_policy": "continue",
        "requires_shipping": True,
        "weight": unit_weight,
        "weight_unit": "g",
        "sku": sku,
        "taxable": True,
    }
    
    if colour:
        # Colour x Quantity x Customer Type structure
        variant["option1"] = colour
        variant["option2"] = label
        variant["option3"] = customer_type
    else:
        # Quantity x Customer Type structure (original)
        variant["option1"] = label
        variant["option2"] = customer_type
    
    return variant


def build_variants(trade_bands, endc_bands, sku, unit_weight, colours=None, colour_codes=None):
    variants = []
    labels = collect_unique_band_labels(trade_bands, endc_bands)
    
    # If colours are provided, create variants for each colour x quantity x customer type
    if colours and len(colours) > 0:
        for colour in colours:
            # Append colour code to SKU if it exists
            colour_code = (colour_codes or {}).get(colour, '')
            variant_sku = sku + ('/' + colour_code) if colour_code else sku
            
            for label in labels:
                t_band = next((b for b in (trade_bands or []) if band_label(b) == label), None)
                e_band = next((b for b in (endc_bands or []) if band_label(b) == label), None)
                if t_band:
                    variants.append(build_variant_for_band(label, t_band, "Trade", variant_sku, unit_weight, colour))
                if e_band:
                    variants.append(build_variant_for_band(label, e_band, "End Customer", variant_sku, unit_weight, colour))
    else:
        # Original behavior - no colours
        for label in labels:
            t_band = next((b for b in (trade_bands or []) if band_label(b) == label), None)
            e_band = next((b for b in (endc_bands or []) if band_label(b) == label), None)
            if t_band:
                variants.append(build_variant_for_band(label, t_band, "Trade", sku, unit_weight))
            if e_band:
                variants.append(build_variant_for_band(label, e_band, "End Customer", sku, unit_weight))
    return variants


def enrich_bands_with_variant_ids(bands, updated_variants, customer_type, colour=None):
    enriched = []
    for band in bands or []:
        label = band_label(band)
        
        # Match variants based on whether colours are present
        if colour:
            # Colour variants: option1=colour, option2=label, option3=customer_type
            match = next(
                (v for v in updated_variants if v.get("option1") == colour and v.get("option2") == label and v.get("option3") == customer_type),
                None,
            )
        else:
            # Try to match non-colour variants first: option1=label, option2=customer_type
            match = next(
                (v for v in updated_variants if v.get("option1") == label and v.get("option2") == customer_type),
                None,
            )
            
            # If no match found, check if variants have colour structure (option2 and option3)
            # If so, match by option2=label and option3=customer_type, picking first match regardless of colour (option1)
            if not match:
                match = next(
                    (v for v in updated_variants if v.get("option2") == label and v.get("option3") == customer_type),
                    None,
                )
                if match:
                    print(f"ℹ️ Matched variant for label '{label}' and customer type '{customer_type}' using first colour variant (colour: {match.get('option1', 'unknown')})", flush=True)
        
        if match and match.get("id"):
            enriched_band = {**band, "id": match["id"]}
            # Format price to string with 2 decimal places for storage in metafields
            if "price" in enriched_band:
                enriched_band["price"] = format_price(enriched_band["price"])
            enriched.append(enriched_band)
    return enriched


def _json_string_for_metafield(value):
    # Use a space after colons for Liquid parsing compatibility
    return json.dumps(value, separators=(",", ": "))


def update_metafield(metafield_id, value, metafield_name, product_name, sku):
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/metafields/{metafield_id}.json"
    payload = {"metafield": {"id": metafield_id, "value": _json_string_for_metafield(value)}}
    resp = safe_request("PUT", url, headers=HEADERS, json=payload)
    if resp.status_code == 200:
        print(
            f"✔️ Updated metafield {metafield_name}, on {product_name} ({sku}), (ID: {metafield_id})",
            flush=True,
        )
        return True
    print(
        f"❌ Failed to update metafield {metafield_name} on {product_name} ({sku}): {resp.status_code} {resp.text}",
        flush=True,
    )
    return False


def create_metafield(product_id, key, value, product_name, sku):
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/metafields.json"
    payload = {
        "metafield": {
            "namespace": "custom",
            "key": key,
            "value": _json_string_for_metafield(value),
            "type": "single_line_text_field",
            "owner_id": product_id,
            "owner_resource": "product",
        }
    }
    resp = safe_request("POST", url, headers=HEADERS, json=payload)
    if resp.status_code == 201:
        metafield = resp.json().get("metafield") or {}
        print(
            f"✔️ Created metafield {key} with ID {metafield.get('id')}, on {product_name} ({sku})",
            flush=True,
        )
        return metafield.get("id")
    print(
        f"❌ Failed to create metafield {key} on {product_name} ({sku}): {resp.status_code} {resp.text}",
        flush=True,
    )
    return None


def set_or_update_metafield(metafields, product_id, key, value, product_name, sku):
    if key in metafields and metafields[key].get("id"):
        update_metafield(metafields[key]["id"], value, key, product_name, sku)
    else:
        create_metafield(product_id, key, value, product_name, sku)


def attach_main_image_to_variants(product_id, product_name, colours=None, colour_images=None):
    try:
        # Handle colour_images if it's a string (converted from JSON)
        if isinstance(colour_images, str):
            import json
            try:
                colour_images = json.loads(colour_images)
                print(f"🔧 Converted colour_images from string to dict", flush=True)
            except Exception as e:
                print(f"⚠️ Failed to parse colour_images: {e}", flush=True)
                colour_images = None
        
        product_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        response = safe_request("GET", product_url, headers=HEADERS)
        product_data = (response.json() or {}).get("product") or {}

        if not product_data.get("image"):
            print(
                f"❌ No main image found for product {product_name} (ID: {product_id}). Skipping image sync.",
                flush=True,
            )
            return False

        # Wait a moment for all variants to be fully available in the API
        print(f"⏳ Waiting for all variants to be available...", flush=True)
        import time
        time.sleep(2.0)
        
        # Fetch fresh product data with pagination to get ALL variants
        print(f"🔄 Fetching fresh product data for image assignment...", flush=True)
        fresh_product_data = product_data  # fallback to original data
        
        # Try up to 3 times to get all variants
        for attempt in range(1, 4):
            try:
                # First get the product basic info
                fresh_product_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
                fresh_resp = requests.get(fresh_product_url, headers=HEADERS)
                
                if fresh_resp.status_code == 200:
                    fresh_product_data = fresh_resp.json().get("product", {})
                    
                    # Now fetch ALL variants using pagination
                    all_variants = []
                    page_info = None
                    page_num = 1
                    
                    while True:
                        if page_info:
                            variants_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/variants.json?limit=250&page_info={page_info}"
                        else:
                            variants_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/variants.json?limit=250"
                        
                        print(f"🔄 Fetching variants page {page_num}...", flush=True)
                        variants_resp = requests.get(variants_url, headers=HEADERS)
                        
                        if variants_resp.status_code == 200:
                            variants_data = variants_resp.json()
                            page_variants = variants_data.get("variants", [])
                            all_variants.extend(page_variants)
                            
                            print(f"✅ Page {page_num}: {len(page_variants)} variants fetched", flush=True)
                            
                            # Check for next page
                            link_header = variants_resp.headers.get('Link', '')
                            if 'rel="next"' in link_header:
                                # Extract page_info from Link header
                                import re
                                next_match = re.search(r'page_info=([^&>]+)', link_header)
                                if next_match:
                                    page_info = next_match.group(1)
                                    page_num += 1
                                    continue
                            
                            break  # No more pages
                        else:
                            print(f"⚠️ Failed to fetch variants page {page_num}: {variants_resp.status_code}", flush=True)
                            break
                    
                    # Update the product data with all variants
                    fresh_product_data["variants"] = all_variants
                    variant_count = len(all_variants)
                    print(f"✅ Fresh product data fetched (attempt {attempt}): {variant_count} variants found total", flush=True)
                    
                    # If we have variants, we're good (no need to check exact count)
                    if variant_count > 0:
                        print(f"✅ Found {variant_count} variants, proceeding with image assignment", flush=True)
                        break
                    else:
                        print(f"⚠️ No variants found, retrying...", flush=True)
                        if attempt < 3:
                            time.sleep(2.0)  # Wait longer before retry
                else:
                    print(f"⚠️ Failed to fetch fresh product data (attempt {attempt}): {fresh_resp.status_code}", flush=True)
                    if attempt < 3:
                        time.sleep(2.0)
            except Exception as e:
                print(f"⚠️ Error fetching fresh product data (attempt {attempt}): {str(e)}", flush=True)
                if attempt < 3:
                    time.sleep(2.0)
        
        # Now extract main image and variant IDs from the fresh data
        # The main image should be the first image (position 1) after sorting
        images = fresh_product_data.get("images", [])
        if images:
            # Sort by position to ensure correct order
            images.sort(key=lambda x: x.get('position', 999))
            # The first image (position 1) should be the main image
            main_image_id = images[0].get("id")
            print(f"🔍 Main image determined: ID {main_image_id} at position {images[0].get('position', '?')}", flush=True)
        else:
            # Fallback to product.image if images array is empty
            main_image_id = (fresh_product_data.get("image") or {}).get("id")
            print(f"🔍 Main image from product.image: ID {main_image_id}", flush=True)
        
        all_variant_ids = [v.get("id") for v in fresh_product_data.get("variants", []) if v.get("id")]
        
        if not main_image_id or not all_variant_ids:
            print(
                f"❌ Missing main image or variants for product {product_name} (ID: {product_id}).",
                flush=True,
            )
            return False
        
        # If colours exist, try to map images to colours
        if colours and len(colours) > 0:
            print(f"🎨 Checking for colour-specific images for {len(colours)} colours...", flush=True)
            print(f"🔍 Main image (position 1) ID: {main_image_id}", flush=True)
            
            # If no images found, wait and retry once (for new products where images might not be indexed yet)
            if not images and colour_images:
                print(f"⚠️ No images found in product data, waiting 2 seconds and retrying...", flush=True)
                time.sleep(2.0)
                # Fetch product data again
                retry_resp = requests.get(fresh_product_url, headers=HEADERS)
                if retry_resp.status_code == 200:
                    retry_data = retry_resp.json().get("product", {})
                    images = retry_data.get("images", [])
                    if images:
                        images.sort(key=lambda x: x.get('position', 999))
                    print(f"🔍 Retry: Found {len(images)} images", flush=True)
            
            # Create a map of colour to variant IDs
            colour_to_variants = {}
            variants_found = fresh_product_data.get("variants", [])
            print(f"🔍 Found {len(variants_found)} variants for image assignment", flush=True)
            if variants_found:
                print(f"🔍 First variant for image assignment: {variants_found[0]}", flush=True)
            
            for variant in variants_found:
                option1 = variant.get("option1", "")
                if option1 in colours:
                    if option1 not in colour_to_variants:
                        colour_to_variants[option1] = []
                    colour_to_variants[option1].append(variant.get("id"))
            
            print(f"🔍 Colour to variants mapping: {colour_to_variants}", flush=True)
            print(f"🔍 Total variants found for image assignment: {len(variants_found)}", flush=True)
            print(f"🔍 Variants per colour: {len(variants_found) // len(colours) if colours else 'N/A'}", flush=True)
            
            # Try to find images for each colour
            assigned_variants = set()
            print(f"🔍 Available images: {len(images)}", flush=True)
            if images:
                print(f"🔍 Image positions: {[(i, img.get('position', '?'), img.get('id')) for i, img in enumerate(images)]}", flush=True)
                print(f"🔍 Sample image structure: id={images[0].get('id')}, position={images[0].get('position')}", flush=True)
            if colour_images:
                print(f"🔍 colour_images mapping: {colour_images}", flush=True)
                print(f"🔍 Expected image order based on media_order should match these indices", flush=True)
            for colour in colours:
                print(f"🔍 Processing colour: {colour}", flush=True)
                if colour not in colour_to_variants:
                    print(f"⚠️ No variants found for colour: {colour}", flush=True)
                    continue
                else:
                    print(f"✅ Found {len(colour_to_variants[colour])} variants for colour: {colour}", flush=True)
                
                # Extract colour name (before colon if present) for matching with colour_images
                # Colours can be "Colour:Code" format, but colour_images uses just "Colour"
                colour_name = colour.split(':')[0] if ':' in colour else colour
                print(f"🔍 Using colour name '{colour_name}' for image mapping (from '{colour}')", flush=True)
                
                # First check if there's a specific image mapping from frontend
                colour_image = None
                if colour_images and colour_name in colour_images:
                    # The mapping contains the image index (order in which images were attached)
                    image_index = colour_images[colour_name]
                    print(f"🔍 Looking for image at index: {image_index} (out of {len(images)} images) for colour '{colour_name}'", flush=True)
                    # Get image by index if it exists
                    if isinstance(image_index, int) and 0 <= image_index < len(images):
                        colour_image = images[image_index]
                        print(f"✔️ Found image at index {image_index} for colour {colour}", flush=True)
                    elif isinstance(image_index, str) and image_index.isdigit():
                        # Fallback: try as integer index
                        idx = int(image_index)
                        if 0 <= idx < len(images):
                            colour_image = images[idx]
                            print(f"✔️ Found image at index {idx} for colour {colour} (converted from string)", flush=True)
                        else:
                            print(f"⚠️ Invalid image index {image_index}", flush=True)
                    else:
                        print(f"⚠️ Invalid image index format: {image_index}", flush=True)
                
                # Fallback: Look for an image with the colour in its filename/alt text
                if not colour_image:
                    colour_lower = colour.lower()
                    for img in images:
                        filename = (img.get("filename") or "").lower()
                        alt_text = (img.get("alt") or "").lower()
                        if colour_lower in filename or colour_lower in alt_text:
                            colour_image = img
                            break
                
                if colour_image:
                    # Assign this image to this colour's variants
                    img_id = colour_image.get("id")
                    variant_ids = colour_to_variants[colour]
                    update_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/images/{img_id}.json"
                    update_data = {"image": {"id": img_id, "variant_ids": variant_ids}}
                    # Handle redirects for PUT requests
                    update_response = requests.put(update_url, headers=HEADERS, json=update_data, allow_redirects=False)
                    
                    # If redirected, follow it silently
                    if update_response.status_code in [301, 302, 303, 307, 308]:
                        redirect_url = update_response.headers.get('Location', update_url)
                        if redirect_url.startswith('/'):
                            from urllib.parse import urlparse
                            parsed = urlparse(update_url)
                            redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                        update_response = requests.put(redirect_url, headers=HEADERS, json=update_data, allow_redirects=True)
                    
                    if update_response.status_code == 200:
                        print(f"✔️ Assigned image {img_id} to {colour} variants", flush=True)
                        for v_id in variant_ids:
                            assigned_variants.add(v_id)
            
            # First, assign main image to ALL variants (this ensures all variants have the main image by default)
            print(f"🔍 Assigning main image to ALL {len(all_variant_ids)} variants first...", flush=True)
            update_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/images/{main_image_id}.json"
            update_data = {"image": {"id": main_image_id, "variant_ids": all_variant_ids}}
            # Handle redirects for PUT requests
            update_response = requests.put(update_url, headers=HEADERS, json=update_data, allow_redirects=False)
            
            # If redirected, follow it silently
            if update_response.status_code in [301, 302, 303, 307, 308]:
                redirect_url = update_response.headers.get('Location', update_url)
                if redirect_url.startswith('/'):
                    from urllib.parse import urlparse
                    parsed = urlparse(update_url)
                    redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                update_response = requests.put(redirect_url, headers=HEADERS, json=update_data, allow_redirects=True)
            
            if update_response.status_code == 200:
                print(f"✔️ Main image assigned to all variants", flush=True)
            else:
                print(f"⚠️ Failed to assign main image to all variants: {update_response.status_code}", flush=True)
            
            # Now assign specific colour images (these will override the main image for those variants)
            # The colour-specific images are already assigned above, so we're done
            print(f"🔍 Total variant IDs: {len(all_variant_ids)}", flush=True)
            print(f"🔍 Assigned variants (with specific images): {len(assigned_variants)}", flush=True)
            print(f"🔍 Remaining variants (keeping main image): {len(all_variant_ids) - len(assigned_variants)}", flush=True)
        else:
            # No colours - assign main image to all variants
            update_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/images/{main_image_id}.json"
            update_data = {"image": {"id": main_image_id, "variant_ids": all_variant_ids}}
            # Handle redirects for PUT requests
            update_response = requests.put(update_url, headers=HEADERS, json=update_data, allow_redirects=False)
            
            # If redirected, follow it silently
            if update_response.status_code in [301, 302, 303, 307, 308]:
                redirect_url = update_response.headers.get('Location', update_url)
                if redirect_url.startswith('/'):
                    from urllib.parse import urlparse
                    parsed = urlparse(update_url)
                    redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                update_response = requests.put(redirect_url, headers=HEADERS, json=update_data, allow_redirects=True)
            
            if update_response.status_code == 200:
                print(f"✔️ All variants of product '{product_name}' have matching image.", flush=True)
                return True
        
        print(f"✔️ Image assignment complete for product '{product_name}'", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ Exception during main image variant update: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False


def process_product(product):
    try:
        product_id = product.get("id")
        product_name = product.get("title", "Unknown Product")
        if not product_id:
            print("❌ Invalid product structure - missing ID", flush=True)
            return

        if "origination" in (product_name or "").lower():
            print(f"{'='*60}\n Skipping product with 'origination' in name: {product_name} (ID: {product_id})...", flush=True)
            return

        print(f"{'='*60}\n Analysing product: {product_name} (ID: {product_id})...", flush=True)

        keys_to_fetch = [
            "pricejsontr",
            "pricejsoner",
            "pricejsontid",
            "pricejsoneid",
            "unit_weight",
            "sku",
            "product_colours",
        ]
        print(f"🔍 Fetching metafields for product {product_name} (ID: {product_id})", flush=True)
        metafields = get_metafields_by_keys(product_id, keys_to_fetch)
        print(f"🔍 Fetched metafields: {list(metafields.keys())}", flush=True)
        
        # Debug: Check if product_colours is in the fetched metafields
        if "product_colours" in metafields:
            print(f"🔍 product_colours metafield found in fetched metafields", flush=True)
            print(f"🔍 product_colours value: '{metafields['product_colours'].get('value', '')}'", flush=True)
        else:
            print(f"⚠️ product_colours metafield NOT found in fetched metafields", flush=True)
            print(f"🔍 Trying to fetch all metafields manually...", flush=True)
            # Try to fetch the metafield directly
            try:
                import requests
                from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION
                headers = {"X-Shopify-Access-Token": ACCESS_TOKEN}
                url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
                resp = requests.get(url, headers=headers)
                if resp.status_code == 200:
                    all_mfs = resp.json().get("metafields", [])
                    print(f"🔍 Total metafields on product: {len(all_mfs)}", flush=True)
                    colours_mf = [m for m in all_mfs if m.get("key") == "product_colours" and m.get("namespace") == "custom"]
                    if colours_mf:
                        print(f"🔍 Found product_colours metafield directly: '{colours_mf[0].get('value', '')}'", flush=True)
                    else:
                        print(f"⚠️ product_colours metafield not found on product", flush=True)
            except Exception as e:
                print(f"❌ Error fetching metafields directly: {e}", flush=True)

        sku = get_sku(metafields)
        unit_weight = get_unit_weight_grams(metafields)
        
        # Parse colour options - can be in format "Colour:Code" or just "Colour"
        colours = []
        colour_codes = {}
        if "product_colours" in metafields:
            colours_str = metafields["product_colours"].get("value", "").strip()
            print(f"🔍 Raw product_colours value: '{colours_str}'", flush=True)
            if colours_str:
                for colour_entry in colours_str.split(","):
                    colour_entry = colour_entry.strip()
                    if ':' in colour_entry:
                        # Format: "Colour:Code" (e.g., "Red:r")
                        colour_parts = colour_entry.split(':', 1)
                        colour = colour_parts[0].strip()
                        code = colour_parts[1].strip() if len(colour_parts) > 1 else ''
                        colours.append(colour)
                        colour_codes[colour] = code
                    else:
                        # Format: just "Colour" (no code)
                        colours.append(colour_entry)
                        colour_codes[colour_entry] = ''
                print(f"🔍 Parsed colours: {colours}", flush=True)
                if colour_codes:
                    print(f"🔍 Colour codes: {colour_codes}", flush=True)
        else:
            print(f"⚠️ product_colours metafield not found in fetched metafields", flush=True)
            print(f"🔍 Available metafields: {list(metafields.keys())}", flush=True)
        
        print(f" Using Unit weight: {unit_weight}g and SKU: '{sku}'", flush=True)
        if colours:
            print(f" Colours found: {', '.join(colours)}", flush=True)
        else:
            print(f" No colours specified - using standard variants", flush=True)

        # Required pricing metafields
        if "pricejsontr" not in metafields or "pricejsoner" not in metafields:
            print(f"❌ Missing required raw JSON metafields for {product_name}. Skipping.", flush=True)
            return

        trade_raw = parse_bands(metafields["pricejsontr"].get("value", "[]"), product_name, "pricejsontr")
        endc_raw = parse_bands(metafields["pricejsoner"].get("value", "[]"), product_name, "pricejsoner")
        if not trade_raw and not endc_raw:
            print(f"❌ No valid pricing bands found for {product_name}. Skipping.", flush=True)
            return

        variants = build_variants(trade_raw, endc_raw, sku, unit_weight, colours, colour_codes)
        print(f"Creating/updating {len(variants)} variants...", flush=True)
        
        # Debug: Show first variant structure
        if variants:
            print(f"🔍 First variant structure: {variants[0]}", flush=True)
        
        # Use GraphQL to delete all variants at once (much more efficient)
        print(f"🗑️ Deleting existing variants using GraphQL...", flush=True)
        variants_deleted = False
        try:
            # Import here to avoid issues with variable scoping
            import requests
            from config import STORE_DOMAIN, API_VERSION, ACCESS_TOKEN
            import time
            
            # First, get all variant IDs using GraphQL
            get_variants_query = """
            query getProductVariants($id: ID!) {
                product(id: $id) {
                    variants(first: 250) {
                        edges {
                            node {
                                id
                            }
                        }
                    }
                }
            }
            """
            
            get_variants_variables = {
                "id": f"gid://shopify/Product/{product_id}"
            }
            
            graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
            get_response = requests.post(graphql_url, json={'query': get_variants_query, 'variables': get_variants_variables}, headers=HEADERS)
            
            if get_response.status_code == 200:
                get_data = get_response.json()
                if 'errors' in get_data:
                    print(f"❌ Error fetching variants: {get_data['errors']}", flush=True)
                else:
                    variants_data = get_data.get('data', {}).get('product', {}).get('variants', {}).get('edges', [])
                    variant_ids = [edge['node']['id'] for edge in variants_data]
                    
                    if variant_ids:
                        print(f"🔍 Found {len(variant_ids)} existing variants to delete", flush=True)
                        
                        # Delete all variants using GraphQL bulk operation
                        delete_variants_query = """
                        mutation productVariantsBulkDelete($productId: ID!, $variantsIds: [ID!]!) {
                            productVariantsBulkDelete(productId: $productId, variantsIds: $variantsIds) {
                                product {
                                    id
                                }
                                userErrors {
                                    field
                                    message
                                }
                            }
                        }
                        """
                        
                        delete_variants_variables = {
                            "productId": f"gid://shopify/Product/{product_id}",
                            "variantsIds": variant_ids
                        }
                        
                        delete_response = requests.post(graphql_url, json={'query': delete_variants_query, 'variables': delete_variants_variables}, headers=HEADERS)
                        
                        if delete_response.status_code == 200:
                            delete_data = delete_response.json()
                            if 'errors' in delete_data:
                                print(f"❌ GraphQL delete errors: {delete_data['errors']}", flush=True)
                            else:
                                delete_result = delete_data.get('data', {}).get('productVariantsBulkDelete', {})
                                if delete_result.get('userErrors'):
                                    print(f"❌ Delete user errors: {delete_result['userErrors']}", flush=True)
                                    # Check if it's the "last variant" error
                                    if any('last variant' in str(error).lower() for error in delete_result['userErrors']):
                                        print(f"ℹ️ Cannot delete last variant - will update it instead", flush=True)
                                        variants_deleted = False  # Mark that we couldn't delete
                                        # Don't abort, continue with variant creation
                                    else:
                                        print(f"⚠️ Other deletion errors - continuing anyway", flush=True)
                                        variants_deleted = False
                                else:
                                    # GraphQL deletion doesn't return deleted IDs, just check for success
                                    print(f"✅ Successfully deleted {len(variant_ids)} variants via GraphQL", flush=True)
                                    variants_deleted = True
                                    
                                    # Short wait for eventual consistency
                                    time.sleep(1.0)
                    else:
                        print(f"✅ No existing variants found", flush=True)
            else:
                print(f"❌ Failed to fetch variants: {get_response.status_code}", flush=True)
                
        except Exception as e:
            print(f"⚠️ Could not delete existing variants: {e}", flush=True)
            print(f"⚠️ Continuing anyway...", flush=True)
            variants_deleted = False
        
        # If we couldn't delete variants (e.g., last variant error), we need to handle this differently
        if not variants_deleted and len(variants) > 1:
            print(f"ℹ️ Could not delete existing variants - this is expected for products with only one variant", flush=True)
            print(f"ℹ️ Will update the product with new options and variants", flush=True)
        
        updated_variants = update_product_variants(product_id, variants, product_name, sku, colours)
        print(f"🔍 update_product_variants returned: {len(updated_variants) if updated_variants else 0} variants", flush=True)
        if not updated_variants:
            print(f"❌ Aborting due to variant update failure for {product_name}.", flush=True)
            return False

        # Enrich bands with Shopify variant IDs and persist
        enriched_trade = enrich_bands_with_variant_ids(trade_raw, updated_variants, "Trade", None)
        enriched_endc = enrich_bands_with_variant_ids(endc_raw, updated_variants, "End Customer", None)
        set_or_update_metafield(metafields, product_id, "pricejsontid", enriched_trade, product_name, sku)
        set_or_update_metafield(metafields, product_id, "pricejsoneid", enriched_endc, product_name, sku)

        # Wait a moment for variants to be fully saved before attaching images
        print(f"⏳ Waiting 2 seconds for variants to be fully saved...", flush=True)
        time.sleep(2.0)

        # Sync main image across variants
        colour_images = product.get("_colour_images")  # Passed from Product_Creator
        print(f"🔍 Received colour_images from Product_Creator: {colour_images}", flush=True)
        attach_main_image_to_variants(product_id, product_name, colours, colour_images)

        print(f"✅ Successfully processed product: {product_name}", flush=True)
        return True
    except Exception as e:
        print(f"❌ Error processing product {product.get('title', 'Unknown')}: {str(e)}", flush=True)
        return False


def _filter_products(products, product_ids=None, product_filter=None):
    if product_ids:
        wanted = set(str(pid).strip() for pid in product_ids)
        out = []
        for p in products:
            if isinstance(p, dict) and str(p.get("id")) in wanted:
                out.append(p)
        return out

    if product_filter:
        flt = product_filter.lower().strip()
        out = []
        for p in products:
            if not isinstance(p, dict) or "id" not in p:
                continue
            pid = str(p.get("id"))
            name = (p.get("title") or "").lower()
            sku = ""
            try:
                if p.get("variants"):
                    v0 = p["variants"][0]
                    if isinstance(v0, dict):
                        sku = (v0.get("sku") or "").lower()
            except Exception:
                sku = ""

            if (
                flt == pid.lower()
                or flt == name.lower()
                or flt == sku.lower()
                or flt in name
                or flt in sku
            ):
                out.append(p)
        return out

    return products


def main():
    try:
        product_filter = None
        product_ids = None

        if len(sys.argv) > 1:
            if sys.argv[1] == "--products" and len(sys.argv) > 2:
                product_ids = sys.argv[2].strip().split(",")
                print(f"🔍 Processing specific products by IDs: {product_ids}", flush=True)
            else:
                product_filter = sys.argv[1].strip()
                print(f"🔍 Filtering for product: {product_filter}", flush=True)

        products = get_all_products()
        if not products:
            print("❌ No products fetched from Shopify API", flush=True)
            return 1

        print(f"📦 Total products fetched: {len(products)}", flush=True)
        products = _filter_products(products, product_ids=product_ids, product_filter=product_filter)
        if not products:
            if product_ids:
                print(f"❌ No products found with the specified IDs: {product_ids}", flush=True)
            elif product_filter:
                print(f"❌ No products found matching: '{product_filter}'", flush=True)
                print("💡 Try searching by: product name, product ID, or SKU", flush=True)
            else:
                print("❌ No products to process", flush=True)
            return 1

        print(f"🚀 Starting to process {len(products)} products...", flush=True)

        successful = 0
        failed = 0
        for i, product in enumerate(products, 1):
            try:
                print(f"📝 Processing product {i}/{len(products)}: {product.get('title', 'Unknown')}", flush=True)
                process_product(product)
                successful += 1
            except Exception as e:
                print(f"❌ Failed to process product {product.get('title', 'Unknown')}: {str(e)}", flush=True)
                failed += 1
                continue
            if i < len(products):
                time.sleep(0.7)

        print("=" * 60, flush=True)
        print(f"🎉 Completed processing {len(products)} products!", flush=True)
        print(f"✅ Successful: {successful}, ❌ Failed: {failed}", flush=True)
        return 0
    except Exception as e:
        print(f"❌ Fatal error in main function: {str(e)}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
