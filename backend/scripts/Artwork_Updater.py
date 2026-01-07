#!/usr/bin/env python3
"""
Artwork Updater - Clean, simple tool for managing product artwork
"""

import os
import sys
import requests
import json
from datetime import datetime

# UTF-8 encoding handled at subprocess level in backend

# Add the parent directory to the path so we can import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION
except ImportError:
    print("ERROR: Could not import config. Make sure config.py exists in the backend directory.")
    sys.exit(1)

def make_graphql_request(query, variables=None, shopify_domain=None):
    """
    Make a GraphQL request to Shopify with redirect handling
    
    Args:
        query (str): GraphQL query string
        variables (dict): GraphQL variables
        shopify_domain (str, optional): The actual Shopify domain to use (to avoid redirects)
    
    Returns:
        requests.Response: The response object
    """
    # Use provided domain or fall back to STORE_DOMAIN
    domain = shopify_domain or STORE_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
    url = f"https://{domain}/admin/api/{API_VERSION}/graphql.json"
    
    headers = {
        'X-Shopify-Access-Token': ACCESS_TOKEN,
        'Content-Type': 'application/json',
    }
    
    payload = {'query': query}
    if variables:
        payload['variables'] = variables
    
    # Handle redirects for GraphQL requests
    response = requests.post(url, json=payload, headers=headers, allow_redirects=False)
    
    # If redirected, follow it silently
    if response.status_code in [301, 302, 303, 307, 308]:
        redirect_url = response.headers.get('Location', url)
        if redirect_url.startswith('/'):
            from urllib.parse import urlparse
            parsed = urlparse(url)
            redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
        response = requests.post(redirect_url, json=payload, headers=headers, allow_redirects=True)
    
    return response

