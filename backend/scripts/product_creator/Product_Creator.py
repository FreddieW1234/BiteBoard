#!/usr/bin/env python3
"""
Product Editor/Creator - Tool for creating and editing products in Shopify
"""

import os
import sys
import requests
import json
import base64
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

# UTF-8 encoding handled at subprocess level in backend

# Add the parent directory to the path so we can import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION
except ImportError:
    print("ERROR: Could not import config. Make sure config.py exists in the backend directory.")
    sys.exit(1)

def format_price(price):
    """Format price to 2 decimal places as string."""
    try:
        decimal_price = Decimal(str(price))
        formatted = decimal_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return str(formatted)
    except (ValueError, TypeError):
        return str(price)

def manage_product_media(product_id, shopify_media_ids_to_keep):
    """
    Remove media from a product that are not in the keep list
    
    Args:
        product_id (int): The ID of the product
        shopify_media_ids_to_keep (list): List of media IDs (global IDs) to keep
    
    Returns:
        dict: Result with success status and any errors
    """
    try:
        print(f"🔄 Managing media for product {product_id}...")
        print(f"📋 Media IDs to keep: {shopify_media_ids_to_keep}")
        
        # Get existing product media
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        headers = {
            'X-Shopify-Access-Token': ACCESS_TOKEN,
            'Content-Type': 'application/json'
        }
        
        response = requests.get(url, headers=headers)
        if not response.ok:
            return {"success": False, "error": f"Failed to get product: {response.status_code}"}
        
        product_data = response.json().get('product', {})
        existing_media = product_data.get('images', [])
        
        print(f"📷 Found {len(existing_media)} existing media items")
        
        # Convert keep list to comparable format
        # We expect REST API numeric IDs (not global IDs) for comparison
        keep_ids = set()
        for media_id in shopify_media_ids_to_keep:
            if isinstance(media_id, str):
                if media_id.startswith('gid://'):
                    # Extract numeric ID from global ID
                    # NOTE: Global ID numeric part is DIFFERENT from REST API ID!
                    # For REST API comparison, we need the REST API numeric ID, not the global ID numeric
                    # But if only global ID is provided, try to extract it anyway
                    keep_ids.add(media_id.split('/')[-1])
                else:
                    # Direct REST API numeric ID (what we want)
                    keep_ids.add(media_id)
            else:
                # Numeric ID converted to string
                keep_ids.add(str(media_id))
        
        print(f"🔑 Keep IDs (normalized): {keep_ids}")
        
        # Debug: Show all existing media IDs
        existing_ids = [str(img.get('id')) for img in existing_media]
        print(f"📋 Existing media IDs on product: {existing_ids}")
        
        # Find media to remove
        media_to_remove = []
        for media in existing_media:
            media_id = str(media.get('id'))
            if media_id not in keep_ids:
                media_to_remove.append(media_id)
                print(f"🗑️ Will remove media ID: {media_id} (not in keep list)")
            else:
                print(f"✅ Will keep media ID: {media_id}")
        
        if not media_to_remove:
            print(f"ℹ️ No media to remove - all {len(existing_media)} existing images are in the keep list")
        else:
            print(f"🗑️ Found {len(media_to_remove)} media items to remove: {media_to_remove}")
        
        # Remove unwanted media
        removed_count = 0
        errors = []
        
        for media_id in media_to_remove:
            try:
                delete_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/images/{media_id}.json"
                print(f"🗑️ Attempting to delete image {media_id} from product {product_id}...")
                delete_response = requests.delete(delete_url, headers=headers)
                
                if delete_response.ok or delete_response.status_code == 204:
                    removed_count += 1
                    print(f"✅ Successfully removed media ID: {media_id}")
                else:
                    error_msg = f"Failed to remove media {media_id}: {delete_response.status_code}"
                    if delete_response.text:
                        error_msg += f" - {delete_response.text[:200]}"
                    errors.append(error_msg)
                    print(f"❌ {error_msg}")
            except Exception as e:
                error_msg = f"Error removing media {media_id}: {str(e)}"
                errors.append(error_msg)
                print(f"💥 {error_msg}")
                import traceback
                print(traceback.format_exc())
        
        return {
            "success": len(errors) == 0,
            "removed_count": removed_count,
            "errors": errors
        }
        
    except Exception as e:
        error_msg = f"Error managing product media: {str(e)}"
        print(f"💥 {error_msg}")
        return {
            "success": False,
            "removed_count": 0,
            "errors": [error_msg]
        }

def reorder_product_media_by_order(product_id, media_order, shopify_media_ids, shopify_domain=None):
    """
    Reorder product media according to the media_order array from frontend
    This includes both newly uploaded files and existing Shopify media
    
    Args:
        product_id (int): The ID of the product
        media_order (list): List of media order items like [{'type': 'upload', 'index': 0}, {'type': 'shopify', 'id': '...', 'position': 1}]
        shopify_media_ids (list): List of Shopify media IDs that were kept (for reference)
        shopify_domain (str, optional): The actual Shopify domain to use (to avoid redirects)
    
    Returns:
        dict: Result with success status
    """
    try:
        if not media_order:
            return {"success": True, "message": "No media order specified"}
        
        print(f"🔄 Reordering media by order for product {product_id}...")
        
        # Use the provided domain or fall back to STORE_DOMAIN
        domain = shopify_domain or STORE_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
        # Get current product media
        url = f"https://{domain}/admin/api/{API_VERSION}/products/{product_id}.json"
        headers = {
            'X-Shopify-Access-Token': ACCESS_TOKEN,
            'Content-Type': 'application/json'
        }
        
        response = requests.get(url, headers=headers)
        if not response.ok:
            return {"success": False, "error": f"Failed to get product: {response.status_code}"}
        
        product_data = response.json().get('product', {})
        existing_images = product_data.get('images', [])
        
        print(f"📷 Found {len(existing_images)} existing images on product")
        
        # Normalize shopify_media_ids for comparison
        normalized_keep_ids = set()
        for media_id in (shopify_media_ids or []):
            if isinstance(media_id, str) and media_id.startswith('gid://'):
                normalized_keep_ids.add(media_id.split('/')[-1])
            else:
                normalized_keep_ids.add(str(media_id))
        
        # Separate existing images from newly uploaded images
        existing_image_ids = set(str(img.get('id')) for img in existing_images if str(img.get('id')) in normalized_keep_ids)
        
        # Identify newly uploaded images (not in the keep list)
        # These are images that were just uploaded and weren't in the original keep list
        new_upload_images = [
            img for img in existing_images 
            if str(img.get('id')) not in normalized_keep_ids
        ]
        # Sort new uploads by creation time or ID (oldest/newest uploads first)
        # If created_at is available, sort by it (ascending = oldest first)
        # Otherwise sort by ID (ascending)
        new_upload_images.sort(key=lambda x: (
            x.get('created_at', '') if x.get('created_at') else '',
            x.get('id', 0)
        ))
        new_upload_ids = [str(img.get('id')) for img in new_upload_images]
        
        # Also create a map of all image IDs for quick lookup
        all_image_map = {str(img.get('id')): img for img in existing_images}
        
        all_image_ids = [str(img.get('id')) for img in existing_images]
        
        # Count how many new uploads we expect
        upload_count = sum(1 for item in media_order if item.get('type') == 'upload')
        shopify_count = sum(1 for item in media_order if item.get('type') == 'shopify')
        
        print(f"📊 Media order: {upload_count} uploads, {shopify_count} Shopify media")
        print(f"📊 Found {len(new_upload_ids)} newly uploaded images")
        
        # Map media order to actual image IDs
        position_map = {}  # Maps desired position -> image ID
        shopify_positions_processed = 0
        upload_positions_processed = 0
        
        # Debug: Print all available images
        print(f"🔍 All available images on product:")
        for img in existing_images:
            img_id = str(img.get('id', ''))
            img_pos = img.get('position', '?')
            img_src = img.get('src', 'N/A')[:50] if img.get('src') else 'N/A'
            is_in_keep = img_id in normalized_keep_ids
            print(f"   ID: {img_id}, Position: {img_pos}, In keep list: {is_in_keep}, Src: {img_src}")
        
        for order_item in media_order:
            item_type = order_item.get('type')
            # Use position from order_item if provided, otherwise use sequential position
            position = order_item.get('position')
            if position is None:
                position = len(position_map) + 1
            
            if item_type == 'shopify':
                # Match by Shopify ID
                media_id = str(order_item.get('id', ''))
                # Try to find by exact match first
                if media_id in all_image_map:
                    position_map[position] = media_id
                    shopify_positions_processed += 1
                    print(f"📍 Position {position}: Shopify media ID {media_id}")
                else:
                    # Try to find by extracting numeric ID from Global ID format
                    numeric_id = media_id
                    if 'gid://' in media_id:
                        numeric_id = media_id.split('/')[-1]
                    # Also try matching just the numeric part
                    found = False
                    for img_id, img_data in all_image_map.items():
                        if img_id == numeric_id or str(img_data.get('id', '')) == numeric_id:
                            position_map[position] = img_id
                            shopify_positions_processed += 1
                            print(f"📍 Position {position}: Shopify media ID {media_id} (matched to image ID {img_id})")
                            found = True
                            break
                    if not found:
                        print(f"⚠️ Could not find Shopify media ID {media_id} in product images")
                        print(f"   Available image IDs: {list(all_image_map.keys())[:10]}...")  # Show first 10 for debugging
            elif item_type == 'upload':
                # Match newly uploaded images by order
                if upload_positions_processed < len(new_upload_ids):
                    image_id = new_upload_ids[upload_positions_processed]
                    position_map[position] = image_id
                    upload_positions_processed += 1
                    print(f"📍 Position {position}: New upload (image ID {image_id})")
                else:
                    print(f"⚠️ Could not find upload at index {upload_positions_processed} (only {len(new_upload_ids)} new uploads found)")
                    # Fallback: For new products, all images might be "new uploads" or newly attached
                    # Try to use images not yet assigned, in the order they appear
                    remaining_images = [img for img in existing_images if str(img.get('id')) not in position_map.values()]
                    if remaining_images:
                        # Sort by position to maintain order
                        remaining_images.sort(key=lambda x: x.get('position', 999))
                        fallback_id = str(remaining_images[0].get('id'))
                        position_map[position] = fallback_id
                        upload_positions_processed += 1
                        print(f"📍 Position {position}: Using fallback image ID {fallback_id} (not yet assigned)")
                    else:
                        print(f"⚠️ No remaining images available for position {position}")
        
        # Verify we have all expected images before reordering
        missing_images = []
        for order_item in media_order:
            if order_item.get('type') == 'shopify':
                media_id = str(order_item.get('id', ''))
                if media_id not in all_image_map:
                    missing_images.append(media_id)
        
        if missing_images:
            print(f"⚠️ Warning: {len(missing_images)} expected images not found. Attempting to continue with available images.")
        
        # Update positions for all images
        errors = []
        successful_updates = []
        for position, image_id in sorted(position_map.items()):
            update_url = f"https://{domain}/admin/api/{API_VERSION}/products/{product_id}/images/{image_id}.json"
            payload = {
                "image": {
                    "id": int(image_id),
                    "position": position
                }
            }
            
            # Handle redirects for PUT requests
            update_response = requests.put(update_url, headers=headers, json=payload, allow_redirects=False)
            if update_response.status_code in [301, 302, 303, 307, 308]:
                redirect_url = update_response.headers.get('Location', update_url)
                if redirect_url.startswith('/'):
                    from urllib.parse import urlparse
                    parsed = urlparse(update_url)
                    redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                update_response = requests.put(redirect_url, headers=headers, json=payload, allow_redirects=True)
            if update_response.ok:
                successful_updates.append((position, image_id))
                print(f"✅ Set position {position} for image ID: {image_id}")
            else:
                error_msg = f"Failed to reorder image {image_id}: {update_response.status_code} - {update_response.text[:200]}"
                errors.append(error_msg)
                print(f"❌ {error_msg}")
        
        print(f"📊 Reordering summary: {len(successful_updates)} successful, {len(errors)} errors")
        
        # After reordering, ensure the first image (position 1) is set as the main product image
        if position_map:
            first_position = min(position_map.keys())
            first_image_id = position_map[first_position]
            print(f"🖼️ Setting image at position {first_position} (ID: {first_image_id}) as main product image...")
            try:
                # Update the product to set the main image
                product_update_url = f"https://{domain}/admin/api/{API_VERSION}/products/{product_id}.json"
                product_update_payload = {
                    "product": {
                        "id": product_id,
                        "image": {
                            "id": int(first_image_id)
                        }
                    }
                }
                product_update_response = requests.put(product_update_url, headers=headers, json=product_update_payload, allow_redirects=False)
                if product_update_response.status_code in [301, 302, 303, 307, 308]:
                    redirect_url = product_update_response.headers.get('Location', product_update_url)
                    if redirect_url.startswith('/'):
                        from urllib.parse import urlparse
                        parsed = urlparse(product_update_url)
                        redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                    product_update_response = requests.put(redirect_url, headers=headers, json=product_update_payload, allow_redirects=True)
                
                if product_update_response.status_code == 200:
                    print(f"✅ Main product image set to image ID: {first_image_id}")
                else:
                    print(f"⚠️ Failed to set main product image: {product_update_response.status_code}")
            except Exception as e:
                print(f"⚠️ Error setting main product image: {e}")
        
        return {
            "success": len(errors) == 0,
            "errors": errors
        }
        
    except Exception as e:
        error_msg = f"Error reordering product media by order: {str(e)}"
        print(f"💥 {error_msg}")
        return {
            "success": False,
            "errors": [error_msg]
        }

