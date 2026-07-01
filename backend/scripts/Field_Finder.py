import requests
import json
import sys

# UTF-8 encoding handled at subprocess level in backend

try:
    from config import STORE_DOMAIN, API_VERSION, ACCESS_TOKEN  # type: ignore
except ImportError:
    raise RuntimeError("Missing config module; ensure backend/config.py is available.")

HEADERS = {
    "Content-Type": "application/json",
    "X-Shopify-Access-Token": ACCESS_TOKEN,
}

def get_product_by_id(product_id):
    """Get a single product by ID"""
    try:
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        
        product_data = response.json()
        return product_data.get("product")
        
    except Exception as e:
        print(f"Error fetching product {product_id}: {str(e)}")
        return None

def get_all_products():
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products.json?limit=250"
    products = []
    while url:
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            break
        data = response.json()
        products.extend(data.get("products", []))
        
        link_header = response.headers.get("Link")
        next_url = None
        if link_header:
            parts = link_header.split(",")
            for part in parts:
                if 'rel="next"' in part:
                    next_url = part[part.find("<")+1 : part.find(">")]
                    break
        url = next_url
    return products

def fetch_all_metafields(product_id):
    metafields = []
    # Remove limit to get ALL metafields, including blank ones
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
    
    print(f"🔍 Fetching metafields for product {product_id}", flush=True)
    page_count = 0
    
    while url:
        page_count += 1
        print(f"📄 Fetching page {page_count}: {url}", flush=True)
        
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            print(f"❌ Failed to fetch page {page_count}: {response.status_code}", flush=True)
            return []
        
        data = response.json()
        current_metafields = data.get("metafields", [])
        print(f"📥 Page {page_count}: Got {len(current_metafields)} metafields", flush=True)
        
        # Debug: Show what we got on this page
        for i, m in enumerate(current_metafields):
            print(f"     {i+1}. {m.get('namespace')}:{m.get('key')} ({m.get('type')})", flush=True)
        
        metafields.extend(current_metafields)
        
        # Check for next page
        link_header = response.headers.get("Link")
        url = None
        if link_header:
            print(f"🔗 Link header: {link_header}", flush=True)
            parts = link_header.split(',')
            for part in parts:
                if 'rel="next"' in part:
                    url = part[part.find("<")+1:part.find(">")]
                    print(f"🔄 Next page found: {url}", flush=True)
                    break
        else:
            print(f"🔗 No Link header found", flush=True)
        
        if not url:
            print(f"✅ No more pages, total metafields: {len(metafields)}", flush=True)
    
    print(f"📊 Total metafields collected: {len(metafields)}", flush=True)
    
    # Debug: Show ALL metafields to see what we're working with
    print("🔍 DEBUG: ALL metafields collected:", flush=True)
    for i, m in enumerate(metafields):
        print(f"   {i+1}. Namespace: '{m.get('namespace')}', Key: '{m.get('key')}', Type: '{m.get('type')}'", flush=True)
    
    # Debug: Show breakdown by namespace
    namespace_breakdown = {}
    for m in metafields:
        namespace = m.get('namespace', 'unknown')
        if namespace not in namespace_breakdown:
            namespace_breakdown[namespace] = []
        namespace_breakdown[namespace].append(m.get('key'))
    
    print("📊 Metafields by namespace:", flush=True)
    for namespace, keys in namespace_breakdown.items():
        print(f"   {namespace}: {len(keys)} metafields - {keys}", flush=True)
        
    # Check specifically for packaging fields
    packaging_fields = [m for m in metafields if 'packaging' in m.get('key', '').lower()]
    if packaging_fields:
        print("🎯 Found packaging-related fields:", flush=True)
        for m in packaging_fields:
            print(f"   - {m.get('namespace')}:{m.get('key')} = {m.get('value', '')[:100]}...", flush=True)
    else:
        print("⚠️ No packaging-related fields found in raw metafields", flush=True)
        
    # Check for any fields with dots in the key
    dot_fields = [m for m in metafields if '.' in m.get('key', '')]
    if dot_fields:
        print("🔍 Found fields with dots in key:", flush=True)
        for m in dot_fields:
            print(f"   - {m.get('namespace')}:{m.get('key')} ({m.get('type')})", flush=True)
    else:
        print("ℹ️ No fields with dots in key found", flush=True)
    
    # Count by namespace
    namespace_counts = {}
    for m in metafields:
        namespace = m.get('namespace', 'unknown')
        namespace_counts[namespace] = namespace_counts.get(namespace, 0) + 1
    
    print("📊 Metafields by namespace:", flush=True)
    for namespace, count in sorted(namespace_counts.items()):
        print(f"   {namespace}: {count} metafields", flush=True)
    
    # Fetch metafield definitions to get available options for list types
    print("🔍 Fetching metafield definitions for list options...", flush=True)
    
    # Try to get all metafields from store to see what custom fields exist...
    try:
        # Look specifically for the 'Product for field finder' product
        products_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products.json?limit=250"
        products_response = requests.get(products_url, headers=HEADERS)
        
        if products_response.status_code == 200:
            products_data = products_response.json()
            products = products_data.get("products", [])
            
            # Find the specific template product
            template_product = None
            for product in products:
                if 'product for field finder' in product.get('title', '').lower():
                    template_product = product
                    break
            
            if template_product:
                # Get all metafields from the template product
                template_mf_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{template_product.get('id')}/metafields.json"
                template_response = requests.get(template_mf_url, headers=HEADERS)
                if template_response.status_code == 200:
                    template_data = template_response.json()
                    template_metafields = template_data.get("metafields", [])
                    
                    # Find all custom namespace metafields from template
                    custom_metafields = [mf for mf in template_metafields if mf.get('namespace') == 'custom']
                    
                    if custom_metafields:
                        # Add any custom metafields that don't exist on current product
                        current_custom_keys = {m.get('key') for m in metafields if m.get('namespace') == 'custom'}
                        custom_keys = {mf.get('key') for mf in custom_metafields}
                        missing_custom_keys = custom_keys - current_custom_keys
                        
                        if missing_custom_keys:
                            for key in sorted(missing_custom_keys):
                                # Find the metafield definition from template
                                template_mf = next((mf for mf in custom_metafields if mf.get('key') == key), None)
                                if template_mf:
                                    blank_metafield = {
                                        'namespace': 'custom',
                                        'key': key,
                                        'type': template_mf.get('type', 'single_line_text_field'),
                                        'value': '',
                                        'id': None,
                                        '_is_from_template': True
                                    }
                                    metafields.append(blank_metafield)
    except Exception as e:
        pass  # Silently handle errors for template product lookup
    
    # Try different API endpoints for metafield definitions
    definitions_urls = [
        f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/metafield_definitions.json?metafield[owner_resource]=product",
        f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/metafield_definitions.json",
        f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/metafields.json?metafield[owner_resource]=product&limit=250"
    ]
    
    metafield_definitions = []
    successful_url = None
    
    for i, url in enumerate(definitions_urls):
        try:
            definitions_response = requests.get(url, headers=HEADERS)
            
            if definitions_response.status_code == 200:
                successful_url = url
                definitions_data = definitions_response.json()
                
                # Handle different response formats
                if "metafield_definitions" in definitions_data:
                    metafield_definitions = definitions_data.get("metafield_definitions", [])
                elif "metafields" in definitions_data:
                    # Alternative format - extract definitions from metafields
                    metafields_data = definitions_data.get("metafields", [])
                    
                    # Extract unique metafield definitions
                    seen_definitions = set()
                    for metafield in metafields_data:
                        definition_key = (metafield.get('namespace'), metafield.get('key'), metafield.get('type'))
                        if definition_key not in seen_definitions:
                            seen_definitions.add(definition_key)
                            metafield_definitions.append({
                                'namespace': metafield.get('namespace'),
                                'key': metafield.get('key'),
                                'type': metafield.get('type'),
                                'options': metafield.get('options', [])
                            })
                
                break  # Success, exit the loop
        except Exception as e:
            if i == len(definitions_urls) - 1:  # Last URL
                pass  # Silently handle errors
    
    # Process the metafield definitions we found
    if metafield_definitions:
        # Create a lookup for choice/select options (both list types and single_line_text_field with choices)
        options_lookup = {}
        for definition in metafield_definitions:
            key = definition.get("key", "")
            namespace = definition.get("namespace", "")
            options = definition.get("options", [])
            
            # Check for both list types AND single_line_text_field with choices
            if options and len(options) > 0:
                options_lookup[f"{namespace}:{key}"] = options
    
    if not metafield_definitions:
        pass  # No metafield definitions found
    
    # Add the options to each metafield
    for metafield in metafields:
        metafield_key = f"{metafield.get('namespace', '')}:{metafield.get('key', '')}"
        if metafield_key in options_lookup:
            metafield['available_options'] = options_lookup[metafield_key]
    
    # For choice/select metafields without predefined options, try to extract from existing metafield values
    for metafield in metafields:
        metafield_type = metafield.get('type', '')
        namespace = metafield.get('namespace', '')
        key = metafield.get('key', '')
        current_value = metafield.get('value', '')
        
        # Defer category and subcategory entirely to categories.py; don't inject hardcoded lists here
        if not (namespace == 'custom' and key in ('custom_category', 'subcategory')):
            if current_value and str(current_value).strip():
                # If there's a current value and no preset choices, use it as one option
                metafield['available_options'] = [str(current_value).strip()]
            else:
                # Don't create fake options - only use real ones from Shopify
                pass

    # Ensure category and subcategory options come from categories.py (canonical source)
    try:
        from scripts.product_creator.categories import get_metafield_choices as _get_category_choices, get_subcategory_choices  # type: ignore
        from scripts.product_creator.categories import get_subcategory_metafield_key  # type: ignore
        
        # Collect all subcategory metafields (including overflow ones)
        subcategory_metafields = []
        subcategory_keys = ['subcategory']
        
        # Find all overflow subcategory metafields (subcategory_2, subcategory_3, etc.)
        for metafield in metafields:
            key = metafield.get('key', '')
            if metafield.get('namespace') == 'custom' and key.startswith('subcategory'):
                if key == 'subcategory' or (key.startswith('subcategory_') and key.split('_')[-1].isdigit()):
                    subcategory_keys.append(key)
                    subcategory_metafields.append(metafield)
        
        for metafield in metafields:
            key_only = metafield.get('key')
            if metafield.get('namespace') == 'custom' and key_only == 'custom_category':
                try:
                    choices = _get_category_choices(key_only) or []
                except Exception:
                    choices = []
                metafield['available_options'] = choices
                metafield['type'] = 'list.single_line_text_field'
            elif metafield.get('namespace') == 'custom' and key_only in subcategory_keys:
                # This is a subcategory metafield (main or overflow)
                try:
                    # Get choices for this specific metafield key
                    choices = _get_category_choices(key_only) or []
                except Exception:
                    choices = []
                metafield['available_options'] = choices
                metafield['type'] = 'list.single_line_text_field'
        
        # Merge subcategory values from all overflow metafields into the main subcategory field
        # This ensures users see the subcategory value regardless of which metafield it's stored in
        main_subcategory_field = None
        subcategory_value = None
        
        for metafield in metafields:
            if metafield.get('namespace') == 'custom' and metafield.get('key') == 'subcategory':
                main_subcategory_field = metafield
                # Try to extract value from list format ["value"] or just "value"
                val = metafield.get('value', '')
                if val:
                    try:
                        import json
                        parsed = json.loads(val)
                        if isinstance(parsed, list) and len(parsed) > 0:
                            subcategory_value = parsed[0]
                        else:
                            subcategory_value = val
                    except (json.JSONDecodeError, AttributeError):
                        subcategory_value = val
                break
        
        # Check overflow metafields for subcategory values
        if not subcategory_value:
            for metafield in metafields:
                key = metafield.get('key', '')
                if metafield.get('namespace') == 'custom' and key.startswith('subcategory_') and key.split('_')[-1].isdigit():
                    val = metafield.get('value', '')
                    if val:
                        try:
                            import json
                            parsed = json.loads(val)
                            if isinstance(parsed, list) and len(parsed) > 0:
                                subcategory_value = parsed[0]
                            else:
                                subcategory_value = val
                        except (json.JSONDecodeError, AttributeError):
                            subcategory_value = val
                        break
        
        # Update main subcategory field with merged value
        if main_subcategory_field:
            if subcategory_value:
                main_subcategory_field['value'] = subcategory_value
        else:
            # Ensure subcategory exists even if missing on product
            try:
                # Get all subcategory choices (will be shown in the main field)
                sub_choices = get_subcategory_choices() or []
            except Exception:
                sub_choices = []
            metafields.append({
                'namespace': 'custom',
                'key': 'subcategory',
                'type': 'list.single_line_text_field',
                'value': subcategory_value or '',
                'available_options': sub_choices,
            })
    except Exception:
        # If categories module not available, provide no options rather than hardcoding
        for metafield in metafields:
            if metafield.get('namespace') == 'custom' and (metafield.get('key') == 'custom_category' or 
                                                           metafield.get('key', '').startswith('subcategory')):
                metafield['available_options'] = []
                metafield['type'] = 'list.single_line_text_field'
    
    if not metafield_definitions:
        print("⚠️ No metafield definitions found from any API endpoint", flush=True)
    
    # Process all metafields but mark some as filtered
    real_metafields = []
    metaobjects = []
    other_items = []
    filtered_metafields = []
    
    for m in metafields:
        metafield_type = m.get('type', '')
        namespace = m.get('namespace', '')
        key = m.get('key', '')
        
        # Mark pricejson metafields as filtered (hidden from Field Finder but accessible via API)
        if key.startswith('pricejson') and '.' not in key:
            m['_filtered'] = True
            m['_filter_reason'] = 'pricejson'
            filtered_metafields.append(m)
        # Mark shopify chocolate type metafields as filtered
        elif namespace == 'shopify' and 'chocolate' in key.lower():
            m['_filtered'] = True
            m['_filter_reason'] = 'shopify_chocolate'
            filtered_metafields.append(m)
        # Filter out specific custom fields that shouldn't be shown in Field Finder
        elif namespace == 'custom' and key in ['artworkguidelines', 'artworktemplates', 'packaging if applicable', 'packaging_if_applicable', 'product_colours', 'packaging_colours']:
            m['_filtered'] = True
            m['_filter_reason'] = 'custom_filtered'
            filtered_metafields.append(m)
        # Filter out all global namespace fields
        elif namespace == 'global':
            m['_filtered'] = True
            m['_filter_reason'] = 'global_namespace'
            filtered_metafields.append(m)
        # Handle metaobjects
        elif metafield_type.startswith('metaobject'):
            metaobjects.append(m)
        # All other metafields go to real_metafields
        else:
            # Accept ALL other metafield types
            real_metafields.append(m)
    
    # Only include real metafields (filtered ones are completely excluded)
    valid_metafields = [m for m in real_metafields if m.get('namespace') and m.get('key')]
    
    # Log what was filtered out (reduced output)
    if filtered_metafields:
        print(f"🚫 Hidden {len(filtered_metafields)} filtered metafields from Field Finder", flush=True)
    
    print(f"🎯 Returning {len(valid_metafields)} metafields for Field Finder", flush=True)
    

    
    # Debug: Check for any other namespaces we might be missing
    all_namespaces = set()
    for m in metafields:
        namespace = m.get('namespace', '')
        if namespace and namespace not in ['custom', 'shopify']:
            all_namespaces.add(namespace)
    
    # Debug: Show all metafields being returned
    for m in valid_metafields:
        pass  # Silent processing
    
    # Debug: Show which metafields have available_options
    list_metafields = [m for m in valid_metafields if m.get('type', '').startswith('list.')]
    
    # Debug: Check for custom_category and subcategory fields specifically
    custom_category_metafield = [m for m in valid_metafields if m.get('key') == 'custom_category' and m.get('namespace') == 'custom']
    subcategory_metafield = [m for m in valid_metafields if m.get('key') == 'subcategory' and m.get('namespace') == 'custom']
    
    return valid_metafields