def fetch_files_with_graphql():
    """
    Fetch all files from Shopify Admin > Content > Files using GraphQL Admin API
    """
    try:
        # GraphQL query to get files from Admin > Content > Files
        # Using the correct query structure for Shopify files
        query = """
        query getFiles($first: Int!) {
            files(first: $first) {
                edges {
                    node {
                        id
                        alt
                        createdAt
                        fileStatus
                        ... on GenericFile {
                            url
                            mimeType
                            originalFileSize
                        }
                        ... on MediaImage {
                            image {
                                url
                                width
                                height
                            }
                            mimeType
                        }
                    }
                }
                pageInfo {
                    hasNextPage
                    endCursor
                }
            }
        }
        """
        
        variables = {
            "first": 250
        }
        
        # Use the helper function to handle redirects
        response = make_graphql_request(query, variables)
        
        if response.status_code == 200:
            data = response.json()
            
            # Check for GraphQL errors first
            if 'errors' in data:
                print(f"❌ GraphQL errors: {json.dumps(data['errors'], indent=2)}")
                return []
            
            if 'data' in data and 'files' in data['data']:
                files_data = data['data']['files']
                
                if 'edges' in files_data:
                    files = []
                    for edge in files_data['edges']:
                        file_info = edge['node']
                        
                        # Extract basic file information
                        original_global_id = file_info.get('id', '')
                        file_id = original_global_id.split('/')[-1] if '/' in original_global_id else original_global_id
                        alt_text = file_info.get('alt', '')
                        created_at = file_info.get('createdAt', '')
                        file_status = file_info.get('fileStatus', '')
                        
                        # Initialize file data
                        formatted_file = {
                            'id': file_id,
                            'original_global_id': original_global_id,
                            'filename': alt_text or 'Untitled',  # Use alt text as the display filename
                            'content_type': 'application/octet-stream',
                            'size': 0,
                            'created_at': created_at,
                            'updated_at': created_at,
                            'alt': alt_text,
                            'url': '',
                            'preview_url': None,
                            'file_status': file_status,
                            'original_filename': alt_text  # Store original filename for reference
                        }
                        
                        # Handle different file types
                        if 'image' in file_info and file_info['image']:
                            # MediaImage type
                            formatted_file['url'] = file_info['image'].get('url', '')
                            formatted_file['preview_url'] = file_info['image'].get('url', '')
                            formatted_file['content_type'] = file_info.get('mimeType', 'image/jpeg')
                            # Calculate approximate size from width * height (no direct fileSize field)
                            width = file_info['image'].get('width', 0)
                            height = file_info['image'].get('height', 0)
                            formatted_file['size'] = width * height if width and height else 0
                            
                            # Handle filename display logic
                            if not formatted_file['filename'] or formatted_file['filename'] == 'Untitled':
                                # If alt text is blank, try to extract from URL as fallback
                                url = formatted_file['url']
                                if url:
                                    url_parts = url.split('/')
                                    if len(url_parts) > 0:
                                        filename_part = url_parts[-1]
                                        formatted_file['filename'] = filename_part.split('?')[0] if '?' in filename_part else filename_part
                                else:
                                    # If no URL, use a generic name
                                    formatted_file['filename'] = 'Uploaded File'
                        
                        elif 'url' in file_info:
                            # GenericFile type
                            formatted_file['url'] = file_info.get('url', '')
                            formatted_file['content_type'] = file_info.get('mimeType', 'application/octet-stream')
                            formatted_file['size'] = file_info.get('originalFileSize', 0)
                            
                            # Handle filename display logic
                            if not formatted_file['filename'] or formatted_file['filename'] == 'Untitled':
                                # If alt text is blank, try to extract from URL as fallback
                                url = formatted_file['url']
                                if url:
                                    url_parts = url.split('/')
                                    if len(url_parts) > 0:
                                        filename_part = url_parts[-1]
                                        formatted_file['filename'] = filename_part.split('?')[0] if '?' in filename_part else filename_part
                                else:
                                    # If no URL, use a generic name
                                    formatted_file['filename'] = 'Uploaded File'
                        
                        files.append(formatted_file)
                    
                    return files
                else:
                    return []
            else:
                print(f"⚠️ GraphQL response missing 'data.files' field. Response: {response.text[:500]}", flush=True)
                return []
        else:
            print(f"❌ GraphQL request failed with status {response.status_code}. Response: {response.text[:500]}", flush=True)
            return []
            
    except Exception as e:
        print(f"❌ Error fetching files from Shopify: {str(e)}", flush=True)
        import traceback
        traceback.print_exc()
        return []