def reorder_product_media(product_id, shopify_media_ids_in_order):
    """
    Reorder product media according to the specified order
    
    Args:
        product_id (int): The ID of the product
        shopify_media_ids_in_order (list): List of media IDs in desired order
    
    Returns:
        dict: Result with success status
    """
    try:
        if not shopify_media_ids_in_order:
            return {"success": True, "message": "No media to reorder"}
        
        print(f"🔄 Reordering {len(shopify_media_ids_in_order)} media items for product {product_id}...")
        
        # Get existing product media
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        headers = {
            'X-Shopify-Access-Token': ACCESS_TOKEN,
            'Content-Type': 'application/json'
        }
        
        response = requests.get(url, headers=headers)
        if not response.ok:
            return {"success": False, "error": f"Failed to get product: {response.status_code}"}
        
        product_data = response.json().get('product', {})
        existing_images = product_data.get('images', [])
        
        # Create a mapping of image IDs to their data
        image_map = {str(img.get('id')): img for img in existing_images}
        
        # Update positions for each image
        errors = []
        for position, media_id in enumerate(shopify_media_ids_in_order, start=1):
            # Normalize media ID
            if isinstance(media_id, str) and media_id.startswith('gid://'):
                media_id = media_id.split('/')[-1]
            media_id = str(media_id)
            
            if media_id in image_map:
                image_id = image_map[media_id]['id']
                update_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/images/{image_id}.json"
                payload = {
                    "image": {
                        "id": image_id,
                        "position": position
                    }
                }
                
                update_response = requests.put(update_url, headers=headers, json=payload)
                if update_response.ok:
                    print(f"✅ Set position {position} for media ID: {media_id}")
                else:
                    error_msg = f"Failed to reorder media {media_id}: {update_response.status_code}"
                    errors.append(error_msg)
                    print(f"❌ {error_msg}")
        
        return {
            "success": len(errors) == 0,
            "errors": errors
        }
        
    except Exception as e:
        error_msg = f"Error reordering product media: {str(e)}"
        print(f"💥 {error_msg}")
        return {
            "success": False,
            "errors": [error_msg]
        }