def create_metafield(product_id, namespace, key, value, metafield_type="single_line_text_field"):
    try:
        # Special handling for category and subcategory fields
        if key == 'custom_category' and namespace == 'custom':
            metafield_type = 'list.single_line_text_field'  # Use list type as required by Shopify definition
            print(f"🎯 Forcing custom_category to use type: {metafield_type}", flush=True)
        elif namespace == 'custom' and (key == 'subcategory' or key.startswith('subcategory_')):
            # Determine the correct metafield key for this subcategory value
            try:
                from scripts.product_creator.categories import get_subcategory_metafield_key
                correct_key = get_subcategory_metafield_key(value)
                if correct_key != key:
                    print(f"🔄 Subcategory '{value}' should be in '{correct_key}', not '{key}'. Using correct key.", flush=True)
                    key = correct_key
            except (ImportError, AttributeError):
                # Fallback if helper function not available
                pass
            
            metafield_type = 'list.single_line_text_field'  # Use list type as required by Shopify definition
            print(f"🎯 Forcing subcategory metafield to use type: {metafield_type}", flush=True)
        
        # Format value for list types
        formatted_value = value
        if metafield_type == 'list.single_line_text_field':
            formatted_value = f'["{value}"]'  # Format as JSON array for list types
            print(f"📝 Formatting value for list type: {formatted_value}", flush=True)

        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
        payload = {
            "metafield": {
                "namespace": namespace,
                "key": key,
                "value": formatted_value,
                "type": metafield_type
            }
        }
        
        print(f"Creating metafield {key} for product {product_id}", flush=True)
        response = requests.post(url, headers=HEADERS, data=json.dumps(payload))
        
        if response.status_code == 201:
            metafield_id = response.json().get("metafield", {}).get("id")
            print(f"✅ Successfully created metafield {key} with ID: {metafield_id}", flush=True)
            return metafield_id
        else:
            print(f"❌ Failed to create metafield {key}: {response.status_code}", flush=True)
            print(f"   Response: {response.text}", flush=True)
            return None
            
    except Exception as e:
        print(f"💥 Exception creating metafield {key}: {str(e)}", flush=True)
        return None