def upload_file_to_shopify(file_path, alt_text=""):
    """
    Upload a file to Shopify using direct REST API - bypassing staged upload issues
    """
    try:
        # Use the original filename from alt_text parameter, not the temporary file path
        filename = alt_text or os.path.basename(file_path)
        
        print(f"[UPLOAD] Attempting to upload {filename} to Shopify using direct REST API")
        
        # Use the correct 3-step staged upload process from Shopify Community
        print(f"[UPLOAD] Using Shopify's official 3-step staged upload process...")
        
        try:
            # Step 1: Generate staged upload URL
            print(f"📋 Step 1: Generating staged upload URL...")
            
            graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
        
            mutation = """
            mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
                stagedUploadsCreate(input: $input) {
                    stagedTargets {
                        url
                        resourceUrl
                        parameters {
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
        
            variables = {
                "input": [{
                    "filename": filename,  # Use original filename here
                    "mimeType": "application/pdf",
                    "resource": "FILE"
                }]
            }
            
            # Use the helper function to handle redirects
            response = make_graphql_request(mutation, variables)
            
            if response.status_code != 200:
                print(f"❌ Step 1 failed: {response.status_code}")
                return False
                
            data = response.json()
            
            if 'errors' in data:
                print(f"❌ GraphQL errors: {data['errors']}")
                return False
                
            if 'data' not in data or 'stagedUploadsCreate' not in data['data']:
                print(f"❌ No staged upload data")
                return False
                
            staged_upload = data['data']['stagedUploadsCreate']
            
            if staged_upload.get('userErrors'):
                print(f"❌ User errors: {staged_upload['userErrors']}")
                return False
                
            if not staged_upload.get('stagedTargets'):
                print(f"❌ No staged targets")
                return False
                
            staged_target = staged_upload['stagedTargets'][0]
            
            print(f"[UPLOAD] Step 1 complete: Staged upload URL generated")
            
            # Step 2: Upload file to Google Cloud Storage
            print(f"[UPLOAD] Step 2: Uploading file to Google Cloud Storage...")
            
            with open(file_path, 'rb') as f:
                # Build the form data with all required parameters
                form_data = {}
                for param in staged_target['parameters']:
                    form_data[param['name']] = param['value']
                
                # Method 1: PUT request with file content directly
                try:
                    f.seek(0)  # Reset file pointer
                    file_content = f.read()
                    
                    upload_response = requests.put(staged_target['url'], data=file_content, headers={'Content-Type': 'application/pdf'})
                    
                    if upload_response.status_code in [200, 201, 204]:
                        print(f"[UPLOAD] Step 2 complete: File uploaded to Google Cloud Storage")
                    else:
                        raise Exception("Upload failed")
                        
                except Exception as method1_error:
                    # Method 2: POST with multipart form
                    try:
                        f.seek(0)  # Reset file pointer
                        files = {'file': (filename, f, 'application/pdf')}
                        
                        upload_response = requests.post(staged_target['url'], data=form_data, files=files)
                        
                        if upload_response.status_code in [200, 201, 204]:
                            print(f"[UPLOAD] Step 2 complete: File uploaded to Google Cloud Storage")
                        else:
                            raise Exception("Upload failed")
                            
                    except Exception as method2_error:
                        # Method 3: POST with just the file content
                        try:
                            f.seek(0)  # Reset file pointer
                            file_content = f.read()
                            
                            upload_response = requests.post(staged_target['url'], data=file_content, headers={'Content-Type': 'application/pdf'})
                            
                            if upload_response.status_code in [200, 201, 204]:
                                print(f"[UPLOAD] Step 2 complete: File uploaded to Google Cloud Storage")
                            else:
                                print(f"[ERROR] Upload failed: {upload_response.status_code}")
                                return False
                                
                        except Exception as method3_error:
                            print(f"[ERROR] All upload methods failed")
                            return False
            
            # Step 3: Create file record using fileCreate
            print(f"[UPLOAD] Step 3: Creating file record...")
            
            file_create_mutation = """
            mutation fileCreate($files: [FileCreateInput!]!) {
                fileCreate(files: $files) {
                    files {
                        id
                        alt
                        createdAt
                        fileStatus
                        ... on MediaImage {
                            image {
                                url
                            }
                        }
                        ... on GenericFile {
                            url
                        }
                    }
                    userErrors {
                        field
                        message
                    }
                }
            }
            """
            
            file_variables = {
                "files": [{
                    "originalSource": staged_target['url'].split('?')[0],  # Remove query params
                    "alt": filename  # Use original filename as alt text
                }]
            }
            
            
            # Use the helper function to handle redirects
            file_response = make_graphql_request(file_create_mutation, file_variables)
            
            if file_response.status_code != 200:
                print(f"❌ Step 3 failed: {file_response.status_code}")
                return False
                
            file_data = file_response.json()
            
            if 'errors' in file_data:
                print(f"❌ File creation errors: {file_data['errors']}")
                return False
                
            if 'data' in file_data and file_data['data']['fileCreate']['userErrors']:
                print(f"❌ File creation user errors: {file_data['data']['fileCreate']['userErrors']}")
                return False
                
            print(f"[UPLOAD] Step 3 complete: File record created successfully")
            print(f"[UPLOAD] PDF uploaded successfully: {filename}")
            
            # Step 4: Set alt text to blank after successful upload
            print(f"[UPLOAD] Step 4: Setting alt text to blank...")
            
            try:
                # Wait for Shopify to process the file and become READY
                import time
                max_attempts = 10
                attempt = 0
                target_file = None
                
                while attempt < max_attempts and target_file is None:
                    attempt += 1
                    
                    # Fetch the updated file list to find our new file
                    files_query = """
                    query {
                        files(first: 250) {
                            edges {
                                node {
                                    id
                                    alt
                                    createdAt
                                    fileStatus
                                    ... on MediaImage {
                                        image {
                                            url
                                        }
                                    }
                                    ... on GenericFile {
                                        url
                                    }
                                }
                            }
                        }
                    }
                    """
                    
                    # Use the helper function to handle redirects
                    files_response = make_graphql_request(files_query)
                    
                    if files_response.status_code == 200:
                        files_data = files_response.json()
                        
                        if 'data' in files_data and 'files' in files_data['data']:
                            for edge in files_data['data']['files']['edges']:
                                file_node = edge['node']
                                file_alt = file_node.get('alt', '')
                                file_status = file_node.get('fileStatus')
                                
                                # Look for file with matching alt text and READY status
                                if file_alt == filename and file_status == 'READY':
                                    target_file = file_node
                                    break
                    
                    if target_file is None:
                        time.sleep(3)
                
                if target_file:
                    # Update the file to set alt text to blank
                    update_mutation = """
                    mutation fileUpdate($files: [FileUpdateInput!]!) {
                        fileUpdate(files: $files) {
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
        
                    update_variables = {
            "files": [{
                            "id": target_file['id'],
                            "alt": ""  # Set alt text to blank as requested
                        }]
                    }
                    
                    # Use the helper function to handle redirects
                    update_response = make_graphql_request(update_mutation, update_variables)
                    
                    if update_response.status_code == 200:
                        update_data = update_response.json()
                        if 'errors' not in update_data and 'data' in update_data:
                            print(f"[UPLOAD] Step 4 complete: Alt text set to blank")
                        else:
                            print(f"[WARNING] Update failed: {update_data}")
                    else:
                        print(f"[WARNING] Update request failed: {update_response.status_code}")
                else:
                    print(f"[WARNING] Could not find uploaded file after {max_attempts} attempts")
                    
            except Exception as cleanup_error:
                print(f"[WARNING] Post-upload update error (non-critical): {cleanup_error}")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Error in staged upload process: {str(e)}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Error in upload_file_to_shopify: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def update_products_to_specific_file(target_filename, column):
    """
    Update all products that have any Artwork_Guidelines file to use the specified target file
    """
    try:
        print(f"[PRODUCT UPDATE] Starting update to specific file: {target_filename}")
        print(f"[PRODUCT UPDATE] Column: {column}")
        
        # Fetch all products from Shopify
        products = fetch_all_products()
        
        if not products:
            return {
                'updatedCount': 0,
                'totalCount': 0,
                'message': 'No products found'
            }
        
        updated_count = 0
        total_count = len(products)
        
        # Get the target file ID
        target_file_id = get_file_id_from_filename(target_filename)
        if not target_file_id:
            return {
                'updatedCount': 0,
                'totalCount': total_count,
                'error': f'Could not find file: {target_filename}'
            }
        
        # Convert to Global ID format
        target_file_global_id = f"gid://shopify/GenericFile/{target_file_id}"
        
        # Check each product for artwork references in metafields
        for product in products:
            product_id = product.get('id')
            product_title = product.get('title', 'Unknown')
            
            # Check product metafield
            metafield = product.get('metafield')
            
            if metafield and metafield.get('value'):
                metafield_value = metafield.get('value', '')
                metafield_id = metafield.get('id', '')
                
                # Check if the metafield contains a Shopify file ID
                if metafield_value.startswith('gid://shopify/GenericFile/'):
                    # Extract the numeric file ID from the Global ID
                    numeric_id = metafield_value.replace('gid://shopify/GenericFile/', '')
                    actual_filename = get_filename_from_file_id(numeric_id)
                    
                    if actual_filename:
                        # Check if this matches the column type
                        if column == 'left':
                            # Left column: Artwork_Guidelines files (but not Artwork_Guidelines_A)
                            if actual_filename.startswith('Artwork_Guidelines') and not actual_filename.startswith('Artwork_Guidelines_A'):
                                print(f"[PRODUCT UPDATE] ✅ Found Artwork_Guidelines reference in product: {product_title}")
                                
                                # Update the product metafield with the target file ID
                                if update_product_metafield(product_id, metafield_id, target_file_global_id):
                                    updated_count += 1
                                    print(f"[PRODUCT UPDATE] ✅ Updated: {product_title}")
                                else:
                                    print(f"[PRODUCT UPDATE] ❌ Failed to update: {product_title}")
                        elif column == 'right':
                            # Right column: Only Artwork_Guidelines_A files
                            if actual_filename.startswith('Artwork_Guidelines_A'):
                                print(f"[PRODUCT UPDATE] ✅ Found Artwork_Guidelines_A reference in product: {product_title}")
                                
                                # Update the product metafield with the target file ID
                                if update_product_metafield(product_id, metafield_id, target_file_global_id):
                                    updated_count += 1
                                    print(f"[PRODUCT UPDATE] ✅ Updated: {product_title}")
        else:
                                    print(f"[PRODUCT UPDATE] ❌ Failed to update: {product_title}")
        
        print(f"[PRODUCT UPDATE] ✅ Completed: {updated_count}/{total_count} products updated")
        
        if column == 'left':
            file_type = 'Artwork_Guidelines'
        else:
            file_type = 'Artwork_Guidelines_A'
            
        return {
            'updatedCount': updated_count,
            'totalCount': total_count,
            'message': f'Updated {updated_count} out of {total_count} products with {file_type} files to use {target_filename}'
        }
        
    except Exception as e:
        print(f"[PRODUCT UPDATE] Error: {str(e)}")
        return {
            'updatedCount': 0,
            'totalCount': 0,
            'error': str(e)
        }

if __name__ == "__main__":
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description='Artwork Updater - Upload files to Shopify')
    parser.add_argument('--upload', help='File to upload')
    parser.add_argument('--column', help='Column (left or right)')
    parser.add_argument('--temp_path', help='Path to temporary file')
    
    args = parser.parse_args()
    
    if args.upload:
        # Upload mode - this will be called by the frontend via SSE
        print(f"[UPLOAD] Starting upload process for: {args.upload}")
        print(f"[UPLOAD] Column: {args.column or 'general'}")
        print(f"[UPLOAD] Store: {STORE_DOMAIN}")
        print(f"[UPLOAD] Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Use the actual uploaded file from the frontend
        print(f"[DEBUG] temp_path argument: '{args.temp_path}'")
        print(f"[DEBUG] temp_path exists: {os.path.exists(args.temp_path) if args.temp_path else 'None'}")
        
        if args.temp_path and os.path.exists(args.temp_path):
            temp_file_path = args.temp_path
            print(f"[UPLOAD] Using uploaded file: {temp_file_path}")
        else:
            # Fallback: create a test file for demonstration
            print("[UPLOAD] No temp file provided, creating test file for demonstration...")
            
            import tempfile
            
            # Create a dummy file for testing
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                temp_file.write(b'Test PDF content for upload demonstration')
                temp_file_path = temp_file.name
            print(f"[UPLOAD] Created test file: {temp_file_path}")
        
        try:
            print("[UPLOAD] Starting upload to Shopify...")
            
            # Run the upload process
            success = upload_file_to_shopify(temp_file_path, args.upload)
            
            if success:
                print(f"[UPLOAD] Upload completed successfully: {args.upload}")
                print("[UPLOAD] File is now available in Shopify!")
            else:
                print(f"[UPLOAD] Upload failed: {args.upload}")
                sys.exit(1)
                
        finally:
            # Clean up the temporary file
            try:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                    print(f"[UPLOAD] Cleaned up temporary file: {temp_file_path}")
            except Exception as e:
                print(f"[WARNING] Could not clean up temporary file: {e}")
    else:
        # Test mode (default)
        print("[TEST] Artwork Updater - Clean and Simple")
        print(f"[TEST] Store: {STORE_DOMAIN}")
        print(f"[TEST] Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Test file fetching
        print("\n[TEST] Testing file fetching...")
        files = fetch_files_with_graphql()
        
        if files:
            print(f"[TEST] Found {len(files)} files:")
            for file in files[:5]:  # Show first 5 files
                filename = file.get('alt', file.get('filename', 'Unknown'))
                content_type = file.get('mimeType', 'Unknown')
                print(f"  - {filename} ({content_type})")
            if len(files) > 5:
                print(f"  ... and {len(files) - 5} more files")
        else:
            print("[TEST] No files found or error occurred")
        
        print("[TEST] Script loaded successfully with file handling capabilities")

def update_products_with_new_artwork(new_filename, column, new_version, previous_version):
    """
    Update all products that reference the previous artwork version with the new version
    """
    try:
        print(f"[PRODUCT UPDATE] Starting update: {new_filename} (v{previous_version} → v{new_version})")
        
        # Determine the base name for the artwork
        if column == 'left':
            base_name = 'Artwork_Guidelines'
        else:
            base_name = 'Artwork_Guidelines_A'
        
        # Create the old and new filename patterns
        old_filename_pattern = f"{base_name}_{previous_version}"
        new_filename_pattern = f"{base_name}_{new_version}.pdf"
        
        # Fetch all products from Shopify
        products = fetch_all_products()
        
        if not products:
            return {
                'updatedCount': 0,
                'totalCount': 0,
                'message': 'No products found'
            }
        
        updated_count = 0
        total_count = len(products)
        
        # Check each product for artwork references in metafields
        for product in products:
            product_id = product.get('id')
            product_title = product.get('title', 'Unknown')
            
            # Check product metafield (direct access since we're only fetching one)
            metafield = product.get('metafield')
            
            if metafield and metafield.get('value'):
                metafield_value = metafield.get('value', '')
                metafield_id = metafield.get('id', '')
                metafield_type = metafield.get('type', '')
                metafield_definition = metafield.get('definition', {})
                
                # Metafield type confirmed as file_reference
                
                # Check if the metafield contains a Shopify file ID
                if metafield_value.startswith('gid://shopify/GenericFile/'):
                    # Extract the numeric file ID from the Global ID
                    numeric_id = metafield_value.replace('gid://shopify/GenericFile/', '')
                    actual_filename = get_filename_from_file_id(numeric_id)
                    
                    if actual_filename and old_filename_pattern in actual_filename:
                        print(f"[PRODUCT UPDATE] ✅ Found reference in product: {product_title}")
                        
                        # Get the new file ID for the updated artwork
                        new_file_id = get_file_id_from_filename(new_filename_pattern)
                        
                        if new_file_id:
                            # Convert numeric file ID to Global ID format for file_reference type
                            new_file_global_id = f"gid://shopify/GenericFile/{new_file_id}"
                            # Update the product metafield with the new file ID
                            if update_product_metafield(product_id, metafield_id, new_file_global_id):
                                updated_count += 1
                                print(f"[PRODUCT UPDATE] ✅ Updated: {product_title}")
                            else:
                                print(f"[PRODUCT UPDATE] ❌ Failed to update: {product_title}")
                        else:
                            print(f"[PRODUCT UPDATE] ❌ Could not find new file: {new_filename_pattern}")
        
        print(f"[PRODUCT UPDATE] ✅ Completed: {updated_count}/{total_count} products updated")
        
        return {
            'updatedCount': updated_count,
            'totalCount': total_count,
            'message': f'Updated {updated_count} out of {total_count} products'
        }
        
    except Exception as e:
        print(f"[PRODUCT UPDATE] Error: {str(e)}")
        return {
            'updatedCount': 0,
            'totalCount': 0,
            'error': str(e)
        }

def fetch_all_products():
    """Fetch all products from Shopify using GraphQL"""
    try:
        graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
        
        # GraphQL query to fetch all products with only the artworkguidelines metafield
        query = """
        query getProducts($first: Int!, $after: String) {
            products(first: $first, after: $after) {
                edges {
                    node {
                        id
                        title
                        metafield(namespace: "custom", key: "artworkguidelines") {
                            id
                            value
                            type
                            definition {
                                type {
                                    name
                                }
                            }
                        }
                    }
                }
                pageInfo {
                    hasNextPage
                    endCursor
                }
            }
        }
        """
        
        all_products = []
        has_next_page = True
        cursor = None
        
        while has_next_page:
            variables = {
                "first": 50,  # Fetch 50 products at a time
                "after": cursor
            }
            
            # Use the helper function to handle redirects
            response = make_graphql_request(query, variables)
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and 'products' in data['data']:
                    products_data = data['data']['products']
                    
                    for edge in products_data['edges']:
                        product = edge['node']
                        all_products.append(product)
                    
                    # Check if there are more pages
                    page_info = products_data['pageInfo']
                    has_next_page = page_info['hasNextPage']
                    cursor = page_info['endCursor']
                else:
                    print(f"[PRODUCT UPDATE] Error in GraphQL response: {data}")
                    break
            else:
                print(f"[PRODUCT UPDATE] Failed to fetch products: {response.status_code}")
                break
        
        # Successfully fetched products (removed verbose debug)
        return all_products
        
    except Exception as e:
        print(f"[PRODUCT UPDATE] Error fetching products: {str(e)}")
        return []

def get_filename_from_file_id(file_id):
    """Get the actual filename from a Shopify file ID"""
    try:
        # Use the existing fetch_files_with_graphql function to get all files
        files = fetch_files_with_graphql()
        
        # Look for a file with matching ID
        for file_data in files:
            if file_data.get('id') == file_id:
                filename = file_data.get('alt') or file_data.get('filename', '')
                return filename
        
        return None
        
    except Exception as e:
        print(f"[PRODUCT UPDATE] Error fetching file: {str(e)}")
        return None

def get_file_id_from_filename(filename):
    """Get the Shopify file ID from a filename"""
    try:
        # Use the existing fetch_files_with_graphql function to get all files
        files = fetch_files_with_graphql()
        
        # Look for a file with matching alt text or filename
        for file_data in files:
            file_alt = file_data.get('alt', '')
            file_filename = file_data.get('filename', '')
            
            # Check exact match first
            if file_alt == filename or file_filename == filename:
                return file_data.get('id')
            
            # Check if filename matches without extension
            if file_alt == filename.replace('.pdf', '') or file_filename == filename.replace('.pdf', ''):
                return file_data.get('id')
            
            # Check if filename matches with extension added
            if file_alt == filename + '.pdf' or file_filename == filename + '.pdf':
                return file_data.get('id')
        
        # File not found (removed verbose debug)
        return None
        
    except Exception as e:
        print(f"[PRODUCT UPDATE] Error finding file: {str(e)}")
        return None

def update_product_metafield(product_id, metafield_id, new_value):
    """Update a product's metafield using GraphQL"""
    try:
        mutation = """
        mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
            metafieldsSet(metafields: $metafields) {
                metafields {
                    id
                    key
                    value
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        variables = {
            "metafields": [{
                "ownerId": product_id,
                "namespace": "custom",
                "key": "artworkguidelines",
                "value": new_value,
                "type": "file_reference"
            }]
        }
        
        # Use the helper function to handle redirects
        response = make_graphql_request(mutation, variables)
        
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and 'metafieldsSet' in data['data']:
                result = data['data']['metafieldsSet']
                if not result.get('userErrors'):
                    return True
                else:
                    print(f"[PRODUCT UPDATE] User errors: {result['userErrors']}")
                    return False
            else:
                print(f"[PRODUCT UPDATE] Error in response: {data}")
                return False
        else:
            print(f"[PRODUCT UPDATE] Failed to update metafield: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"[PRODUCT UPDATE] Error updating metafield: {str(e)}")
        return False