def upload_media_to_product(product_id, media_files, shopify_media_ids=None, product_name=None, product_sku=None, shopify_domain=None):
    """
    Upload media files (images/videos) to a Shopify product using the correct API
    
    Args:
        product_id (int): The ID of the product to add media to
        media_files (list): List of media file dictionaries with filename, content, and content_type
        shopify_media_ids (list): List of existing Shopify media file IDs to attach to the product
        product_name (str): The product name for file naming (format: {product_name}_{x})
        product_sku (str): The product SKU for file naming
        shopify_domain (str, optional): The actual Shopify domain to use (to avoid redirects)
    
    Returns:
        dict: Result with success status and any errors
    """
    try:
        # Use provided domain or fall back to STORE_DOMAIN
        domain = shopify_domain or STORE_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
        
        total_media = len(media_files) + (len(shopify_media_ids) if shopify_media_ids else 0)
        
        if total_media == 0:
            return {"success": True, "message": "No media files to upload"}
        
        print(f"🔄 Uploading {len(media_files)} new files and attaching {len(shopify_media_ids) if shopify_media_ids else 0} existing files to product {product_id}")
        
        success_count = 0
        errors = []
        
        # Helper to sanitize parts for filenames
        def _sanitize(value):
            s = "" if value is None else str(value)
            # allow letters, numbers, space, dash, underscore
            s = "".join(c for c in s if c.isalnum() or c in (' ', '-', '_')).rstrip()
            s = s.replace(' ', '_')
            while '__' in s:
                s = s.replace('__', '_')
            return s[:120] if s else ''

        # IMPORTANT: Attach existing Shopify media files FIRST to match frontend index order
        # Frontend sends indices based on [shopifyMedia, newMediaFiles], so we need to attach
        # existing files first, then upload new files to maintain the correct index mapping
        attached_media_count = 0
        if shopify_media_ids:
            print(f"🔄 Attaching {len(shopify_media_ids)} existing Shopify media files to product {product_id} (FIRST to match frontend order)")
            
            try:
                # Use the provided domain or fall back to STORE_DOMAIN
                graphql_domain = shopify_domain or STORE_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
                graphql_url = f"https://{graphql_domain}/admin/api/{API_VERSION}/graphql.json"
                headers = {
                    'X-Shopify-Access-Token': ACCESS_TOKEN,
                    'Content-Type': 'application/json',
                }
                
                # Convert product ID to Global ID format
                product_global_id = f"gid://shopify/Product/{product_id}"
                
                # Prepare file updates for each media ID
                file_updates = []
                for media_id in shopify_media_ids:
                    # Convert to string first to handle both int and str types
                    media_id_str = str(media_id)
                    
                    # Determine the Global ID format
                    if media_id_str.isdigit():
                        # Numeric ID - could be GenericFile or MediaImage
                        # Try MediaImage first (more common for product images)
                        media_global_id = f"gid://shopify/MediaImage/{media_id_str}"
                    elif media_id_str.startswith('gid://shopify/'):
                        # Already a Global ID - use as is
                        media_global_id = media_id_str
                    else:
                        # Assume it's a numeric ID that wasn't converted properly
                        media_global_id = f"gid://shopify/MediaImage/{media_id_str}"
                    
                    print(f"🔍 Attaching media with Global ID: {media_global_id}", flush=True)
                    file_updates.append({
                        "id": media_global_id,
                        "referencesToAdd": [product_global_id]
                    })
                
                # GraphQL mutation to attach files to product
                mutation = """
                mutation fileUpdate($input: [FileUpdateInput!]!) {
                    fileUpdate(files: $input) {
                        files {
                            id
                            alt
                        }
                        userErrors {
                            field
                            message
                        }
                    }
                }
                """
                
                variables = {
                    "input": file_updates
                }
                
                # Handle redirects for GraphQL requests
                response = requests.post(graphql_url, json={'query': mutation, 'variables': variables}, headers=headers, allow_redirects=False)
                
                # If redirected, follow it
                if response.status_code in [301, 302, 303, 307, 308]:
                    redirect_url = response.headers.get('Location', graphql_url)
                    if redirect_url.startswith('/'):
                        from urllib.parse import urlparse
                        parsed = urlparse(graphql_url)
                        redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                    response = requests.post(redirect_url, json={'query': mutation, 'variables': variables}, headers=headers, allow_redirects=True)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Check for GraphQL errors
                    if 'errors' in data:
                        error_msg = f"GraphQL errors: {data['errors']}"
                        errors.append(error_msg)
                        print(f"❌ {error_msg}", flush=True)
                        print(f"🔍 Full response: {json.dumps(data, indent=2)}", flush=True)
                    elif 'data' in data and 'fileUpdate' in data['data']:
                        result = data['data']['fileUpdate']
                        
                        if result.get('userErrors'):
                            for error in result['userErrors']:
                                error_msg = f"User error: {error.get('field', 'unknown')} - {error.get('message', 'Unknown error')}"
                                errors.append(error_msg)
                                print(f"❌ {error_msg}", flush=True)
                        
                        if result.get('files'):
                            attached_media_count = len(result['files'])
                            success_count += attached_media_count
                            for file in result['files']:
                                filename = file.get('alt', file.get('id', 'Unknown'))
                                print(f"✅ Attached existing media: {filename}", flush=True)
                            # Small delay to ensure attached files are indexed before uploading new files
                            if media_files:
                                print("⏳ Waiting 1 second for attached files to be indexed...", flush=True)
                                import time
                                time.sleep(1.0)
                        else:
                            error_msg = "No files were attached - check file IDs and permissions"
                            errors.append(error_msg)
                            print(f"❌ {error_msg}", flush=True)
                            print(f"🔍 Response data: {json.dumps(data, indent=2)}", flush=True)
                    else:
                        error_msg = "Invalid response format from Shopify GraphQL"
                        errors.append(error_msg)
                        print(f"❌ {error_msg}", flush=True)
                        print(f"🔍 Response: {json.dumps(data, indent=2) if isinstance(data, dict) else str(data)}", flush=True)
                else:
                    error_msg = f"HTTP error: {response.status_code} - {response.text[:500]}"
                    errors.append(error_msg)
                    print(f"❌ {error_msg}", flush=True)
                    
            except Exception as e:
                error_msg = f"Error attaching existing media files: {str(e)}"
                errors.append(error_msg)
                print(f"💥 {error_msg}", flush=True)
        
        # Upload new media files (AFTER attaching existing ones to maintain index order)
        for i, media_file in enumerate(media_files):
            try:
                original_filename = media_file['filename']
                content = media_file['content']
                content_type = media_file['content_type']
                
                # Create new filename with SKU, product name and position: {SKU}_{product name}_{x}
                clean_name = _sanitize(product_name or '')
                clean_sku = _sanitize(product_sku or '') or 'NOSKU'
                file_extension = original_filename.split('.')[-1] if '.' in original_filename else ''
                base = f"{clean_sku}_{clean_name}_{i+1}" if clean_name else f"{clean_sku}_{i+1}"
                filename = f"{base}.{file_extension}" if file_extension else base
                
                # Determine if it's an image or video
                is_video = content_type.startswith('video/')
                media_type = 'video' if is_video else 'image'
                
                # Use the correct Shopify API endpoint for product media
                if is_video:
                    # For videos, use the product media endpoint
                    url = f"https://{domain}/admin/api/{API_VERSION}/products/{product_id}/media.json"
                    
                    # Create multipart form data for video upload
                    files = {
                        'media[attachment]': (filename, content, content_type)
                    }
                    data = {
                        'media[alt]': ''
                    }
                    
                    headers = {
                        "X-Shopify-Access-Token": ACCESS_TOKEN
                    }
                    
                    # Handle redirects for POST requests
                    response = requests.post(url, headers=headers, files=files, data=data, allow_redirects=False)
                    if response.status_code in [301, 302, 303, 307, 308]:
                        redirect_url = response.headers.get('Location', url)
                        if redirect_url.startswith('/'):
                            from urllib.parse import urlparse
                            parsed = urlparse(url)
                            redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                        response = requests.post(redirect_url, headers=headers, files=files, data=data, allow_redirects=True)
                    
                else:
                    # For images, use the product images endpoint
                    url = f"https://{domain}/admin/api/{API_VERSION}/products/{product_id}/images.json"
                    
                    # Create multipart form data for image upload
                    files = {
                        'image[attachment]': (filename, content, content_type)
                    }
                    data = {
                        'image[alt]': ''
                    }
                    
                    headers = {
                        "X-Shopify-Access-Token": ACCESS_TOKEN
                    }
                    
                    # Handle redirects for POST requests
                    response = requests.post(url, headers=headers, files=files, data=data, allow_redirects=False)
                    if response.status_code in [301, 302, 303, 307, 308]:
                        redirect_url = response.headers.get('Location', url)
                        if redirect_url.startswith('/'):
                            from urllib.parse import urlparse
                            parsed = urlparse(url)
                            redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                        response = requests.post(redirect_url, headers=headers, files=files, data=data, allow_redirects=True)
                
                if response.status_code in [200, 201]:
                    success_count += 1
                    response_data = response.json()
                    media_id = response_data.get('image', {}).get('id') or response_data.get('media', {}).get('id')
                    print(f"✅ Uploaded {media_type}: {filename} (ID: {media_id})")
                else:
                    error_msg = f"Failed to upload {media_type} {filename}: {response.status_code} - {response.text}"
                    errors.append(error_msg)
                    print(f"❌ {error_msg}")
                    
            except Exception as e:
                error_msg = f"Error uploading media file {filename}: {str(e)}"
                errors.append(error_msg)
                print(f"💥 {error_msg}")
        
        # Fetch product images after upload to get their IDs
        product_images = []
        if total_media > 0:
            try:
                get_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
                get_response = requests.get(get_url, headers=headers)
                if get_response.status_code == 200:
                    product_data = get_response.json().get("product", {})
                    product_images = product_data.get("images", [])
                    print(f"🔍 Fetched {len(product_images)} product images", flush=True)
            except Exception as e:
                print(f"⚠️ Failed to fetch product images: {e}", flush=True)
        
        return {
            "success": len(errors) == 0,
            "success_count": success_count,
            "errors": errors,
            "product_images": product_images  # Return product images for reference
        }
        
    except Exception as e:
        error_msg = f"Error uploading media files: {str(e)}"
        print(f"💥 {error_msg}")
        return {
            "success": False,
            "success_count": 0,
            "errors": [error_msg]
        }