def update_metafield(metafield_id, value, metafield_type=None):
    try:
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/metafields/{metafield_id}.json"
        
        # Use the provided metafield type, or default to single_line_text_field
        payload_type = metafield_type if metafield_type else "single_line_text_field"
        
        # Special handling for category and subcategory fields - keep list type
        if metafield_type and metafield_type.startswith('list.'):
            payload_type = metafield_type  # Keep the list type as required by Shopify definition
            print(f"🎯 Preserving list type for metafield: {payload_type}", flush=True)
        
        # Format value for list types
        formatted_value = value
        if payload_type == 'list.single_line_text_field':
            formatted_value = f'["{value}"]'  # Format as JSON array for list types
            print(f"📝 Formatting value for list type: {formatted_value}", flush=True)

        payload = {
            "metafield": {
                "id": metafield_id,
                "value": formatted_value,
                "type": payload_type
            }
        }
        
        print(f"🔄 Updating metafield {metafield_id} with value: {value[:50]}... (type: {payload_type})", flush=True)
        response = requests.put(url, headers=HEADERS, data=json.dumps(payload))
        
        if response.status_code == 200:
            print(f"✅ Successfully updated metafield {metafield_id}", flush=True)
            return True, "Metafield updated successfully"
        else:
            print(f"❌ Failed to update metafield {metafield_id}: {response.status_code}", flush=True)
            print(f"   Response: {response.text}", flush=True)
            print(f"   URL: {url}", flush=True)
            return False, f"HTTP {response.status_code}: {response.text}"
            
    except Exception as e:
        print(f"💥 Exception updating metafield {metafield_id}: {str(e)}", flush=True)
        return False, str(e)

if __name__ == "__main__":
    print("Field Finder is now a web-based tool. Please use the web interface to search and edit product metafields.")