def update_product_taxable(product_id, taxable):
    """
    Update the taxable field for a product's variants
    
    Args:
        product_id (int): The ID of the product to update
        taxable (bool): Whether the product should be taxable
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        headers = {
            "X-Shopify-Access-Token": ACCESS_TOKEN,
            "Content-Type": "application/json"
        }
        
        # First, get the current product to get existing variants
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to get product for taxable update: {response.status_code}")
            return False
        
        product_data = response.json()["product"]
        variants = product_data.get("variants", [])
        
        # Update each variant with the taxable field
        for variant in variants:
            variant["taxable"] = taxable
        
        # Update the product with modified variants
        payload = {
            "product": {
                "id": product_id,
                "variants": variants
            }
        }
        
        update_response = requests.put(url, headers=headers, json=payload)
        if update_response.status_code == 200:
            response_data = update_response.json()
            updated_variants = response_data.get("product", {}).get("variants", [])
            print(f"✅ Updated taxable field to {taxable} for product {product_id}")
            return True
        else:
            print(f"❌ Failed to update taxable field: {update_response.status_code} - {update_response.text}")
            return False
            
    except Exception as e:
        print(f"💥 Error updating taxable field: {str(e)}")
        return False

def create_metafields(product_id, metafields_data, shopify_domain=None):
    """
    Create or update metafields for a product (upsert - update if exists, create if not)
    
    Args:
        product_id (int): The ID of the product to add metafields to
        metafields_data (list): List of metafield data dictionaries
        shopify_domain (str, optional): The actual Shopify domain to use (to avoid redirects)
    
    Returns:
        dict: Result with success status and any errors
    """
    try:
        # Use provided domain or fall back to STORE_DOMAIN
        domain = shopify_domain or STORE_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
        base_url = f"https://{domain}/admin/api/{API_VERSION}/products/{product_id}"
        headers = {
            "X-Shopify-Access-Token": ACCESS_TOKEN,
            "Content-Type": "application/json"
        }
        
        # Fetch existing metafields to support upsert (POST fails with 422 if namespace+key already exists)
        existing_by_ns_key = {}
        try:
            resp = requests.get(f"{base_url}/metafields.json?limit=250", headers=headers)
            if resp.status_code == 200:
                for mf in resp.json().get("metafields", []):
                    ns, k = mf.get("namespace", ""), mf.get("key", "")
                    if ns and k:
                        existing_by_ns_key[(ns, k)] = mf.get("id")
        except Exception as e:
            print(f"⚠️ Could not fetch existing metafields for upsert: {e}", flush=True)
        
        success_count = 0
        errors = []
        
        for metafield_data in metafields_data:
            try:
                # Normalize value formatting based on metafield type
                raw_value = metafield_data.get("value", "")
                mf_type = metafield_data.get("type", "single_line_text_field") or "single_line_text_field"

                # For list types, Shopify expects a JSON array string
                formatted_value = raw_value
                try:
                    if isinstance(raw_value, str) and raw_value.strip() and mf_type.startswith('list.'):
                        v = raw_value.strip()
                        # If not already a JSON array (simple heuristic), wrap it
                        is_json_array = (v.startswith('[') and v.endswith(']'))
                        formatted_value = v if is_json_array else json.dumps([v])
                except Exception:
                    # Fallback to raw value if formatting fails
                    formatted_value = raw_value
                
                # Replace blank/empty values with "-" (except for list types which should remain as JSON arrays)
                # Also skip if value is already a valid JSON array (for list types)
                if not mf_type.startswith('list.'):
                    # For non-list types, check if value is blank
                    if isinstance(formatted_value, str):
                        if not formatted_value.strip():
                            formatted_value = "-"
                    elif formatted_value is None or formatted_value == "":
                        formatted_value = "-"
                elif mf_type.startswith('list.'):
                    # For list types, only replace if it's an empty string (not a valid JSON array)
                    if isinstance(formatted_value, str):
                        stripped = formatted_value.strip()
                        if not stripped or stripped == '[]' or (not stripped.startswith('[') and not stripped):
                            formatted_value = json.dumps(["-"])
                    # For subcategory metafields, Shopify enforces choices - filter to allowed values only
                    # (Don't skip overflow keys like subcategory_2 - let them through; 422 retry will fix if needed)
                    namespace = metafield_data.get("namespace", "custom")
                    key = metafield_data.get("key", "")
                    if namespace == "custom" and key and (key == "subcategory" or key.startswith("subcategory_")):
                        try:
                            from .categories import get_metafield_choices
                            allowed = set(get_metafield_choices(key) or [])
                            if allowed:
                                parsed = json.loads(formatted_value) if isinstance(formatted_value, str) else formatted_value
                                if isinstance(parsed, list):
                                    filtered = [v for v in parsed if str(v).strip() in allowed]
                                    if filtered != parsed:
                                        print(f"⚠️ Filtered subcategory values for {key}: kept {filtered}, removed {set(parsed) - set(filtered)}", flush=True)
                                    if not filtered:
                                        continue  # Skip - no valid choices; sending invalid value causes 422
                                    formatted_value = json.dumps(filtered)
                        except Exception as e:
                            print(f"⚠️ Could not filter subcategory choices for {key}: {e}", flush=True)

                namespace = metafield_data.get("namespace", "custom")
                key = metafield_data.get("key", "")
                existing_id = existing_by_ns_key.get((namespace, key))
                
                if existing_id:
                    # Update existing metafield (PUT) - only send value (type is immutable on update)
                    payload = {"metafield": {"value": formatted_value}}
                    url = f"{base_url}/metafields/{existing_id}.json"
                    response = requests.put(url, headers=headers, json=payload, allow_redirects=False)
                    if response.status_code in [301, 302, 303, 307, 308]:
                        redirect_url = response.headers.get('Location', url)
                        if redirect_url.startswith('/'):
                            from urllib.parse import urlparse
                            parsed = urlparse(url)
                            redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                        response = requests.put(redirect_url, headers=headers, json=payload, allow_redirects=True)
                else:
                    # Create new metafield (POST)
                    payload = {
                        "metafield": {
                            "namespace": namespace,
                            "key": key,
                            "value": formatted_value,
                            "type": mf_type
                        }
                    }
                    url = f"{base_url}/metafields.json"
                    response = requests.post(url, headers=headers, json=payload, allow_redirects=False)
                    if response.status_code in [301, 302, 303, 307, 308]:
                        redirect_url = response.headers.get('Location', url)
                        if redirect_url.startswith('/'):
                            from urllib.parse import urlparse
                            parsed = urlparse(url)
                            redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                        response = requests.post(redirect_url, headers=headers, json=payload, allow_redirects=True)
                
                if response.status_code in [200, 201]:
                    success_count += 1
                    action = "Updated" if existing_id else "Created"
                    print(f"✅ {action} metafield: {namespace}.{key}", flush=True)
                elif response.status_code == 422 and mf_type.startswith('list.') and namespace == "custom" and (key == "subcategory" or key.startswith("subcategory_")):
                    # 422 "does not exist in provided choices" - extract Shopify's actual choices and retry with filtered value
                    # Applies to subcategory, subcategory_2, subcategory_3, etc.
                    import re
                    try:
                        err_data = response.json()
                        err_val = (err_data.get("errors") or {}).get("value") or []
                        err_str = err_val[0] if isinstance(err_val, list) else str(err_val)
                        if "does not exist in provided choices" in err_str and "[" in err_str:
                            match = re.search(r'choices:\s*(\[.*\])', err_str, re.DOTALL)
                            if match:
                                allowed_json = match.group(1).replace("\\\"", "\"").replace("\\/", "/").rstrip(".")
                                allowed = set(json.loads(allowed_json))
                                parsed = json.loads(formatted_value) if isinstance(formatted_value, str) else formatted_value
                                if isinstance(parsed, list) and allowed:
                                    # Match flexibly (strip, normalize) and use Shopify's exact choice string
                                    def _match_choice(v):
                                        s = str(v).strip()
                                        if s in allowed:
                                            return s
                                        for a in allowed:
                                            if a.strip() == s or a.strip().lower() == s.lower():
                                                return a  # Use Shopify's exact string
                                        return None
                                    filtered = []
                                    for v in parsed:
                                        c = _match_choice(v)
                                        if c:
                                            filtered.append(c)
                                    if filtered:
                                        formatted_value = json.dumps(filtered)
                                        payload = {"metafield": {"value": formatted_value}} if existing_id else {"metafield": {"namespace": namespace, "key": key, "value": formatted_value, "type": mf_type}}
                                        retry_url = f"{base_url}/metafields/{existing_id}.json" if existing_id else f"{base_url}/metafields.json"
                                        retry_resp = requests.put(retry_url, headers=headers, json=payload, allow_redirects=True) if existing_id else requests.post(retry_url, headers=headers, json=payload, allow_redirects=True)
                                        if retry_resp.status_code in [200, 201]:
                                            success_count += 1
                                            action = "Updated" if existing_id else "Created"
                                            print(f"✅ {action} metafield (after 422 retry): {namespace}.{key}", flush=True)
                                            continue
                    except Exception as retry_e:
                        print(f"⚠️ 422 retry failed for {namespace}.{key}: {retry_e}", flush=True)
                    error_msg = f"Failed to create metafield {metafield_data.get('namespace')}.{metafield_data.get('key')}: {response.status_code} - {response.text}"
                    errors.append(error_msg)
                    print(f"❌ {error_msg}")
                else:
                    error_msg = f"Failed to create metafield {metafield_data.get('namespace')}.{metafield_data.get('key')}: {response.status_code} - {response.text}"
                    errors.append(error_msg)
                    print(f"❌ {error_msg}")
                    
            except Exception as e:
                error_msg = f"Error creating metafield {metafield_data.get('namespace')}.{metafield_data.get('key')}: {str(e)}"
                errors.append(error_msg)
                print(f"💥 {error_msg}")
        
        return {
            "success": len(errors) == 0,
            "success_count": success_count,
            "errors": errors
        }
        
    except Exception as e:
        error_msg = f"Error creating metafields: {str(e)}"
        print(f"💥 {error_msg}")
        return {
            "success": False,
            "success_count": 0,
            "errors": [error_msg]
        }

def create_product(product_data):
    """
    Create a new product in Shopify using the Admin API, or update existing product if product_id is provided

    Args:
        product_data (dict): Product information including title, description, etc.

    Returns:
        dict: Result with success status and product information
    """
    try:
        # Check if we're updating an existing product
        existing_product_id = product_data.get("product_id")
        if existing_product_id:
            # Update existing product
            # Ensure STORE_DOMAIN doesn't already include protocol
            domain = STORE_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
            url = f"https://{domain}/admin/api/{API_VERSION}/products/{existing_product_id}.json"
            method = "PUT"
            print(f"🔄 Updating existing product {existing_product_id}")
        else:
            # Create new product
            # Ensure STORE_DOMAIN doesn't already include protocol and has no trailing slash
            domain = STORE_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
            url = f"https://{domain}/admin/api/{API_VERSION}/products.json"
            method = "POST"
            print(f"➕ Creating new product")
            print(f"🔍 Final URL: {url}", flush=True)

        headers = {
            "X-Shopify-Access-Token": ACCESS_TOKEN,
            "Content-Type": "application/json",
            "Cache-Control": "no-cache"
        }
        
        # Determine if product should be taxable based on VAT setting
        tags = product_data.get("tags", "")
        charge_vat_raw = product_data.get("charge_vat", True)  # Default to True if not provided
        
        # Convert to boolean if it's a string (from form data)
        if isinstance(charge_vat_raw, str):
            charge_vat = charge_vat_raw.lower() in ['true', '1', 'yes']
        else:
            charge_vat = bool(charge_vat_raw)
        
        taxable = charge_vat
        
        print(f"🏷️ Tags: {tags}")
        print(f"💰 Taxable setting: {taxable}")
        
        # Check if colours are provided
        product_colours_raw = product_data.get("product_colours") or ""
        product_colours = str(product_colours_raw).strip() if product_colours_raw else ""
        has_colours = bool(product_colours)
        
        # Store the expected title to match against response
        expected_title = product_data.get("title", "").strip()
        
        # Validate that we have a title
        if not expected_title:
            error_msg = "Product title is required and cannot be empty"
            print(f"❌ {error_msg}", flush=True)
            return {
                "success": False,
                "error": error_msg
            }
        
        # Prepare the product payload (without taxable field initially)
        # Ensure variant has valid data - Shopify may reject empty/invalid variants
        variant_price = format_price(product_data.get("price", "0.00"))
        variant_sku = product_data.get("sku", "").strip()
        variant_weight = product_data.get("weight", 0)
        
        # Build variant payload - only include fields that have values
        variant_payload = {
            "price": variant_price,
            "requires_shipping": True
        }
        
        # Only add SKU if it's not empty
        if variant_sku:
            variant_payload["sku"] = variant_sku
        
        # Only add weight if it's greater than 0
        if variant_weight and float(variant_weight) > 0:
            variant_payload["weight"] = float(variant_weight)
        
        # Only add inventory_quantity if it's provided
        inventory_qty = product_data.get("inventory_quantity")
        if inventory_qty is not None:
            variant_payload["inventory_quantity"] = int(inventory_qty)
        
        payload = {
            "product": {
                "title": expected_title,
                "body_html": product_data.get("description", ""),
                "status": product_data.get("status", "active"),
                "tags": tags,
                "variants": [variant_payload]
            }
        }
        
        # Debug: Print the description being saved
        description = product_data.get("description", "")
        print(f"🔍 Description being saved: {repr(description)}", flush=True)
        print(f"🔍 Description contains h3: {'<h3>' in description}", flush=True)
        
        # Don't set options for NEW products - let Price Bandit handle the full variant structure
        # Setting options without variants causes Shopify API errors
        if method == "POST":
            # Just create the product with a single basic variant
            # Price Bandit will handle the options and variants
            pass
        
        # For existing products, only update product-level fields to avoid variant/option conflicts
        # Price Bandit will handle variants in Step 4
        if method == "PUT":
            # Remove variants and options from payload - Shopify API doesn't allow clearing options
            # We'll only update product-level fields here, let Price Bandit handle variants later
            print("ℹ️ Updating product-level fields only for existing product (Price Bandit will handle variants)")
            payload["product"].pop("variants", None)
            # Don't send options field either
        
        print(f"🔄 Step 1: {'Updating' if existing_product_id else 'Creating'} product: {product_data.get('title', 'Untitled')}")
        print(f"🔍 Payload being sent to Shopify:", flush=True)
        import json
        print(json.dumps(payload, indent=2), flush=True)

        # Extract the actual Shopify domain from redirects (if any)
        # This will be used for all subsequent API calls to avoid redirects
        actual_shopify_domain = None
        
        # Ensure we're sending the request correctly
        # For both PUT and POST requests, handle redirects manually to preserve method
        if method == "PUT":
            # For PUT, first try without following redirects
            response = requests.put(url, headers=headers, json=payload, allow_redirects=False)
            
            # Check if we got a redirect status code
            if response.status_code in [301, 302, 303, 307, 308]:
                redirect_url = response.headers.get('Location', url)
                # Handle relative redirects
                if redirect_url.startswith('/'):
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                
                # Extract the actual Shopify domain from the redirect URL
                from urllib.parse import urlparse
                parsed_redirect = urlparse(redirect_url)
                actual_shopify_domain = parsed_redirect.netloc
                
                # Follow redirect with PUT method preserved
                response = requests.put(redirect_url, headers=headers, json=payload, allow_redirects=True)
            else:
                # Extract domain from response URL in case of redirects
                if hasattr(response, 'url') and response.url != url:
                    from urllib.parse import urlparse
                    parsed = urlparse(response.url)
                    actual_shopify_domain = parsed.netloc
        else:
            # For POST, first try without following redirects
            response = requests.post(url, headers=headers, json=payload, allow_redirects=False)
            
            # Check if we got a redirect status code
            if response.status_code in [301, 302, 303, 307, 308]:
                redirect_url = response.headers.get('Location', url)
                # Handle relative redirects
                if redirect_url.startswith('/'):
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                print(f"⚠️ POST request redirected {response.status_code} to: {redirect_url}", flush=True)
                
                # Extract the actual Shopify domain from the redirect URL
                from urllib.parse import urlparse
                parsed_redirect = urlparse(redirect_url)
                actual_shopify_domain = parsed_redirect.netloc
                print(f"🔍 Extracted Shopify domain: {actual_shopify_domain}", flush=True)
                
                # Follow redirect with POST method preserved
                response = requests.post(redirect_url, headers=headers, json=payload, allow_redirects=True)
            
            # Check if we were redirected (which would be unusual for a POST)
            if hasattr(response, 'history') and response.history:
                print(f"⚠️ Request was redirected {len(response.history)} time(s)", flush=True)
                for hist in response.history:
                    print(f"   Redirect: {hist.status_code} -> {hist.url}", flush=True)
                # If POST was redirected, check if it was converted to GET
                if response.url != url:
                    print(f"⚠️ Final URL differs from original: {url} -> {response.url}", flush=True)
                    # Extract domain from final URL if we didn't get it from redirect header
                    if not actual_shopify_domain:
                        from urllib.parse import urlparse
                        parsed_final = urlparse(response.url)
                        actual_shopify_domain = parsed_final.netloc
                        print(f"🔍 Extracted Shopify domain from final URL: {actual_shopify_domain}", flush=True)
        
        # Log the full response for debugging
        print(f"🔍 Shopify API Response Status: {response.status_code}", flush=True)
        print(f"🔍 Shopify API Response Headers: {dict(response.headers)}", flush=True)
        print(f"🔍 Shopify API Request URL: {url}", flush=True)
        print(f"🔍 Shopify API Request Method: {method}", flush=True)
        
        # Log raw response text for debugging (first 2000 chars)
        print(f"🔍 Raw Response Text (first 2000 chars): {response.text[:2000]}", flush=True)
        
        # Check for non-success status codes first
        if response.status_code not in [200, 201]:
            error_msg = f"Shopify API returned status {response.status_code}. Response: {response.text[:1000]}"
            print(f"❌ {error_msg}", flush=True)
            return {
                "success": False,
                "error": error_msg
            }
        
        if response.status_code in [200, 201]:
            try:
                result = response.json()
                print(f"🔍 Shopify API Response JSON keys: {list(result.keys())}", flush=True)
                # Log a sample of the response for debugging (first 500 chars)
                result_str = str(result)
                if len(result_str) > 500:
                    print(f"🔍 Shopify API Response (first 500 chars): {result_str[:500]}...", flush=True)
                else:
                    print(f"🔍 Shopify API Response: {result_str}", flush=True)
            except Exception as e:
                error_msg = f"Failed to parse Shopify API response: {str(e)}. Response text: {response.text[:500]}"
                print(f"❌ {error_msg}", flush=True)
                return {
                    "success": False,
                    "error": error_msg
                }
            
            # Check for errors in the response body (Shopify sometimes returns 200 with errors)
            if "errors" in result:
                error_msg = f"Shopify API returned errors: {result.get('errors')}"
                print(f"❌ {error_msg}", flush=True)
                return {
                    "success": False,
                    "error": error_msg
                }
            
            # Handle both 'product' (singular) and 'products' (plural) response formats
            product = None
            if "product" in result:
                product = result.get("product", {})
                print(f"✅ Response contains 'product' (singular)", flush=True)
            elif "products" in result:
                products_list = result.get("products", [])
                print(f"🔍 Response contains 'products' array with {len(products_list)} product(s)", flush=True)
                
                # If we're creating a NEW product, getting a 'products' array is unexpected and likely an error
                if not existing_product_id:
                    # Log all products in the array for debugging
                    print(f"🔍 Products in response:", flush=True)
                    for idx, p in enumerate(products_list[:10]):  # Limit to first 10 for readability
                        print(f"   {idx + 1}. ID: {p.get('id')}, Title: '{p.get('title')}', Created: {p.get('created_at')}", flush=True)
                    if len(products_list) > 10:
                        print(f"   ... and {len(products_list) - 10} more products", flush=True)
                    
                    # Try to find the product that matches the title we just created
                    matching_product = None
                    if expected_title:
                        for p in products_list:
                            if p.get("title") == expected_title:
                                matching_product = p
                                print(f"✅ Found matching product by title: '{expected_title}' (ID: {p.get('id')})", flush=True)
                                break
                    
                    # If no match found, try to fetch the product by making a separate API call
                    if not matching_product and expected_title:
                        print(f"🔍 Product not found in response array. Attempting to fetch product by title...", flush=True)
                        try:
                            # Try to get the product by searching for it by title
                            from urllib.parse import quote
                            search_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products.json?title={quote(expected_title)}"
                            search_response = requests.get(search_url, headers=headers)
                            if search_response.status_code == 200:
                                search_result = search_response.json()
                                if "products" in search_result and search_result["products"]:
                                    for p in search_result["products"]:
                                        if p.get("title") == expected_title:
                                            matching_product = p
                                            print(f"✅ Found product via search: '{expected_title}' (ID: {p.get('id')})", flush=True)
                                            break
                        except Exception as e:
                            print(f"⚠️ Error searching for product: {str(e)}", flush=True)
                        
                        # If still not found, try getting the most recently created product (within last minute)
                        if not matching_product:
                            print(f"🔍 Trying to find most recently created product...", flush=True)
                            try:
                                from datetime import datetime, timedelta
                                now = datetime.utcnow()
                                one_minute_ago = now - timedelta(minutes=1)
                                
                                # Get products sorted by created_at descending, limit to 5
                                recent_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products.json?limit=5&order=created_at desc"
                                recent_response = requests.get(recent_url, headers=headers)
                                if recent_response.status_code == 200:
                                    recent_result = recent_response.json()
                                    if "products" in recent_result and recent_result["products"]:
                                        for p in recent_result["products"]:
                                            created_str = p.get("created_at", "")
                                            if created_str:
                                                try:
                                                    created_at = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                                                    if created_at.replace(tzinfo=None) >= one_minute_ago:
                                                        if p.get("title") == expected_title:
                                                            matching_product = p
                                                            print(f"✅ Found recently created product: '{expected_title}' (ID: {p.get('id')})", flush=True)
                                                            break
                                                except:
                                                    pass
                            except Exception as e:
                                print(f"⚠️ Error finding recent product: {str(e)}", flush=True)
                    
                    # If still no match found, this is an error - Shopify didn't create our product
                    if not matching_product:
                        error_msg = f"Failed to create product: Shopify API returned a list of existing products instead of the newly created product. Expected title: '{expected_title}'. The product was not found in the response or via search. This suggests the product was not created. Please check Shopify API logs or try again."
                        print(f"❌ {error_msg}", flush=True)
                        print(f"🔍 Full response (first 1000 chars): {str(result)[:1000]}", flush=True)
                        return {
                            "success": False,
                            "error": error_msg
                        }
                    
                    product = matching_product
                else:
                    # For updates, we might get a products array - try to find the updated product
                    if products_list and len(products_list) > 0:
                        # Try to find the product that matches the title we just updated
                        matching_product = None
                        if expected_title:
                            for p in products_list:
                                if p.get("title") == expected_title and p.get("id") == existing_product_id:
                                    matching_product = p
                                    print(f"✅ Found matching updated product by title and ID: '{expected_title}' (ID: {p.get('id')})", flush=True)
                                    break
                        
                        # If no match found, use the product with matching ID
                        if not matching_product:
                            for p in products_list:
                                if p.get("id") == existing_product_id:
                                    matching_product = p
                                    print(f"✅ Found updated product by ID: {existing_product_id}", flush=True)
                                    break
                        
                        if not matching_product:
                            error_msg = f"Failed to update product: Could not find product {existing_product_id} in response. Response contains {len(products_list)} products."
                            print(f"❌ {error_msg}", flush=True)
                            return {
                                "success": False,
                                "error": error_msg
                            }
                        
                        product = matching_product
                    else:
                        error_msg = f"Shopify API response contains 'products' but array is empty. Response: {result}"
                        print(f"❌ {error_msg}", flush=True)
                        return {
                            "success": False,
                            "error": error_msg
                        }
            
            if not product:
                error_msg = f"Shopify API response does not contain a product. Response keys: {list(result.keys()) if result else 'None'}. Response: {str(result)[:500]}"
                print(f"❌ {error_msg}", flush=True)
                return {
                    "success": False,
                    "error": error_msg
                }
            
            product_id = product.get("id")
            if not product_id:
                error_msg = f"Shopify API response does not contain a product ID. Product data: {product}"
                print(f"❌ {error_msg}", flush=True)
                return {
                    "success": False,
                    "error": error_msg
                }
            
            # Verify the product title matches what we sent (especially important for new products)
            product_title = product.get("title", "")
            if not existing_product_id and expected_title and product_title != expected_title:
                error_msg = f"Product title mismatch! Expected '{expected_title}' but got '{product_title}'. This may indicate the wrong product was returned."
                print(f"❌ {error_msg}", flush=True)
                print(f"⚠️ Product ID returned: {product_id}", flush=True)
                # Don't fail here - log the warning but continue, as this might be a Shopify API quirk
                print(f"⚠️ Continuing with returned product, but this may not be the product you intended to create.", flush=True)
            
            action = "updated" if existing_product_id else "created"
            print(f"✅ Step 1 Complete: Product {action} successfully!", flush=True)
            print(f"🆔 Product ID: {product_id}", flush=True)
            print(f"📝 Title: {product.get('title')}", flush=True)
            print(f"🔗 Handle: {product.get('handle')}", flush=True)
            print(f"🏷️ Tags: {tags}", flush=True)
            
            # Log the domain we'll use for subsequent API calls
            if actual_shopify_domain:
                print(f"🌐 Using Shopify domain: {actual_shopify_domain} for subsequent API calls", flush=True)
            else:
                print(f"🌐 Using default domain: {STORE_DOMAIN} for subsequent API calls", flush=True)
            
            # Step 2: Upload media files (images/videos) to the product FIRST
            media_files = product_data.get("media_files", [])
            shopify_media_ids = product_data.get("shopify_media_ids", [])
            total_media = len(media_files) + len(shopify_media_ids)
            
            
            
            if product_id:
                has_new_media = len(media_files) > 0
                is_updating = existing_product_id is not None
                
                # Determine SKU for filenames (needed for both creating and updating)
                def _extract_custom_sku_from_payload(data):
                    try:
                        mfs = data.get("metafields", []) or []
                        for mf in mfs:
                            if mf.get("namespace") == "custom" and mf.get("key") == "sku":
                                val = mf.get("value", "")
                                if isinstance(val, str) and val:
                                    # Handle JSON array string like ["ABC"]
                                    v = val.strip()
                                    if (v.startswith("[") and v.endswith("]")):
                                        try:
                                            parsed = json.loads(v)
                                            if isinstance(parsed, list) and parsed:
                                                return str(parsed[0])
                                        except Exception:
                                            return v
                                    return v
                                return str(val)
                    except Exception:
                        return ""
                    return ""

                payload_custom_sku = _extract_custom_sku_from_payload(product_data)
                provided_sku = product_data.get("sku") or ""

                fetched_custom_sku = ""
                if not payload_custom_sku and not provided_sku:
                    try:
                        # Fetch metafield custom.sku from API for the newly created product
                        # Use actual_shopify_domain if available to avoid redirects
                        mf_domain = actual_shopify_domain or STORE_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
                        url_mf = f"https://{mf_domain}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
                        headers_mf = {"X-Shopify-Access-Token": ACCESS_TOKEN}
                        r_mf = requests.get(url_mf, headers=headers_mf)
                        if r_mf.status_code == 200:
                            mfs = r_mf.json().get("metafields", [])
                            for mf in mfs:
                                if mf.get("namespace") == "custom" and mf.get("key") == "sku":
                                    fetched_custom_sku = str(mf.get("value", "")).strip()
                                    if fetched_custom_sku:
                                        break
                    except Exception:
                        fetched_custom_sku = ""

                created_variants = result.get("product", {}).get("variants", [])
                created_sku = (created_variants[0].get("sku") if created_variants and created_variants[0].get("sku") else "")
                sku_for_filename = payload_custom_sku or provided_sku or fetched_custom_sku or created_sku or "NOSKU"
                
                # Now handle media based on whether we're updating or creating
                if is_updating:
                    print(f"🔄 Step 2: Managing media for existing product - {len(media_files)} new files, {len(shopify_media_ids)} existing files to keep...")
                    
                    # Step 2a: Remove media not in the keep list
                    # Always call this - empty list means remove all images
                    print(f"🗑️ Step 2a: Removing unwanted media from product (keeping {len(shopify_media_ids) if shopify_media_ids else 0} images)...")
                    manage_results = manage_product_media(product_id, shopify_media_ids or [])
                    if manage_results["success"]:
                        print(f"✅ Step 2a Complete: Removed {manage_results['removed_count']} unwanted media items")
                    else:
                        print(f"⚠️ Step 2a Partial: Some media removal failed: {manage_results['errors']}")
                    
                    # Step 2b: Upload ONLY new media files (don't try to re-attach existing ones)
                    if has_new_media:
                        product_title = product_data.get("title", "")
                        print(f"📤 Step 2b: Uploading {len(media_files)} new media files...")
                        
                        # When updating, only upload new files (don't pass shopify_media_ids to avoid re-attachment attempts)
                        media_results = upload_media_to_product(
                            product_id,
                            media_files,
                            None,  # Don't try to re-attach existing media
                            product_title,
                            product_sku=sku_for_filename,
                            shopify_domain=actual_shopify_domain
                        )
                        if media_results["success"]:
                            print(f"✅ Step 2b Complete: New media files uploaded successfully!")
                        else:
                            print(f"⚠️ Step 2b Partial: Some media files failed to upload: {media_results['errors']}")
                    
                    # Step 2c: Reorder all media according to media_order
                    # Add a small delay to ensure Shopify has processed the uploads
                    import time
                    if has_new_media:
                        print("⏳ Waiting 2 seconds for Shopify to process new uploads...")
                        time.sleep(2)
                    
                    media_order = product_data.get("media_order", [])
                    if media_order:
                        print(f"🔄 Step 2c: Reordering media according to media_order ({len(media_order)} items)...")
                        reorder_results = reorder_product_media_by_order(product_id, media_order, shopify_media_ids, shopify_domain=actual_shopify_domain)
                        if reorder_results["success"]:
                            print(f"✅ Step 2c Complete: Media reordered successfully!")
                        else:
                            print(f"⚠️ Step 2c Partial: Some media reordering failed: {reorder_results['errors']}")
                    elif shopify_media_ids:
                        # Fallback to old method if no media_order provided
                        print(f"🔄 Step 2c: Reordering {len(shopify_media_ids)} existing media items (fallback method)...")
                        reorder_results = reorder_product_media(product_id, shopify_media_ids)
                        if reorder_results["success"]:
                            print(f"✅ Step 2c Complete: Media reordered successfully!")
                        else:
                            print(f"⚠️ Step 2c Partial: Some media reordering failed: {reorder_results['errors']}")
                    
                    print(f"✅ Step 2 Complete: Media management finished for existing product!")
                
                elif has_new_media or total_media > 0:
                    # Creating new product - upload all media (same flow as updating existing product)
                    print(f"🔄 Step 2: Uploading {len(media_files)} new files and attaching {len(shopify_media_ids)} existing files for new product...")
                    product_title = product_data.get("title", "")
                    
                    # Step 2a: Upload/attach all media (both new and existing)
                    media_results = upload_media_to_product(
                        product_id,
                        media_files,
                        shopify_media_ids,
                        product_title,
                        product_sku=sku_for_filename,
                        shopify_domain=actual_shopify_domain
                    )
                    if media_results["success"]:
                        print(f"✅ Step 2a Complete: All media files uploaded/attached successfully!")
                    else:
                        print(f"⚠️ Step 2a Partial: Some media files failed to process: {media_results['errors']}")
                    
                    # Step 2b: Reorder all media according to media_order (same as existing product flow)
                    # Add a delay to ensure Shopify has processed the uploads
                    import time
                    if has_new_media:
                        print("⏳ Waiting 2 seconds for Shopify to process new uploads...")
                        time.sleep(2)
                    
                    media_order = product_data.get("media_order", [])
                    print(f"🔍 DEBUG: media_order received for new product: {media_order}")
                    print(f"🔍 DEBUG: media_order type: {type(media_order)}, length: {len(media_order) if isinstance(media_order, list) else 'N/A'}")
                    if media_order:
                        print(f"🔄 Step 2b: Reordering media according to media_order ({len(media_order)} items)...")
                        debug_items = [f"{item.get('type', '?')} at pos {item.get('position', '?')}" for item in media_order]
                        print(f"🔍 DEBUG: media_order items: {debug_items}")
                        # For new products, pass shopify_media_ids to help identify existing vs new images
                        # The reorder function will fetch ALL images from the product and match them to media_order
                        reorder_results = reorder_product_media_by_order(product_id, media_order, shopify_media_ids, shopify_domain=actual_shopify_domain)
                        if reorder_results["success"]:
                            print(f"✅ Step 2b Complete: Media reordered successfully!")
                        else:
                            print(f"⚠️ Step 2b Partial: Some media reordering failed: {reorder_results['errors']}")
                    else:
                        print(f"⚠️ WARNING: No media_order provided for new product! Cannot set image order.")
                        print(f"🔍 DEBUG: product_data keys: {list(product_data.keys())}")
                        if shopify_media_ids:
                            # Fallback to old method if no media_order provided
                            print(f"🔄 Step 2b: Reordering {len(shopify_media_ids)} existing media items (fallback method)...")
                            reorder_results = reorder_product_media(product_id, shopify_media_ids)
                            if reorder_results["success"]:
                                print(f"✅ Step 2b Complete: Media reordered successfully!")
                            else:
                                print(f"⚠️ Step 2b Partial: Some media reordering failed: {reorder_results['errors']}")
                    
                    print(f"✅ Step 2 Complete: All media files processed successfully!")
                else:
                    print(f"⏭️ Step 2 Skipped: No media to manage")
            
            # Step 3: Create metafields if provided
            metafields = product_data.get("metafields") or []
            if not isinstance(metafields, list):
                metafields = []
            
            # Build categories and subcategories from top-level (form) or metafields
            categories = []
            subcategories = []
            if product_data.get("categories"):
                categories = list(product_data["categories"]) if isinstance(product_data["categories"], (list, tuple)) else [product_data["categories"]]
            elif product_data.get("category"):
                categories = [str(product_data["category"]).strip()]
            if product_data.get("subcategories"):
                sc = product_data["subcategories"]
                if isinstance(sc, (list, tuple)):
                    subcategories = list(sc)
                elif isinstance(sc, str) and sc.strip().startswith("["):
                    try:
                        subcategories = json.loads(sc)
                    except json.JSONDecodeError:
                        subcategories = [str(sc).strip()]
                else:
                    subcategories = [str(sc).strip()]
            elif product_data.get("subcategory"):
                subcategories = [str(product_data["subcategory"]).strip()]
            
            # Extract from metafields if not from top-level (merge from ALL matching metafields)
            cats_from_mf = []
            subcats_from_mf = []
            for mf in metafields:
                if mf.get("namespace") != "custom":
                    continue
                val = mf.get("value")
                if val is None:
                    continue
                try:
                    if isinstance(val, list):
                        arr = [str(v).strip() for v in val if v]
                    elif isinstance(val, str):
                        s = val.strip()
                        if s.startswith("["):
                            arr = [str(v).strip() for v in json.loads(s) if v]
                        elif s:
                            arr = [s]
                        else:
                            continue
                    else:
                        arr = [str(val).strip()]
                except (json.JSONDecodeError, TypeError):
                    arr = [str(val).strip()] if val else []
                if not arr:
                    continue
                if mf.get("key") == "custom_category":
                    cats_from_mf.extend(arr)
                elif (mf.get("key") or "").startswith("subcategory"):
                    subcats_from_mf.extend(arr)
            if not categories and cats_from_mf:
                categories = list(dict.fromkeys(cats_from_mf))
            if not subcategories and subcats_from_mf:
                subcategories = list(dict.fromkeys(subcats_from_mf))
            # Merge metafield subcategories into top-level so overflow routing always has full list
            if subcats_from_mf and subcategories is not None:
                subcategories = list(dict.fromkeys(list(subcategories) + list(subcats_from_mf)))
            
            # Remove category from metafields (we add it)
            # KEEP subcategory metafields - frontend sends multiple selections per key (subcategory, subcategory_2, etc.)
            # Each overflow has no duplicates, so pass them through as-is
            metafields = [
                mf for mf in metafields
                if not (mf.get("namespace") == "custom" and mf.get("key") == "custom_category")
            ]
            
            # Add category metafield if we have it
            if categories:
                metafields.append({
                    "namespace": "custom",
                    "key": "custom_category",
                    "value": json.dumps(categories),
                    "type": "list.single_line_text_field"
                })
            
            # Ensure subcategory metafields are saved - ALWAYS merge from top-level subcategories
            # (Frontend sends subcategories merged; we must route each to correct key: subcategory, subcategory_2, etc.)
            # IMPORTANT: Shopify enforces choices per metafield - subcategory has first 128, subcategory_2 has next 128.
            if subcategories:
                try:
                    from .categories import get_subcategory_metafield_key
                    by_key = {}
                    for sc in subcategories:
                        s = str(sc).strip()
                        if s:
                            key = get_subcategory_metafield_key(s)
                            by_key.setdefault(key, []).append(s)
                            print(f"📂 Routed subcategory '{s}' -> {key}", flush=True)
                    # Remove existing subcategory* metafields - we replace with routed values
                    metafields = [mf for mf in metafields if not (mf.get("namespace") == "custom" and (mf.get("key") or "").startswith("subcategory"))]
                    for mf_key, vals in by_key.items():
                        if vals:
                            metafields.append({
                                "namespace": "custom",
                                "key": mf_key,
                                "value": json.dumps(vals),
                                "type": "list.single_line_text_field"
                            })
                            print(f"📂 Subcategory metafield {mf_key}: {vals}", flush=True)
                except Exception as e:
                    print(f"⚠️ Failed to route subcategories: {e}", flush=True)
            
            # Debug: log subcategory metafields being sent
            subcat_mfs = [mf for mf in metafields if mf.get("namespace") == "custom" and (mf.get("key") or "").startswith("subcategory")]
            if subcat_mfs:
                print(f"📂 Subcategory metafields to save: {[(m.get('key'), m.get('value')) for m in subcat_mfs]}", flush=True)
            elif subcategories:
                print(f"⚠️ Subcategories from form but no subcategory metafields in list: {subcategories}", flush=True)
            
            # Add colour options metafield if provided
            product_colours_raw = product_data.get("product_colours") or ""
            product_colours = str(product_colours_raw).strip() if product_colours_raw else ""
            if product_colours:
                print(f"🎨 Colours provided: {product_colours}", flush=True)
                metafields.append({
                    "namespace": "custom",
                    "key": "product_colours",
                    "value": product_colours,  # Store comma-separated colours
                    "type": "single_line_text_field"
                })
                
                # Create default pricing metafields for colour variants if they don't exist
                # This allows Price Bandit to create colour variants even without explicit pricing
                has_trade_pricing = any(mf.get("key") == "pricejsontr" for mf in metafields)
                has_endc_pricing = any(mf.get("key") == "pricejsoner" for mf in metafields)
                
                if not has_trade_pricing:
                    print(f"➕ Adding default trade pricing for colour variants", flush=True)
                    metafields.append({
                        "namespace": "custom",
                        "key": "pricejsontr",
                        "value": '[{"min": 0, "max": 100, "price": 0.00}]',  # Default pricing band
                        "type": "single_line_text_field"
                    })
                
                if not has_endc_pricing:
                    print(f"➕ Adding default end customer pricing for colour variants", flush=True)
                    metafields.append({
                        "namespace": "custom",
                        "key": "pricejsoner", 
                        "value": '[{"min": 0, "max": 100, "price": 0.00}]',  # Default pricing band
                        "type": "single_line_text_field"
                    })
            
            if metafields and product_id:
                print(f"🔄 Step 3: Creating {len(metafields)} metafields...")
                # Use the actual Shopify domain if we extracted it from redirects
                metafield_results = create_metafields(product_id, metafields, shopify_domain=actual_shopify_domain)
                if metafield_results["success"]:
                    print(f"✅ Step 3 Complete: All metafields created successfully!")
                    # Small delay to ensure metafields are fully saved before Price Bandit reads them
                    import time
                    time.sleep(0.5)
                else:
                    print(f"⚠️ Step 3 Partial: Some metafields failed to create: {metafield_results['errors']}")
            else:
                print(f"⏭️ Step 3 Skipped: No metafields to create")
            
            # Step 4: Run Price Bandit script to create variants (after media and metafields are created)
            # For new products, add extra delay to ensure images are fully indexed
            if not existing_product_id:
                print("⏳ Waiting 2 seconds before Price Bandit to ensure all images are indexed...", flush=True)
                import time
                time.sleep(2.0)
            
            print(f"🔄 Step 4: Running Price Bandit script to create variants...")
            
            # Import Price Bandit functions first
            try:
                import sys
                import os
                # Add the scripts directory to the path
                scripts_dir = os.path.join(os.path.dirname(__file__), '..')
                if scripts_dir not in sys.path:
                    sys.path.append(scripts_dir)
                from Price_Bandit import process_product
                import Price_Bandit
                
                # Temporarily update STORE_DOMAIN in both config and Price_Bandit if we have the actual Shopify domain
                # This ensures Price Bandit uses the correct domain to avoid redirects
                original_store_domain = None
                if actual_shopify_domain:
                    try:
                        import config
                        original_store_domain = config.STORE_DOMAIN
                        config.STORE_DOMAIN = actual_shopify_domain
                        # Also update Price_Bandit's imported STORE_DOMAIN directly
                        Price_Bandit.STORE_DOMAIN = actual_shopify_domain
                    except Exception as e:
                        print(f"⚠️ Could not update STORE_DOMAIN: {e}", flush=True)
                        original_store_domain = None
                
                print(f"🔍 Price Bandit imported successfully")
                
                # Create a product object that Price Bandit expects
                product_for_bandit = {
                    "id": product_id,
                    "title": product.get('title', 'Unknown Product')
                }
                
                # Pass colour_images if provided
                colour_images = product_data.get("colour_images")
                print(f"🔍 Received colour_images from frontend: {colour_images}, type: {type(colour_images)}", flush=True)
                if colour_images:
                    # If it's already a dict from JSON parsing in app.py, use it directly
                    # Otherwise convert from string
                    if isinstance(colour_images, str):
                        import json
                        try:
                            colour_images = json.loads(colour_images)
                            print(f"🔧 Parsed colour_images from string: {colour_images}", flush=True)
                        except Exception as e:
                            print(f"⚠️ Failed to parse colour_images: {e}", flush=True)
                            colour_images = None
                    
                    if colour_images:
                        # Store as a custom attribute to pass to Price Bandit
                        product_for_bandit["_colour_images"] = colour_images
                        print(f"🔍 Storing colour_images in product_for_bandit: {product_for_bandit.get('_colour_images')}", flush=True)
                
                print(f"🔍 Running Price Bandit for product ID: {product_id}")
                
                # Run Price Bandit's process_product function
                price_bandit_success = process_product(product_for_bandit)
                if price_bandit_success:
                    print(f"✅ Step 4 Complete: Price Bandit script executed successfully!")
                else:
                    print(f"❌ Step 4 Failed: Price Bandit script failed to create variants!")
                
            except ImportError as e:
                print(f"❌ Step 4 Failed: Could not import Price Bandit: {str(e)}")
            except Exception as e:
                print(f"❌ Step 4 Failed: Price Bandit execution error: {str(e)}")
                import traceback
                traceback.print_exc()
            finally:
                # Restore original STORE_DOMAIN if we changed it
                if 'original_store_domain' in locals() and original_store_domain is not None:
                    try:
                        import config
                        config.STORE_DOMAIN = original_store_domain
                        # Also restore Price_Bandit's STORE_DOMAIN
                        if 'Price_Bandit' in locals():
                            Price_Bandit.STORE_DOMAIN = original_store_domain
                    except Exception as e:
                        print(f"⚠️ Could not restore STORE_DOMAIN: {e}", flush=True)
            
            # Step 5: Update taxable field on variants if needed (Price Bandit sets taxable=True by default)
            if not taxable:  # If user selected "No" for charge VAT
                print(f"🔄 Step 5: Updating taxable field to False on all variants...")
                taxable_updated = update_product_taxable(product_id, False)
                if taxable_updated:
                    print(f"✅ Step 5 Complete: Taxable field updated to False on all variants")
                else:
                    print(f"❌ Step 5 Failed: Could not update taxable field")
            else:
                print(f"✅ Step 5 Complete: Variants created with taxable=True (Price Bandit default)")
            
            # Verify the product actually exists by fetching it (with timeout to avoid worker hang)
            verify_domain = actual_shopify_domain or STORE_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
            verify_url = f"https://{verify_domain}/admin/api/{API_VERSION}/products/{product_id}.json"
            try:
                verify_response = requests.get(verify_url, headers=headers, timeout=25)
                if verify_response.status_code == 200:
                    verified_product = verify_response.json().get("product", {})
                    if verified_product.get("id") == product_id:
                        print(f"✅ Verification: Product {product_id} confirmed to exist in Shopify", flush=True)
                    else:
                        print(f"⚠️ Warning: Product verification returned different product", flush=True)
                else:
                    print(f"⚠️ Warning: Could not verify product existence (status: {verify_response.status_code})", flush=True)
            except (requests.Timeout, requests.ConnectionError) as e:
                print(f"⚠️ Warning: Verification request skipped ({type(e).__name__}) - product was still created", flush=True)
            
            print(f"🎉 Product {action} process completed!")
            # Use actual_shopify_domain for the final URL if available
            final_domain = actual_shopify_domain or STORE_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
            print(f"🌐 URL: https://{final_domain}/admin/products/{product_id}")

            return {
                "success": True,
                "product": product,
                "message": f"Product '{product.get('title')}' {action} successfully"
            }
        else:
            error_msg = f"Failed to {method.lower()} product: {response.status_code} - {response.text}"
            print(f"❌ {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }
            
    except Exception as e:
        error_msg = f"Error creating product: {str(e)}"
        print(f"💥 {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }

def get_metafield_choices(namespace_key):
    """
    Get preset choices for a specific metafield from the categories file
    
    Args:
        namespace_key (str): The metafield namespace and key (e.g., "custom.custom_category")
    
    Returns:
        list: List of preset choices for the metafield
    """
    try:
        # Import the categories module
        from .categories import get_metafield_choices as get_categories_choices
        
        # Parse namespace and key from the input
        if '.' in namespace_key:
            namespace, key = namespace_key.split('.', 1)
        else:
            namespace = namespace_key
            key = ""
        
        # Get choices from the categories file
        choices = get_categories_choices(key)
        if choices:
            print(f"Found {len(choices)} preset choices for {namespace_key}: {choices}")
            return choices
        else:
            print(f"No preset choices found for {namespace_key}")
            return []
            
    except Exception as e:
        print(f"Error fetching metafield choices for {namespace_key}: {str(e)}")
        return []

def get_existing_metafield_values(namespace, key):
    """Fallback function to get existing metafield values"""
    try:
        graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
        headers = {
            'X-Shopify-Access-Token': ACCESS_TOKEN,
            'Content-Type': 'application/json',
        }
        
        query = """
        query getMetafieldValues($namespace: String!) {
            products(first: 250) {
                edges {
                    node {
                        metafields(first: 50, namespace: $namespace) {
                            edges {
                                node {
                                    key
                                    value
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        response = requests.post(graphql_url, headers=headers, json={
            'query': query,
            'variables': {"namespace": namespace}
        })
        
        if response.status_code == 200:
            data = response.json()
            products = data.get('data', {}).get('products', {}).get('edges', [])
            
            if products:
                unique_values = set()
                for product_edge in products:
                    product = product_edge['node']
                    metafields = product.get('metafields', {}).get('edges', [])
                    for metafield_edge in metafields:
                        metafield = metafield_edge['node']
                        metafield_key = metafield.get('key', '')
                        if metafield_key == key:
                            value = metafield.get('value', '')
                            if value and value.strip():
                                try:
                                    import json
                                    parsed_value = json.loads(value.strip())
                                    if isinstance(parsed_value, list) and len(parsed_value) > 0:
                                        unique_values.add(parsed_value[0])
                                    else:
                                        unique_values.add(value.strip())
                                except (json.JSONDecodeError, IndexError):
                                    unique_values.add(value.strip())
                
                choices = sorted(list(unique_values))
                print(f"Fallback: Found {len(choices)} existing values for {namespace}.{key}: {choices}")
                return choices
        
        return []
    except Exception as e:
        print(f"Error in fallback function: {str(e)}")
        return []

def get_product_templates():
    """
    Get predefined product templates for common product types
    
    Returns:
        dict: Available product templates
    """
    templates = {
        "simple_product": {
            "name": "Simple Product",
            "description": "A basic product with one variant",
            "template": {
                "title": "New Product",
                "description": "Product description",
                "vendor": "",
                "product_type": "",
                "tags": "",
                "status": "draft",
                "price": "0.00",
                "sku": "",
                "inventory_quantity": 0,
                "variants": []
            }
        },
        "size_variants": {
            "name": "Product with Size Variants",
            "description": "Product with different sizes (S, M, L, XL)",
            "template": {
                "title": "New Product with Sizes",
                "description": "Product description",
                "vendor": "",
                "product_type": "",
                "tags": "",
                "status": "draft",
                "options": [
                    {
                        "name": "Size",
                        "values": ["S", "M", "L", "XL"]
                    }
                ],
                "variants": [
                    {"option1": "S", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "M", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "L", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "XL", "price": "0.00", "sku": "", "inventory_quantity": 0}
                ]
            }
        },
        "color_size_variants": {
            "name": "Product with Color & Size",
            "description": "Product with color and size variants",
            "template": {
                "title": "New Product with Colors & Sizes",
                "description": "Product description",
                "vendor": "",
                "product_type": "",
                "tags": "",
                "status": "draft",
                "options": [
                    {
                        "name": "Color",
                        "values": ["Red", "Blue", "Green"]
                    },
                    {
                        "name": "Size",
                        "values": ["S", "M", "L"]
                    }
                ],
                "variants": [
                    {"option1": "Red", "option2": "S", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Red", "option2": "M", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Red", "option2": "L", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Blue", "option2": "S", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Blue", "option2": "M", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Blue", "option2": "L", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Green", "option2": "S", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Green", "option2": "M", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Green", "option2": "L", "price": "0.00", "sku": "", "inventory_quantity": 0}
                ]
            }
        }
    }
    
    return templates

def validate_product_data(product_data):
    """
    Validate product data before creation
    
    Args:
        product_data (dict): Product information to validate
    
    Returns:
        dict: Validation result with success status and any errors
    """
    errors = []
    
    # Required fields
    if not product_data.get("title", "").strip():
        errors.append("Product title is required")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def main():
    """
    Main function for command line usage
    """
    print("🛍️  Product Editor/Creator - Shopify Product Tool")
    print("=" * 50)
    
    # Example usage
    if len(sys.argv) > 1:
        if sys.argv[1] == "--templates":
            templates = get_product_templates()
            print("\n📋 Available Product Templates:")
            for key, template in templates.items():
                print(f"\n🔹 {template['name']}")
                print(f"   {template['description']}")
            return
    
    # Interactive mode
    print("\n📝 Enter product details:")
    
    product_data = {
        "title": input("Product Title: ").strip(),
        "description": input("Description (optional): ").strip(),
        "vendor": input("Vendor (optional): ").strip(),
        "product_type": input("Product Type (optional): ").strip(),
        "tags": input("Tags (comma-separated, optional): ").strip(),
        "status": input("Status (draft/active, default: draft): ").strip() or "draft",
        "price": input("Price (default: 0.00): ").strip() or "0.00",
        "sku": input("SKU (optional): ").strip(),
        "inventory_quantity": input("Inventory Quantity (default: 0): ").strip() or "0"
    }
    
    # Validate the data
    validation = validate_product_data(product_data)
    if not validation["valid"]:
        print("\n❌ Validation Errors:")
        for error in validation["errors"]:
            print(f"   • {error}")
        return
    
    # Create the product
    result = create_product(product_data)
    
    if result["success"]:
        print(f"\n✅ {result['message']}")
    else:
        print(f"\n❌ {result['error']}")

if __name__ == "__main__":
    main()
