from flask import Flask, render_template, jsonify, Response, make_response, request
import os
import subprocess
import requests
from datetime import datetime
import json

from config import ACCESS_TOKEN, API_VERSION, STORE_DOMAIN  # type: ignore

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# Increase maximum file size to 100MB
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# Add CORS headers
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Dynamically detect available tools (scripts) by listing filenames in scripts folder
def get_tools():
    scripts_dir = os.path.join(os.path.dirname(__file__), 'scripts')
    files = [f[:-3] for f in os.listdir(scripts_dir)
             if f.endswith('.py') and f not in ('app.py', '__init__.py')]
    return files

@app.route('/')
def index():
    try:
        response = make_response(render_template('index.html'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/test')
def test():
    return "Flask server is working! Template path: " + str(os.path.join(os.path.dirname(__file__), 'templates'))

@app.route('/api/tools')
def api_tools():
    return jsonify(get_tools())

@app.route('/api/products')
def api_products():
    try:
        # Import the Price Bandit script to use its functions
        import sys
        sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
        
        from Price_Bandit import get_all_products  # type: ignore
        
        products = get_all_products()
        
        # Format products for autocomplete
        formatted_products = []
        for product in products:
            formatted_product = {
                'id': product['id'],
                'title': product.get('title', 'Unknown Product'),
                'variants': product.get('variants', [])
            }
            formatted_products.append(formatted_product)
        
        return jsonify(formatted_products)
    except Exception as e:
        try:
            print(f"💥 Products error: {str(e)}")
        except (OSError, ValueError):
            pass
        return jsonify([])

@app.route('/api/shopify/files')
def api_shopify_files():
    try:
        import sys
        import os
        sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
        
        from Artwork_Updater import fetch_files_with_graphql  # type: ignore
        
        # Use the GraphQL function from Artwork_Updater
        files = fetch_files_with_graphql()
        
        if files:
            try:
                print(f"📁 Loaded {len(files)} files")
            except (OSError, ValueError):
                pass
            return jsonify(files)
        else:
            try:
                print("📁 No files found")
            except (OSError, ValueError):
                pass
            return jsonify([])
    except Exception as e:
        try:
            print(f"💥 Error loading files: {str(e)}")
        except (OSError, ValueError):
            # stdout might be closed or corrupted
            pass
        return jsonify([])



@app.route('/api/upload-file', methods=['POST'])
def api_upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        file_type = request.form.get('type', 'general')
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        print(f"📤 Uploading: {file.filename} ({file_type})")
        
        # Save the uploaded file temporarily
        import tempfile
        import os
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            file.save(temp_file.name)
            temp_file_path = temp_file.name
        
        try:
            # Import the Artwork_Updater script to use its upload function
            import sys
            sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
            
            try:
                from Artwork_Updater import upload_file_to_shopify  # type: ignore
            except ImportError as e:
                error_msg = f"Failed to import Artwork_Updater: {str(e)}"
                print(f"❌ {error_msg}")
                return jsonify({'success': False, 'error': error_msg}), 500
            
            # Upload the file to Shopify using the temporary file path
            print(f"🔄 Starting Shopify upload for: {file.filename}")
            result = upload_file_to_shopify(temp_file_path, file.filename)
            
            if result:
                print(f"✅ Upload successful: {file.filename}")
                return jsonify({
                    'success': True, 
                    'filename': file.filename,
                    'message': 'File uploaded successfully to Shopify',
                    'id': '12345',  # Mock ID for testing
                    'content_type': file.content_type,
                    'size': os.path.getsize(temp_file_path),
                    'created_at': datetime.now().isoformat(),
                    'url': f'https://example.com/files/{file.filename}'  # Mock URL
                })
            else:
                error_msg = 'Upload function returned no result'
                print(f"❌ Upload failed: {error_msg}")
                return jsonify({'success': False, 'error': error_msg}), 400
                
        finally:
            # Clean up the temporary file
            try:
                os.unlink(temp_file_path)
                print(f"🧹 Cleaned up temporary file: {temp_file_path}")
            except Exception as cleanup_error:
                print(f"⚠️ Warning: Could not clean up temporary file {temp_file_path}: {cleanup_error}")
            
    except Exception as e:
        error_msg = str(e)
        # Limit error message length to prevent long strings
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "..."
        print(f"💥 Upload error: {error_msg}")
        return jsonify({'success': False, 'error': error_msg}), 500

@app.route('/api/upload-progress')
def api_upload_progress():
    """Stream real-time upload progress updates"""
    def generate():
        # This would be connected to a real-time progress system
        # For now, we'll return the console output from the upload process
        yield "data: {\"type\": \"progress\", \"message\": \"Upload progress streaming enabled\"}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/suggest-filename', methods=['POST'])
def api_suggest_filename():
    """Suggest next filename based on existing files with auto-incrementing integers"""
    try:
        data = request.get_json()
        base_name = data.get('baseName', 'Artwork_Guidelines')
        
        # Get existing files
        import sys
        sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
        
        from Artwork_Updater import fetch_files_with_graphql  # type: ignore
        
        files = fetch_files_with_graphql()
        
        if not files:
            return jsonify({'suggestedName': f"{base_name}_1"})
        
        # Extract integers from existing filenames
        max_integer = 0
        for file in files:
            filename = file.get('alt', '') or file.get('filename', '')
            if filename:
                # Look for patterns like "Artwork_Guidelines_1", "Artwork_Guidelines_2", etc.
                if base_name in filename:
                    # Extract the number after the base name
                    parts = filename.split(base_name + '_')
                    if len(parts) > 1:
                        try:
                            number = int(parts[1].split('.')[0])  # Remove file extension
                            max_integer = max(max_integer, number)
                        except ValueError:
                            continue
        
        # Suggest next filename
        suggested_name = f"{base_name}_{max_integer + 1}"
        return jsonify({'suggestedName': suggested_name})
        
    except Exception as e:
        print(f"💥 Error suggesting filename: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/delete_file', methods=['POST'])
def delete_file():
    """Delete a file from Shopify using GraphQL"""
    try:
        data = request.get_json()
        file_id = data.get('fileId')
        filename = data.get('filename')
        
        if not file_id:
            return jsonify({'success': False, 'error': 'No file ID provided'}), 400
        
        print(f"🗑️ Deleting file: {filename} (ID: {file_id})")
        
        # GraphQL mutation to delete the file
        graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
        
        # Convert numeric ID to Global ID format
        file_global_id = f"gid://shopify/GenericFile/{file_id}"
        
        mutation = """
        mutation fileDelete($fileIds: [ID!]!) {
            fileDelete(fileIds: $fileIds) {
                deletedFileIds
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        variables = {
            "fileIds": [file_global_id]
        }
        
        headers = {
            'X-Shopify-Access-Token': ACCESS_TOKEN,
            'Content-Type': 'application/json',
        }
        
        response = requests.post(graphql_url, json={'query': mutation, 'variables': variables}, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            
            # Check for GraphQL errors
            if 'errors' in data:
                error_msg = f"GraphQL errors: {data['errors']}"
                print(f"❌ {error_msg}")
                return jsonify({'success': False, 'error': error_msg}), 400
            
            if 'data' in data and 'fileDelete' in data['data']:
                result = data['data']['fileDelete']
                
                if result.get('userErrors'):
                    error_msg = f"User errors: {result['userErrors']}"
                    print(f"❌ {error_msg}")
                    return jsonify({'success': False, 'error': error_msg}), 400
                
                if result.get('deletedFileIds'):
                    print(f"✅ File deleted successfully: {filename}")
                    return jsonify({
                        'success': True,
                        'message': f'File "{filename}" deleted successfully',
                        'deletedFileIds': result['deletedFileIds']
                    })
                else:
                    error_msg = 'File was not deleted - no deleted file IDs returned'
                    print(f"❌ {error_msg}")
                    return jsonify({'success': False, 'error': error_msg}), 400
            else:
                error_msg = 'Invalid response format from Shopify'
                print(f"❌ {error_msg}")
                return jsonify({'success': False, 'error': error_msg}), 400
        else:
            error_msg = f"HTTP error: {response.status_code}"
            print(f"❌ {error_msg}")
            return jsonify({'success': False, 'error': error_msg}), 400
            
    except Exception as e:
        error_msg = str(e)
        print(f"💥 Delete error: {error_msg}")
        return jsonify({'success': False, 'error': error_msg}), 500

@app.route('/check_file_usage', methods=['POST'])
def check_file_usage():
    """Check if a file is currently being used in products"""
    try:
        data = request.get_json()
        file_id = data.get('fileId')
        filename = data.get('filename')
        
        if not file_id:
            return jsonify({'success': False, 'error': 'No file ID provided'}), 400
        
        print(f"🔍 Checking file usage: {filename} (ID: {file_id})")
        
        # Import the Artwork_Updater script to use its functions
        import sys
        sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
        
        try:
            from Artwork_Updater import fetch_all_products, get_filename_from_file_id  # type: ignore
        except ImportError as e:
            error_msg = f"Failed to import Artwork_Updater: {str(e)}"
            print(f"❌ {error_msg}")
            return jsonify({'success': False, 'error': error_msg}), 500
        
        # Fetch all products and check if any use this file
        products = fetch_all_products()
        file_global_id = f"gid://shopify/GenericFile/{file_id}"
        
        products_using_file = []
        for product in products:
            metafield = product.get('metafield')
            if metafield and metafield.get('value') == file_global_id:
                products_using_file.append({
                    'id': product.get('id'),
                    'title': product.get('title', 'Unknown')
                })
        
        is_used = len(products_using_file) > 0
        
        print(f"📊 File usage check: {filename} is {'used' if is_used else 'not used'} in {len(products_using_file)} products")
        
        return jsonify({
            'success': True,
            'isUsed': is_used,
            'productsUsingFile': products_using_file,
            'usageCount': len(products_using_file)
        })
        
    except Exception as e:
        error_msg = str(e)
        print(f"💥 File usage check error: {error_msg}")
        return jsonify({'success': False, 'error': error_msg}), 500

@app.route('/api/update-products-to-file', methods=['POST'])
def api_update_products_to_file():
    """Update all products to use a specific file"""
    try:
        data = request.get_json()
        target_filename = data.get('targetFilename')
        column = data.get('column')
        
        if not target_filename:
            return jsonify({'success': False, 'error': 'No target filename provided'}), 400
        
        print(f"🔄 Updating products to use file: {target_filename} (column: {column})")
        
        # Import the Artwork_Updater script to use its functions
        import sys
        sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
        
        try:
            from Artwork_Updater import update_products_to_specific_file  # type: ignore
        except ImportError as e:
            error_msg = f"Failed to import Artwork_Updater: {str(e)}"
            print(f"❌ {error_msg}")
            return jsonify({'success': False, 'error': error_msg}), 500
        
        # Update products to use the target file
        result = update_products_to_specific_file(target_filename, column)
        
        if 'error' in result:
            print(f"❌ Product update failed: {result['error']}")
            return jsonify({'success': False, 'error': result['error']}), 400
        
        print(f"✅ Product update successful: {result['message']}")
        return jsonify({
            'success': True,
            'message': result['message'],
            'updatedCount': result['updatedCount'],
            'totalCount': result['totalCount']
        })
        
    except Exception as e:
        error_msg = str(e)
        print(f"💥 Product update error: {error_msg}")
        return jsonify({'success': False, 'error': error_msg}), 500

@app.route('/api/product/<int:product_id>')
def api_product_detail(product_id):
    try:
        import sys
        import os
        sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
        
        from Field_Finder import fetch_all_metafields  # type: ignore
        
        # Get product details
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        headers = {"X-Shopify-Access-Token": ACCESS_TOKEN}
        
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch product"}), 400
        
        product_data = response.json().get("product", {})
        
        # Get metafields
        metafields = fetch_all_metafields(product_id)
        
        # Format the response
        formatted_product = {
            'id': product_data['id'],
            'title': product_data.get('title', 'Unknown Product'),
            'handle': product_data.get('handle', ''),
            'vendor': product_data.get('vendor', ''),
            'product_type': product_data.get('product_type', ''),
            'tags': product_data.get('tags', []),
            'options': product_data.get('options', []),
            'variants': product_data.get('variants', []),
            'metafields': metafields
        }
        
        return jsonify(formatted_product)
    except Exception as e:
        print(f"💥 Product detail error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/product/<int:product_id>/prices')
def api_product_prices(product_id):
    """Special endpoint for Price Manager that returns all metafields including pricejson ones"""
    try:
        # Get product details
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        headers = {"X-Shopify-Access-Token": ACCESS_TOKEN}
        
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch product"}), 400
        
        product_data = response.json().get("product", {})
        
        # Get ALL metafields without filtering
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json?limit=250"
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch metafields"}), 400
        
        metafields_data = response.json()
        all_metafields = metafields_data.get("metafields", [])
        
        # Format the response
        formatted_product = {
            'id': product_data['id'],
            'title': product_data.get('title', 'Unknown Product'),
            'handle': product_data.get('handle', ''),
            'vendor': product_data.get('vendor', ''),
            'product_type': product_data.get('product_type', ''),
            'status': product_data.get('status', 'active'),
            'body_html': product_data.get('body_html', ''),
            'tags': product_data.get('tags', []),
            'options': product_data.get('options', []),
            'variants': product_data.get('variants', []),
            'images': product_data.get('images', []),
            'metafields': all_metafields  # Include ALL metafields
        }
        
        return jsonify(formatted_product)
    except Exception as e:
        print(f"💥 Product prices error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/metafield/update', methods=['POST'])
def api_metafield_update():
    try:
        import sys
        import os
        sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
        
        from Field_Finder import update_metafield  # type: ignore
        
        data = request.get_json()
        metafield_id = data.get('metafield_id')
        value = data.get('value')
        metafield_type = data.get('metafield_type')  # Get the metafield type
        
        if not metafield_id or value is None:
            return jsonify({"error": "Missing required fields"}), 400
        
        success = update_metafield(metafield_id, value, metafield_type)
        
        if success:
            return jsonify({"message": "Metafield updated successfully"})
        else:
            return jsonify({"error": "Failed to update metafield"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/metafield/delete', methods=['POST'])
def api_metafield_delete():
    try:
        data = request.get_json()
        metafield_id = data.get('metafield_id')
        
        if not metafield_id:
            return jsonify({"error": "Missing metafield ID"}), 400
        
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/metafields/{metafield_id}.json"
        headers = {"X-Shopify-Access-Token": ACCESS_TOKEN}
        
        response = requests.delete(url, headers=headers)
        
        if response.status_code == 200:
            return jsonify({"message": "Metafield deleted successfully"})
        else:
            return jsonify({"error": f"Failed to delete metafield: {response.status_code}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/metafield/create', methods=['POST'])
def api_metafield_create():
    try:
        import sys
        import os
        sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
        
        from Field_Finder import create_metafield  # type: ignore
        
        data = request.get_json()
        product_id = data.get('product_id')
        namespace = data.get('namespace')
        key = data.get('key')
        value = data.get('value')
        metafield_type = data.get('type', 'single_line_text_field')
        
        if not all([product_id, namespace, key]):
            return jsonify({"error": "Missing required fields"}), 400
        
        metafield_id = create_metafield(product_id, namespace, key, value, metafield_type)
        
        if metafield_id:
            return jsonify({"message": "Metafield created successfully", "id": metafield_id})
        else:
            return jsonify({"error": "Failed to create metafield"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/update_metafield', methods=['POST'])
def api_update_metafield():
    try:
        data = request.get_json()
        
        product_id = data.get('product_id')
        metafield_key = data.get('metafield_key')
        metafield_value = data.get('metafield_value')
        
        if not all([product_id, metafield_key, metafield_value is not None]):
            return jsonify({"error": "Missing required fields"}), 400
        
        # Create or update the metafield
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
        headers = {
            "X-Shopify-Access-Token": ACCESS_TOKEN,
            "Content-Type": "application/json"
        }
        
        # Convert the value to string format for single_line_text_field type
        if isinstance(metafield_value, (list, dict)):
            # Format JSON as single line with spaces after colons for Liquid parsing compatibility
            # single_line_text_field doesn't support line breaks
            value_to_save = json.dumps(metafield_value, separators=(',', ': '))
        else:
            value_to_save = str(metafield_value)
        
        # Get the metafield type from the request, or default to single_line_text_field
        metafield_type = data.get('metafield_type', 'single_line_text_field')
        
        metafield_data = {
            "metafield": {
                "namespace": "custom",
                "key": metafield_key,
                "value": value_to_save,
                "type": metafield_type
            }
        }
        
        response = requests.post(url, headers=headers, json=metafield_data)
        
        if response.status_code in [200, 201]:
            # After successful save, run Price Bandit for this product
            try:
                run_price_bandit_for_product(product_id)
            except Exception as e:
                print(f"⚠️ Price Bandit run failed: {str(e)}")
                # Don't fail the save operation if Price Bandit fails
            
            return jsonify({"success": True, "message": "Metafield updated successfully and Price Bandit triggered"})
        else:
            return jsonify({"error": f"Failed to update metafield: {response.text}"}), 400
            
    except Exception as e:
        print(f"💥 Metafield update error: {str(e)}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

def run_price_bandit_for_product(product_id):
    """Run Price Bandit for a specific product to update pricing"""
    try:
        import subprocess
        import os
        import sys
        
        # Get the product details to use as filter
        from Field_Finder import get_product_by_id  # type: ignore
        product = get_product_by_id(product_id)
        if not product:
            return False

        product_name = product.get('title', 'Unknown')

        # Run Price_Bandit script directly with the product name as filter
        script_path = os.path.join(os.path.dirname(__file__), 'scripts', 'Price_Bandit.py')

        # Use the same Python interpreter that's currently running
        python_executable = sys.executable

        # Get current environment and ensure we're using the same Python path
        env = os.environ.copy()

        # Ensure UTF-8 encoding for subprocess I/O on Windows
        env = env.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        result = subprocess.run([
            python_executable, script_path, product_name
        ], capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=os.path.dirname(__file__), env=env)

        if result.returncode == 0:
            return True
        else:
            return False
            
    except Exception as e:
        print(f"💥 Price Bandit error: {str(e)}")
        return False

@app.route('/api/price-bandit/run', methods=['POST'])
def api_run_price_bandit():
    try:
        data = request.get_json() or {}
        product_id = data.get('product_id')
        if not product_id:
            return jsonify({'success': False, 'error': 'Missing product_id'}), 400

        ok = run_price_bandit_for_product(int(product_id))
        if ok:
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Price Bandit run failed'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/app/<tool_name>')
def load_tool(tool_name):
    template_path = f'UI/{tool_name}.html'
    try:
        return render_template(template_path)
    except:
        return f"<p>Tool UI for '{tool_name}' not found.</p>"

@app.route('/api/templates-uploader/upload-zip', methods=['POST'])
def api_templates_uploader_upload_zip():
    try:
        product_id = request.form.get('product_id')
        zip_name = request.form.get('zip_name', 'artwork_templates')
        explicit_version = request.form.get('explicit_version')
        if not product_id:
            return jsonify({'success': False, 'error': 'Missing product_id'}), 400
        files = request.files.getlist('files')
        if not files:
            return jsonify({'success': False, 'error': 'No files provided'}), 400

        # Convert uploaded files to in-memory bytes list
        prepared = []
        for f in files:
            content = f.read()
            if not content:
                continue
            prepared.append({'filename': f.filename, 'content': content, 'content_type': f.content_type or 'application/octet-stream'})
        if not prepared:
            return jsonify({'success': False, 'error': 'All files were empty'}), 400

        # Use the script helper to zip, upload and set metafield
        import sys, os
        sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
        from Templates_Uploader import upload_zip_and_set_metafield  # type: ignore

        ver_int = None
        try:
            if explicit_version:
                ver_int = int(explicit_version)
        except Exception:
            ver_int = None

        result = upload_zip_and_set_metafield(product_id=str(product_id), filename=zip_name, files=prepared, explicit_version=ver_int)
        return jsonify({'success': True, **result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/templates-uploader/zip-contents', methods=['POST'])
def api_templates_uploader_zip_contents():
    try:
        data = request.get_json() or {}
        file_global_id = data.get('file_global_id') or data.get('global_id') or data.get('id')
        if not file_global_id:
            return jsonify({'success': False, 'error': 'Missing file_global_id'}), 400

        # Resolve file URL via GraphQL node query, with brief retries to allow processing
        from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION  # type: ignore
        graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
        headers = {'X-Shopify-Access-Token': ACCESS_TOKEN, 'Content-Type': 'application/json'}
        query = """
        query getFile($id: ID!) {
          node(id: $id) {
            ... on GenericFile { id url }
            ... on MediaImage { id image { url } }
          }
        }
        """

        import time, io, zipfile, base64, mimetypes

        file_url = None
        last_error = None
        for _ in range(8):  # retry up to ~8 seconds
            # Handle redirects for GraphQL requests
            resp = requests.post(graphql_url, headers=headers, json={'query': query, 'variables': {'id': file_global_id}}, allow_redirects=False)
            
            # If redirected, follow it
            if resp.status_code in [301, 302, 303, 307, 308]:
                redirect_url = resp.headers.get('Location', graphql_url)
                if redirect_url.startswith('/'):
                    from urllib.parse import urlparse
                    parsed = urlparse(graphql_url)
                    redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                resp = requests.post(redirect_url, headers=headers, json={'query': query, 'variables': {'id': file_global_id}}, allow_redirects=True)
            
            if resp.status_code != 200:
                last_error = f'GraphQL HTTP {resp.status_code}'
                time.sleep(1)
                continue
            data_json = resp.json()
            if 'errors' in data_json:
                last_error = f"GraphQL errors: {data_json['errors']}"
                time.sleep(1)
                continue
            node = (data_json.get('data') or {}).get('node') or {}
            file_url = node.get('url') or (node.get('image') or {}).get('url')
            if file_url:
                # Try to download
                file_resp = requests.get(file_url, stream=True)
                if file_resp.status_code == 200:
                    content = file_resp.content
                    try:
                        zf = zipfile.ZipFile(io.BytesIO(content))
                        # Success, break out
                        break
                    except Exception as zerr:
                        last_error = f'Not a valid ZIP yet: {zerr}'
                else:
                    last_error = f'Download HTTP {file_resp.status_code}'
            time.sleep(1)
        else:
            # Retries exhausted
            return jsonify({'success': False, 'error': last_error or 'File URL not ready'}), 400

        # Build entries
        entries = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            size = info.file_size
            mime, _ = mimetypes.guess_type(name)
            is_image = bool(mime and mime.startswith('image/'))
            preview_data_url = None
            if is_image and size <= 300_000:
                try:
                    data_bytes = zf.read(info)
                    b64 = base64.b64encode(data_bytes).decode('ascii')
                    preview_data_url = f"data:{mime};base64,{b64}"
                except Exception:
                    preview_data_url = None
            entries.append({'name': name, 'size': size, 'is_image': is_image, 'preview': preview_data_url})

        return jsonify({'success': True, 'entries': entries, 'count': len(entries)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/templates-uploader/zip-file', methods=['GET'])
def api_templates_uploader_zip_file():
    try:
        file_global_id = request.args.get('file_global_id', '').strip()
        entry_name = request.args.get('name', '').strip()
        if not file_global_id or not entry_name:
            return jsonify({'success': False, 'error': 'Missing file_global_id or name'}), 400

        from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION  # type: ignore
        graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
        headers = {'X-Shopify-Access-Token': ACCESS_TOKEN, 'Content-Type': 'application/json'}
        query = """
        query getFile($id: ID!) {
          node(id: $id) {
            ... on GenericFile { id url }
            ... on MediaImage { id: id image { url } }
          }
        }
        """
        resp = requests.post(graphql_url, headers=headers, json={'query': query, 'variables': {'id': file_global_id}})
        if resp.status_code != 200:
            return jsonify({'success': False, 'error': f'GraphQL HTTP {resp.status_code}'}), 400
        data_json = resp.json()
        if 'errors' in data_json:
            return jsonify({'success': False, 'error': f"GraphQL errors: {data_json['errors']}"}), 400
        node = (data_json.get('data') or {}).get('node') or {}
        file_url = node.get('url') or (node.get('image') or {}).get('url')
        if not file_url:
            return jsonify({'success': False, 'error': 'File URL not found for given ID'}), 400

        # Download the ZIP
        file_resp = requests.get(file_url, stream=True)
        if file_resp.status_code != 200:
            return jsonify({'success': False, 'error': f'Failed to download file: HTTP {file_resp.status_code}'}), 400

        import io, zipfile, mimetypes
        content = file_resp.content
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
        except Exception:
            return jsonify({'success': False, 'error': 'File is not a valid ZIP'}), 400

        try:
            with zf.open(entry_name) as f:
                data_bytes = f.read()
        except KeyError:
            return jsonify({'success': False, 'error': 'Entry not found in ZIP'}), 404

        mime, _ = mimetypes.guess_type(entry_name)
        if not mime:
            mime = 'application/octet-stream'

        r = make_response(data_bytes)
        r.headers['Content-Type'] = mime
        # inline display with filename
        r.headers['Content-Disposition'] = f"inline; filename=\"{entry_name}\""
        return r
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/templates-uploader/versions', methods=['GET'])
def api_templates_uploader_versions():
    try:
        base = (request.args.get('base') or '').strip()
        if not base:
            return jsonify({'success': False, 'error': 'Missing base'}), 400

        # Discover files via existing Artwork_Updater helper
        import sys as _sys, os as _os, re as _re
        _sys.path.append(_os.path.join(_os.path.dirname(__file__), 'scripts'))
        from Artwork_Updater import fetch_files_with_graphql  # type: ignore

        files = fetch_files_with_graphql() or []
        pattern = _re.compile(rf"^{_re.escape(base)}_(\d+)\.zip$", _re.IGNORECASE)
        versions = []
        for f in files:
            name = f.get('filename') or f.get('alt') or ''
            if not name:
                url = f.get('url', '')
                if url:
                    tail = url.split('/')[-1].split('?')[0]
                    name = tail
            m = pattern.match(str(name))
            if m:
                try:
                    v = int(m.group(1))
                except Exception:
                    continue
                versions.append({
                    'name': name,
                    'version': v,
                    'url': f.get('url', ''),
                    'global_id': f.get('original_global_id', '')
                })

        # Sort by version descending
        versions.sort(key=lambda x: x.get('version', 0), reverse=True)
        next_version = (versions[0]['version'] + 1) if versions else 1
        return jsonify({'success': True, 'base': base, 'next_version': next_version, 'versions': versions})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/templates-uploader/use-version', methods=['POST'])
def api_templates_uploader_use_version():
    try:
        data = request.get_json() or {}
        product_id = data.get('product_id')
        file_global_id = data.get('file_global_id')
        if not product_id or not file_global_id:
            return jsonify({'success': False, 'error': 'Missing product_id or file_global_id'}), 400

        # Set metafield custom.artworktemplates to this file (file_reference)
        from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION  # type: ignore
        graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
        headers = {'X-Shopify-Access-Token': ACCESS_TOKEN, 'Content-Type': 'application/json'}
        mutation = """
        mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
          metafieldsSet(metafields: $metafields) {
            metafields { id key value }
            userErrors { field message }
          }
        }
        """
        variables = {
            'metafields': [{
                'ownerId': f"gid://shopify/Product/{product_id}",
                'namespace': 'custom',
                'key': 'artworktemplates',
                'type': 'file_reference',
                'value': file_global_id
            }]
        }
        # Handle redirects for GraphQL requests
        resp = requests.post(graphql_url, headers=headers, json={'query': mutation, 'variables': variables}, allow_redirects=False)
        
        # If redirected, follow it
        if resp.status_code in [301, 302, 303, 307, 308]:
            redirect_url = resp.headers.get('Location', graphql_url)
            if redirect_url.startswith('/'):
                from urllib.parse import urlparse
                parsed = urlparse(graphql_url)
                redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
            resp = requests.post(redirect_url, headers=headers, json={'query': mutation, 'variables': variables}, allow_redirects=True)
        
        if resp.status_code != 200:
            return jsonify({'success': False, 'error': f'GraphQL HTTP {resp.status_code}'}), 400
        j = resp.json()
        if 'errors' in j:
            return jsonify({'success': False, 'error': j['errors']}), 400
        ms = j.get('data', {}).get('metafieldsSet', {})
        if ms.get('userErrors'):
            return jsonify({'success': False, 'error': ms['userErrors']}), 400
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Server-Sent Events (SSE) route to run scripts and stream output
@app.route('/run/<tool_name>')
def run_tool(tool_name):
    # Handle case sensitivity by checking for exact filename match first
    scripts_dir = os.path.join(os.path.dirname(__file__), 'scripts')
    script_files = os.listdir(scripts_dir)
    
    # Find the exact script file (case-insensitive)
    script_file = None
    for file in script_files:
        if file.lower() == f'{tool_name}.py'.lower():
            script_file = file
            break
    
    if not script_file:
        return Response(f"data: Script '{tool_name}' not found.\n\n", mimetype='text/event-stream')
    
    # Build absolute script path to be robust regardless of current working directory
    base_dir = os.path.dirname(__file__)
    script_path = os.path.join(base_dir, 'scripts', script_file)
    
    # Handle different script types with their specific parameters
    # Use the same Python interpreter that's running Flask (more reliable on Windows)
    import sys as _sys
    python_exec = _sys.executable or 'python'
    cmd = [python_exec, '-u', script_path]  # -u flag for unbuffered output
    
    if tool_name == 'Price_Bandit':
        # Price Bandit can now handle multiple products or single product
        products_param = request.args.get('products', '').strip()
        product_param = request.args.get('product', '').strip()
        
        if products_param:
            # Multiple products specified as comma-separated IDs
            cmd.append('--products')
            cmd.append(products_param)
        elif product_param:
            # Single product specified (backward compatibility)
            cmd.append(product_param)
    elif tool_name == 'Field_Finder':
        # Field Finder uses product parameter
        product_filter = request.args.get('product', '').strip()
        if product_filter:
            cmd.append(product_filter)
    elif tool_name == 'Price_Manager':
        # Price Manager uses command parameter
        command = request.args.get('command', '').strip()
        if command:
            cmd.append(command)
        # Add additional parameters based on command
        if command == 'search':
            search_term = request.args.get('search_term', '').strip()
            if search_term:
                cmd.append(search_term)
        elif command == 'metafields':
            product_id = request.args.get('product_id', '').strip()
            if product_id:
                cmd.append(product_id)
        elif command == 'pricejsontr':
            product_id = request.args.get('product_id', '').strip()
            if product_id:
                cmd.append(product_id)
    elif tool_name == 'Artwork_Updater':
        # Artwork Updater uses action parameter
        action = request.args.get('action', '').strip()
        if action == 'upload':
            filename = request.args.get('filename', '').strip()
            column = request.args.get('column', '').strip()
            temp_path = request.args.get('temp_path', '').strip()
            if filename:
                cmd.append('--upload')
                cmd.append(filename)
                if column:
                    cmd.append('--column')
                    cmd.append(column)
                if temp_path:
                    cmd.append('--temp_path')
                    cmd.append(temp_path)

    def generate():
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=0,  # Unbuffered
                universal_newlines=True,
                encoding='utf-8',  # Explicitly set UTF-8 encoding
                errors='replace',  # Replace problematic characters
                cwd=base_dir  # Ensure scripts run from the backend directory
            )
            
            # Send initial message
            yield f"data: Starting {tool_name} script...\n\n"
            
            # Read output in real-time
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    # Clean the output and send it
                    cleaned_output = output.strip()
                    if cleaned_output:  # Only send non-empty lines
                        yield f"data: {cleaned_output}\n\n"
            
            # Wait for process to complete
            return_code = process.wait()
            
            if return_code == 0:
                yield f"data: Script completed successfully with exit code {return_code}\n\n"
            else:
                yield f"data: Script completed with exit code {return_code}\n\n"
                
        except Exception as e:
            yield f"data: Error running script: {str(e)}\n\n"
        finally:
            yield f"data: [DONE]\n\n"

    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Content-Type'] = 'text/event-stream; charset=utf-8'
    return response

@app.route('/api/update-products-artwork', methods=['POST'])
def update_products_artwork():
    """Update products with new artwork version"""
    try:
        print(f"[API] Product update endpoint called")
        data = request.get_json()
        print(f"[API] Received data: {data}")
        
        new_filename = data.get('newFilename')
        column = data.get('column')
        new_version = data.get('newVersion')
        previous_version = data.get('previousVersion')
        
        print(f"[API] Starting update process...")
        print(f"[API] New filename: {new_filename}")
        print(f"[API] Column: {column}")
        print(f"[API] New version: {new_version}")
        print(f"[API] Previous version: {previous_version}")
        
        # Import the artwork updater script
        from scripts.Artwork_Updater import update_products_with_new_artwork
        
        # Call the update function
        print(f"[API] Calling update_products_with_new_artwork...")
        result = update_products_with_new_artwork(
            new_filename=new_filename,
            column=column,
            new_version=new_version,
            previous_version=previous_version
        )
        
        print(f"[API] Update function returned: {result}")
        return jsonify(result)
        
    except Exception as e:
        print(f"[ERROR] Product update failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'updatedCount': 0,
            'totalCount': 0
        }), 500

@app.route('/api/update-products-to-file', methods=['POST'])
def update_products_to_file():
    """Update products to use a specific file"""
    try:
        print(f"[API] Update products to file endpoint called")
        data = request.get_json()
        print(f"[API] Received data: {data}")
        
        target_filename = data.get('targetFilename')
        column = data.get('column')
        
        print(f"[API] Starting update process...")
        print(f"[API] Target filename: {target_filename}")
        print(f"[API] Column: {column}")
        
        # Import the artwork updater script
        from scripts.Artwork_Updater import update_products_to_specific_file
        
        # Call the update function
        print(f"[API] Calling update_products_to_specific_file...")
        result = update_products_to_specific_file(
            target_filename=target_filename,
            column=column
        )
        
        print(f"[API] Update function returned: {result}")
        return jsonify(result)
        
    except Exception as e:
        print(f"[ERROR] Update products to file failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'updatedCount': 0,
            'totalCount': 0
        }), 500

@app.route('/api/create-product', methods=['POST'])
def api_create_product():
    """Create a new product in Shopify with media uploads"""
    try:
        print(f"[API] Create product endpoint called")
        
        # Check if request is multipart form data (with or without files)
        if request.content_type and request.content_type.startswith('multipart/form-data'):
            
            # Extract form data
            data = {}
            for key, value in request.form.items():
                if key.startswith('media_'):
                    continue  # Skip media files, they're in request.files
                
                # Parse JSON fields that come as strings from FormData
                if key in ['metafields', 'charge_vat', 'colour_images', 'categories', 'subcategories']:
                    try:
                        if key == 'metafields':
                            if value and value.strip():
                                data[key] = json.loads(value)
                            else:
                                data[key] = []
                        elif key == 'charge_vat':
                            data[key] = value.lower() in ['true', '1', 'yes'] if isinstance(value, str) else bool(value)
                        elif key == 'colour_images':
                            if value and value.strip():
                                data[key] = json.loads(value)
                            else:
                                data[key] = {}
                        elif key in ('categories', 'subcategories'):
                            if value and value.strip():
                                parsed = json.loads(value)
                                data[key] = parsed if isinstance(parsed, list) else [parsed]
                            else:
                                data[key] = []
                        else:
                            data[key] = value
                    except (json.JSONDecodeError, ValueError) as e:
                        print(f"⚠️ Failed to parse {key}: {e}", flush=True)
                        data[key] = value
                else:
                    data[key] = value
            
            # Handle media files
            media_files = []
            
            # Check for media_files format (new format)
            if 'media_files' in request.files:
                files = request.files.getlist('media_files')
                for file in files:
                    if file and file.filename:
                        media_files.append({
                            'filename': file.filename,
                            'content': file.read(),
                            'content_type': file.content_type
                        })
                        print(f"[API] Added media file: {file.filename} ({file.content_type})")
            else:
                # Fallback to media_${index} format (old format)
                media_count = int(request.form.get('media_count', 0))
                for i in range(media_count):
                    file_key = f'media_{i}'
                    if file_key in request.files:
                        file = request.files[file_key]
                        if file and file.filename:
                            media_files.append({
                                'filename': file.filename,
                                'content': file.read(),
                                'content_type': file.content_type
                            })
            
            data['media_files'] = media_files
            
            # Handle selected Shopify media IDs
            shopify_media_ids = request.form.getlist('shopify_media_ids')
            if shopify_media_ids:
                # Convert string IDs to integers (only if they're numeric)
                processed_ids = []
                for id in shopify_media_ids:
                    if id.isdigit():
                        processed_ids.append(int(id))
                    else:
                        processed_ids.append(id)  # Keep as string if it's a Global ID
                data['shopify_media_ids'] = processed_ids
                print(f"[API] Shopify media IDs to keep: {processed_ids}")
            else:
                data['shopify_media_ids'] = []
            
            # Handle media order for reordering
            media_order_str = request.form.get('media_order', '[]')
            try:
                media_order = json.loads(media_order_str) if media_order_str else []
                data['media_order'] = media_order
                print(f"[API] Media order received: {media_order}")
            except (json.JSONDecodeError, ValueError) as e:
                print(f"⚠️ Failed to parse media_order: {e}")
                data['media_order'] = []
            
        elif request.is_json:
            # Handle JSON data (backward compatibility)
            data = request.get_json()
        else:
            # Handle other content types
            return jsonify({
                'success': False,
                'error': f"Unsupported content type: {request.content_type}"
            }), 400
        
        # Import the Product Creator script
        from scripts.product_creator.Product_Creator import create_product, validate_product_data
        
        # Validate the product data
        validation = validate_product_data(data)
        if not validation["valid"]:
            return jsonify({
                'success': False,
                'error': f"Validation failed: {', '.join(validation['errors'])}"
            }), 400
        
        # Create the product
        result = create_product(data)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Failed to create product: {str(e)}"
        }), 500

@app.route('/api/shopify-media', methods=['GET'])
def api_get_shopify_media():
    """Get existing media files from Shopify using GraphQL"""
    try:
        # Import the necessary modules
        from scripts.Artwork_Updater import fetch_files_with_graphql
        
        # Use the existing GraphQL function from Artwork_Updater
        files = fetch_files_with_graphql()
        
        if files:
            # Filter for image and video files
            media_files = []
            for file in files:
                content_type = file.get("content_type", "")
                if content_type.startswith("image/") or content_type.startswith("video/"):
                    # Get the full Global ID from the original GraphQL response
                    full_global_id = file.get("original_global_id", f"gid://shopify/GenericFile/{file.get('id', '')}")
                    media_files.append({
                        "id": file.get("id", ""),  # Keep numeric ID for backward compatibility
                        "global_id": full_global_id,  # Add full Global ID
                        "filename": file.get("filename", file.get("alt", "Unknown")),
                        "content_type": content_type,
                        "size": file.get("size", 0),
                        "created_at": file.get("created_at", ""),
                        "url": file.get("url", ""),
                        "is_image": content_type.startswith("image/"),
                        "is_video": content_type.startswith("video/")
                    })
            
            # Sort by creation date (newest first)
            media_files.sort(key=lambda x: x["created_at"], reverse=True)
            
            return jsonify({
                "success": True,
                "media_files": media_files,
                "total": len(media_files)
            })
        else:
            return jsonify({
                "success": True,
                "media_files": [],
                "total": 0
            })
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Error fetching media files: {str(e)}"
        }), 500

@app.route('/api/metafield-choices/<namespace_key>', methods=['GET'])
def api_metafield_choices(namespace_key):
    """Get preset choices for a specific metafield"""
    try:
        # Single subcategory dropdown: return all subcategories when ?all=1
        if namespace_key == 'custom.subcategory' and request.args.get('all') == '1':
            from scripts.product_creator.categories import get_subcategory_choices
            choices = get_subcategory_choices()
        else:
            from scripts.product_creator.Product_Creator import get_metafield_choices
            choices = get_metafield_choices(namespace_key)
        
        return jsonify({
            'success': True,
            'choices': choices or []
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error fetching metafield choices: {str(e)}'
        }), 500

@app.route('/api/pricing-qty-bands', methods=['GET'])
def api_pricing_qty_bands():
    """Get the pricing quantity bands for autofill"""
    try:
        from scripts.product_creator.metafield_order import get_pricing_qty_bands
        bands = get_pricing_qty_bands()
        
        return jsonify({
            'success': True,
            'bands': bands
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error fetching pricing quantity bands: {str(e)}'
        }), 500

@app.route('/api/foil-colours', methods=['GET'])
def api_foil_colours():
    """Get the foil colours for autofill"""
    try:
        from scripts.product_creator.metafield_order import get_foil_colours
        colours = get_foil_colours()
        
        return jsonify({
            'success': True,
            'colours': colours
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error fetching foil colours: {str(e)}'
        }), 500

def map_subcategories_to_categories(categories, subcategories):
    """
    Map subcategories to their parent categories based on naming patterns
    Returns a dictionary mapping category -> [subcategories]
    """
    category_map = {}
    
    # Initialize all categories with empty lists
    for cat in categories:
        category_map[cat] = []
    
    # Map subcategories to categories based on patterns
    for subcat in subcategories:
        matched = False
        
        for cat in categories:
            # Pattern matching (similar to Category Editor logic)
            if "Biscuits" in cat:
                if "Biscuits" in subcat or "Cake" in subcat or "Cupcakes" in subcat or "Pies" in subcat:
                    category_map[cat].append(subcat)
                    matched = True
                    break
            elif "Cereal" in cat:
                if "Cereal" in subcat or "Porridge" in subcat:
                    category_map[cat].append(subcat)
                    matched = True
                    break
            elif "Chewing Gum" in cat and subcat == "Mint":
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Chocolate" and subcat in ["Balls", "Bars", "Coins", "Hearts", "Neapolitans", "Single Shapes", "Truffles"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif "Crips" in cat and subcat in ["BBQ", "Beef", "Cheese & Onion", "Plain/Original", "Salt & Vinegar", "Sour Cream"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif "Dried Fruits" in cat and subcat in ["Apricots", "Bananas", "Dates"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Drinks" and subcat in ["Coffee", "Fizzy", "Hot Chocolate", "Still", "Tea", "Water"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif "Jams" in cat and ("Marmalade" in subcat or "Marmite" in subcat or "Nutella" in subcat or "Jam" in subcat):
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Lollipops" and subcat in ["Chocolate", "Sugar"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif "Popcorn - Popped" in cat and subcat in ["Sweet", "Sweet & Salty", "Salted", "Toffee"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif "Popcorn - Microwave" in cat and subcat in ["Butter", "Salted", "Sweet"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Pretzels" and subcat in ["Original", "Sour Cream & Onion"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Protein" and subcat in ["Bars", "Nuts"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif "Savoury Snacks" in cat and subcat in ["Bars", "Bags", "Packs"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Soup" and subcat in ["Chicken", "Leek & Potato", "Minestrone", "Tomato"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Sprinkles" and subcat in ["Shapes", "Vermicelli"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Sweets" and subcat in ["Boiled/Compressed", "Jellies"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Mints" and subcat in ["Boiled Sweets", "Compressed Mints", "Chewing Gum"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Vegan" and subcat in ["Sweets", "Treats"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Packaging" and (subcat in ["Bags", "Bottle", "Card", "Eco", "Header Card", "Jar", "Label", "Nets", "Organza Bag", "Popcorn Box", "Plastic Box", "Tin", "Tub", "Wrap"] or "Card Box" in subcat):
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Seasonal" and subcat in ["Valentines Day", "Ramadan", "Eid", "Easter", "Summer", "Halloween", "Black Friday", "Christmas", "New Year"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Themes" and subcat in ["Achievement", "Anniversary", "Appreciation", "Awards", "Back To School", "British", "Carnival", "Celebrations", "Community", "Countdown to Launch", "Customers", "Diversity & Inclusion", "Empowerment", "Football", "Ideas", "Heroes", "Loyalty", "Mental Health", "Meet The Team", "Milestones", "Product Launch", "Referral Rewards", "Sale", "Saver Offers", "Success", "Staff", "Support", "Sustainability", "Thank You", "University", "Volunteer", "Wellbeing", "We Miss You"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Events & Charities" and subcat in ["Cancer Research", "Careers Week", "Mental Health Awareness", "Movember", "Pride", "Wimbledon", "World Bee Day", "Volunteers Week", "World Blood Donor Day", "World Cup - Football", "World Cup - Rugby"]:
                category_map[cat].append(subcat)
                matched = True
                break
            elif cat == "Brands" and subcat in ["Cadbury", "Haribo", "Heinz", "Jordans", "Kellom", "Mars", "McVities", "Nature Valley", "Nestle", "Swizzels", "Walkers"]:
                category_map[cat].append(subcat)
                matched = True
                break
        
        if not matched:
            # If no match found, add to "Uncategorized"
            if "Uncategorized" not in category_map:
                category_map["Uncategorized"] = []
            category_map["Uncategorized"].append(subcat)
    
    return category_map

def sync_category_collections(categories, subcategories, category_mapping=None):
    """Create or update Shopify collections for categories and subcategories using GraphQL"""
    try:
        from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION
        import time
        import json
        
        graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
        headers = {
            'X-Shopify-Access-Token': ACCESS_TOKEN,
            'Content-Type': 'application/json'
        }
        
        results = {
            'categories_created': 0,
            'categories_updated': 0,
            'subcategories_created': 0,
            'subcategories_updated': 0,
            'errors': []
        }
        
        # Map subcategories to categories
        if category_mapping:
            category_map = category_mapping
        else:
            try:
                from scripts.product_creator.categories import CATEGORY_MAPPING
                category_map = CATEGORY_MAPPING if CATEGORY_MAPPING else {}
                if not category_map:
                    category_map = map_subcategories_to_categories(categories, subcategories)
            except (ImportError, AttributeError):
                category_map = map_subcategories_to_categories(categories, subcategories)
        
        # Fetch all metafield definitions dynamically
        print("📋 Fetching metafield definitions...")
        
        # Build query for all possible subcategory metafields (max is ~128 subcategories per metafield)
        max_subcat_index = len(subcategories) // 128 + 2  # Add buffer for safety
        subcategory_aliases = []
        subcategory_queries = []
        
        # Always query for subcategory (index 0)
        subcategory_aliases.append("subcategory")
        subcategory_queries.append('subcategory: metafieldDefinitions(first: 1, namespace: "custom", key: "subcategory", ownerType: PRODUCT) { edges { node { id key } } }')
        
        # Query for subcategory_2, subcategory_3, etc.
        for i in range(2, max_subcat_index + 1):
            alias = f"subcategory_{i}"
            subcategory_aliases.append(alias)
            subcategory_queries.append(f'{alias}: metafieldDefinitions(first: 1, namespace: "custom", key: "{alias}", ownerType: PRODUCT) {{ edges {{ node {{ id key }} }} }}')
        
        get_defs_query = f"""
        query {{
            customCategory: metafieldDefinitions(first: 1, namespace: "custom", key: "custom_category", ownerType: PRODUCT) {{
                edges {{
                    node {{
                        id
                        key
                    }}
                }}
            }}
            {chr(10).join(subcategory_queries)}
        }}
        """
        
        defs_response = requests.post(graphql_url, json={'query': get_defs_query}, headers=headers)
        metafield_defs = {}
        
        if defs_response.status_code == 200:
            defs_data = defs_response.json()
            if 'errors' in defs_data:
                error_msg = f"Error fetching metafield definitions: {defs_data['errors']}"
                print(f"❌ {error_msg}")
                results['errors'].append(error_msg)
            else:
                data = defs_data.get('data', {})
                
                # Get custom_category
                if data.get('customCategory', {}).get('edges'):
                    metafield_defs['custom_category'] = data['customCategory']['edges'][0]['node']['id']
                    print(f"✅ Found custom_category metafield definition")
                else:
                    error_msg = "Metafield definition 'custom_category' not found"
                    print(f"❌ {error_msg}")
                    results['errors'].append(error_msg)
                    return results
                
                # Get all subcategory metafields
                for alias in subcategory_aliases:
                    if data.get(alias, {}).get('edges'):
                        metafield_defs[alias] = data[alias]['edges'][0]['node']['id']
                        print(f"✅ Found {alias} metafield definition")
        else:
            error_msg = f"Failed to fetch metafield definitions: HTTP {defs_response.status_code}"
            print(f"❌ {error_msg}")
            results['errors'].append(error_msg)
            return results
        
        if not metafield_defs.get('custom_category'):
            error_msg = "Missing required metafield definition: custom_category"
            results['errors'].append(error_msg)
            return results
        
        # Fetch all existing collections in batches
        print("📋 Fetching existing collections...")
        existing_collections = {}
        cursor = None
        has_next = True
        
        while has_next:
            query = """
            query getCollections($cursor: String) {
                collections(first: 250, after: $cursor, query: "collection_type:smart") {
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                    edges {
                        node {
                            id
                            title
                            ruleSet {
                                rules {
                                    column
                                    relation
                                    condition
                                }
                            }
                        }
                    }
                }
            }
            """
            
            variables = {"cursor": cursor} if cursor else {}
            response = requests.post(graphql_url, json={'query': query, 'variables': variables}, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if 'errors' in data:
                    error_msg = f"Error fetching collections: {data['errors']}"
                    print(f"❌ {error_msg}")
                    results['errors'].append(error_msg)
                    break
                
                collections_data = data.get('data', {}).get('collections', {})
                edges = collections_data.get('edges', [])
                
                for edge in edges:
                    collection = edge['node']
                    existing_collections[collection['title']] = collection['id']
                    # Debug: Print rules structure for first collection to see how Shopify stores metafield rules
                    if collection.get('ruleSet') and collection['ruleSet'].get('rules'):
                        if len(existing_collections) == 1:  # Only print for first collection
                            print(f"🔍 Debug: First collection '{collection['title']}' rules structure:")
                            print(f"   {json.dumps(collection['ruleSet']['rules'], indent=2)}")
                
                page_info = collections_data.get('pageInfo', {})
                has_next = page_info.get('hasNextPage', False)
                cursor = page_info.get('endCursor')
            else:
                error_msg = f"Failed to fetch collections: HTTP {response.status_code}"
                print(f"❌ {error_msg}")
                results['errors'].append(error_msg)
                break
        
        print(f"✅ Found {len(existing_collections)} existing smart collections")
        
        # Helper function to create/update a collection
        def create_or_update_collection(title, rules, is_update=False, collection_id=None):
            """Create or update a smart collection with given rules"""
            mutation_name = "collectionUpdate" if is_update else "collectionCreate"
            mutation = f"""
            mutation {mutation_name}($input: CollectionInput!) {{
                {mutation_name}(input: $input) {{
                    collection {{
                                id
                                title
                    }}
                    userErrors {{
                                field
                                message
                    }}
                }}
            }}
            """
            
            input_data = {
                            "ruleSet": {
                                "appliedDisjunctively": False,
                    "rules": rules
                }
            }
            
            if is_update:
                input_data["id"] = collection_id
            else:
                input_data["title"] = title
            
            variables = {"input": input_data}
            response = requests.post(graphql_url, json={'query': mutation, 'variables': variables}, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                mutation_name = "collectionUpdate" if is_update else "collectionCreate"
                
                if 'errors' in data:
                    return {'success': False, 'error': data['errors']}
                
                result = data.get('data', {}).get(mutation_name, {})
                
                if result.get('userErrors'):
                    return {'success': False, 'error': result['userErrors']}
                
                return {'success': True}
            else:
                return {'success': False, 'error': f"HTTP {response.status_code}"}
        
        category_def_id = metafield_defs['custom_category']
        
        # Process category collections
        print(f"📋 Processing {len(categories)} category collections...")
        for i, category in enumerate(categories, 1):
            try:
                if i % 10 == 0:  # Only sleep every 10 requests
                    time.sleep(0.2)
                
                collection_title = category
                collection_id = existing_collections.get(collection_title)
                
                rules = [{
                    "column": "PRODUCT_METAFIELD_DEFINITION",
                    "relation": "EQUALS",
                    "condition": collection_title
                }]
                
                result = create_or_update_collection(
                    collection_title,
                    rules,
                    is_update=(collection_id is not None),
                    collection_id=collection_id
                )
                
                if result['success']:
                    if collection_id:
                        results['categories_updated'] += 1
                    else:
                        results['categories_created'] += 1
                else:
                    error = result.get('error', 'Unknown error')
                    error_msg = f"Error processing category '{category}': {error}"
                    results['errors'].append(error_msg)
                            
            except Exception as e:
                error_msg = f"Error processing category collection '{category}': {str(e)}"
                results['errors'].append(error_msg)
        
        # Process subcategory collections
        print(f"📋 Processing subcategory collections...")
        try:
            from scripts.product_creator.categories import get_subcategory_metafield_key
        except (ImportError, AttributeError):
            get_subcategory_metafield_key = lambda x: "subcategory"
        
        subcategory_count = 0
        for category, subcats in category_map.items():
            for subcat in subcats:
                try:
                    subcategory_count += 1
                    if subcategory_count % 10 == 0:  # Only sleep every 10 requests
                        time.sleep(0.2)
                    
                    collection_title = subcat
                    collection_id = existing_collections.get(collection_title)
                    
                    # Get the metafield key for this subcategory
                    metafield_key = get_subcategory_metafield_key(subcat)
                    subcat_def_id = metafield_defs.get(metafield_key)
                    
                    if not subcat_def_id:
                        error_msg = f"Metafield definition '{metafield_key}' not found for subcategory '{subcat}'"
                        results['errors'].append(error_msg)
                        continue
                    
                    # Create rules: both category and subcategory must match
                    rules = [
                        {
                            "column": "PRODUCT_METAFIELD_DEFINITION",
                            "relation": "EQUALS",
                            "condition": category
                        },
                        {
                            "column": "PRODUCT_METAFIELD_DEFINITION",
                            "relation": "EQUALS",
                            "condition": subcat
                        }
                    ]
                    
                    result = create_or_update_collection(
                        collection_title,
                        rules,
                        is_update=(collection_id is not None),
                        collection_id=collection_id
                    )
                    
                    if result['success']:
                        if collection_id:
                            results['subcategories_updated'] += 1
                        else:
                            results['subcategories_created'] += 1
                    else:
                        error = result.get('error', 'Unknown error')
                        error_msg = f"Error processing subcategory '{subcat}': {error}"
                        results['errors'].append(error_msg)
                                
                except Exception as e:
                    error_msg = f"Error processing subcategory collection '{subcat}': {str(e)}"
                    results['errors'].append(error_msg)
        
        # Return results
        total_created = results['categories_created'] + results['subcategories_created']
        total_updated = results['categories_updated'] + results['subcategories_updated']
        
        if results['errors']:
            return {
                'success': False,
                'message': f"Collections sync completed with {len(results['errors'])} error(s)",
                'errors': results['errors'],
                'created': total_created,
                'updated': total_updated
            }
        else:
            return {
                'success': True,
                'message': f"Collections synced successfully: {total_created} created, {total_updated} updated",
                'created': total_created,
                'updated': total_updated
            }
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'success': False, 'errors': [f'Error syncing collections: {str(e)}']}

def sync_metafield_definitions(categories, subcategories):
    """Sync categories and subcategories to Shopify metafield definitions"""
    try:
        from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION
        
        # Deduplicate subcategories while preserving order
        seen = set()
        deduplicated_subcategories = []
        duplicates = []
        for subcat in subcategories:
            if subcat not in seen:
                seen.add(subcat)
                deduplicated_subcategories.append(subcat)
            else:
                duplicates.append(subcat)
        
        if duplicates:
            print(f"⚠️ Found {len(duplicates)} duplicate subcategories: {duplicates[:10]}{'...' if len(duplicates) > 10 else ''}")
            print(f"📊 Deduplicated: {len(subcategories)} → {len(deduplicated_subcategories)} subcategories")
        
        subcategories = deduplicated_subcategories
        
        graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
        headers = {
            'X-Shopify-Access-Token': ACCESS_TOKEN,
            'Content-Type': 'application/json'
        }
        
        results = {
            'category_synced': False,
            'subcategory_synced': False,
            'errors': []
        }
        
        # Sync custom_category metafield definition (product type)
        try:
            # Query for product metafield definitions
            get_query = """
            query getMetafieldDefinition($namespace: String!, $key: String!, $ownerType: MetafieldOwnerType!) {
                metafieldDefinitions(first: 1, namespace: $namespace, key: $key, ownerType: $ownerType) {
                    edges {
                        node {
                            id
                            name
                            namespace
                            key
                            ownerType
                            type {
                                name
                            }
                            validations {
                                name
                                value
                            }
                            capabilities {
                                smartCollectionCondition {
                                    enabled
                                }
                            }
                        }
                    }
                }
            }
            """
            
            # Check if category definition exists (product type)
            variables = {
                "namespace": "custom",
                "key": "custom_category",
                "ownerType": "PRODUCT"
            }
            
            response = requests.post(graphql_url, json={'query': get_query, 'variables': variables}, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if 'errors' in data:
                    print(f"❌ GraphQL errors for category: {data['errors']}")
                    results['errors'].append(f"Category definition query error: {data['errors']}")
                else:
                    edges = data.get('data', {}).get('metafieldDefinitions', {}).get('edges', [])
                    print(f"🔍 Found {len(edges)} category metafield definition(s)")
                    if edges:
                        print(f"🔍 Current definition structure: {json.dumps(edges[0]['node'], indent=2)}")
                    
                    if edges:
                        # Update existing definition
                        definition_node = edges[0]['node']
                        # Convert choices list to JSON string (matching the existing structure)
                        choices_json = json.dumps(categories)
                        
                        # Preserve existing capabilities and ensure smartCollectionCondition is enabled
                        existing_capabilities = definition_node.get("capabilities", {})
                        capabilities = existing_capabilities.copy() if existing_capabilities else {}
                        capabilities["smartCollectionCondition"] = {"enabled": True}
                        
                        update_mutation = """
                        mutation updateMetafieldDefinition($definition: MetafieldDefinitionUpdateInput!) {
                            metafieldDefinitionUpdate(definition: $definition) {
                                userErrors {
                                    field
                                    message
                                }
                            }
                        }
                        """
                        
                        update_variables = {
                            "definition": {
                                "name": definition_node["name"],
                                "namespace": definition_node["namespace"],
                                "key": definition_node["key"],
                                "ownerType": definition_node["ownerType"],
                                "capabilities": capabilities,
                                "validations": [
                                    {
                                        "name": "choices",
                                        "value": choices_json
                                    }
                                ]
                            }
                        }
                        
                        update_response = requests.post(graphql_url, json={'query': update_mutation, 'variables': update_variables}, headers=headers)
                        
                        if update_response.status_code == 200:
                            update_data = update_response.json()
                            if 'errors' in update_data:
                                results['errors'].append(f"Category definition update error: {update_data['errors']}")
                            elif update_data.get('data', {}).get('metafieldDefinitionUpdate', {}).get('userErrors'):
                                errors = update_data['data']['metafieldDefinitionUpdate']['userErrors']
                                results['errors'].append(f"Category definition user errors: {errors}")
                            else:
                                results['category_synced'] = True
                                print(f"✅ Updated custom_category metafield definition with {len(categories)} choices")
                    else:
                        print(f"ℹ️ custom_category metafield definition not found - creating is not supported via API, will need manual creation")
                        results['errors'].append("custom_category metafield definition not found - please create it manually in Shopify")
            else:
                results['errors'].append(f"Failed to fetch category definition: HTTP {response.status_code}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            results['errors'].append(f"Error syncing category definition: {str(e)}")
        
        # Sync subcategory metafield definitions (product type)
        # Use same boundary as categories.py: subcategory = before "Sweets", subcategory_2 = "Sweets" and after
        from scripts.product_creator.categories import get_metafield_choices as get_subcategory_choices_by_key
        MAX_CHOICES_PER_METAFIELD = 128
        subcategory_chunk_list = [
            ("subcategory", get_subcategory_choices_by_key("subcategory") or []),
            ("subcategory_2", get_subcategory_choices_by_key("subcategory_2") or []),
        ]
        # Drop subcategory_2 if empty (e.g. if boundary not in list)
        subcategory_chunk_list = [(k, c) for k, c in subcategory_chunk_list if c]
        
        print(f"📊 Subcategory definitions: subcategory ({len(subcategory_chunk_list[0][1])} choices), subcategory_2 ({len(subcategory_chunk_list[1][1]) if len(subcategory_chunk_list) > 1 else 0} choices)")
        
        update_mutation = """
        mutation updateMetafieldDefinition($definition: MetafieldDefinitionUpdateInput!) {
            metafieldDefinitionUpdate(definition: $definition) {
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        for metafield_key, chunk in subcategory_chunk_list:
            if len(chunk) > MAX_CHOICES_PER_METAFIELD:
                error_msg = f"{metafield_key} has {len(chunk)} items, exceeds {MAX_CHOICES_PER_METAFIELD} limit"
                print(f"❌ {error_msg}")
                results['errors'].append(error_msg)
                continue
            
            print(f"🔄 Processing {metafield_key}: {len(chunk)} subcategories")
            try:
                variables = {
                    "namespace": "custom",
                    "key": metafield_key,
                    "ownerType": "PRODUCT"
                }
                
                response = requests.post(graphql_url, json={'query': get_query, 'variables': variables}, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    if 'errors' in data:
                        print(f"❌ GraphQL errors for {metafield_key}: {data['errors']}")
                        results['errors'].append(f"{metafield_key} definition query error: {data['errors']}")
                        continue
                    
                    edges = data.get('data', {}).get('metafieldDefinitions', {}).get('edges', [])
                    print(f"🔍 Found {len(edges)} {metafield_key} metafield definition(s)")
                    
                    if edges:
                        # Update existing definition
                        # Convert choices list to JSON string (matching the existing structure)
                        choices_json = json.dumps(chunk)
                        print(f"📝 Updating {metafield_key} with {len(chunk)} choices: {choices_json[:100]}...")
                        
                        definition_node = edges[0]['node']
                        # Preserve existing capabilities and ensure smartCollectionCondition is enabled
                        existing_capabilities = definition_node.get("capabilities", {})
                        capabilities = existing_capabilities.copy() if existing_capabilities else {}
                        capabilities["smartCollectionCondition"] = {"enabled": True}
                        
                        update_variables = {
                            "definition": {
                                "name": definition_node["name"],
                                "namespace": definition_node["namespace"],
                                "key": definition_node["key"],
                                "ownerType": definition_node["ownerType"],
                                "capabilities": capabilities,
                                "validations": [
                                    {
                                        "name": "choices",
                                        "value": choices_json
                                    }
                                ]
                            }
                        }
                        
                        update_response = requests.post(graphql_url, json={'query': update_mutation, 'variables': update_variables}, headers=headers)
                        
                        if update_response.status_code == 200:
                            update_data = update_response.json()
                            if 'errors' in update_data:
                                results['errors'].append(f"{metafield_key} definition update error: {update_data['errors']}")
                            elif update_data.get('data', {}).get('metafieldDefinitionUpdate', {}).get('userErrors'):
                                errors = update_data['data']['metafieldDefinitionUpdate']['userErrors']
                                print(f"❌ {metafield_key} definition user errors: {errors}")
                                results['errors'].append(f"{metafield_key} definition user errors: {errors}")
                            else:
                                results['subcategory_synced'] = True
                                print(f"✅ Updated {metafield_key} metafield definition with {len(chunk)} choices")
                    else:
                        print(f"ℹ️ {metafield_key} metafield definition not found - creating is not supported via API, will need manual creation")
                        results['errors'].append(f"{metafield_key} metafield definition not found - please create it manually in Shopify")
                else:
                    results['errors'].append(f"Failed to fetch {metafield_key} definition: HTTP {response.status_code}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                results['errors'].append(f"Error syncing {metafield_key} definition: {str(e)}")
        
        if results['category_synced'] and results['subcategory_synced']:
            return {'success': True, 'message': 'Successfully synced both metafield definitions'}
        elif results['category_synced'] or results['subcategory_synced']:
            return {'success': True, 'message': f"Partially synced: category={results['category_synced']}, subcategory={results['subcategory_synced']}", 'errors': results['errors']}
        else:
            return {'success': False, 'errors': results['errors']}
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'success': False, 'errors': [f'Error syncing metafield definitions: {str(e)}']}

@app.route('/api/category-editor/categories', methods=['GET'])
def api_get_categories():
    """Get current categories and subcategories from categories.py"""
    try:
        from scripts.product_creator.categories import get_category_choices, get_subcategory_choices
        
        categories = get_category_choices()
        subcategories = get_subcategory_choices()
        
        # Try to get the stored mapping
        category_mapping = {}
        try:
            from scripts.product_creator.categories import CATEGORY_MAPPING
            category_mapping = CATEGORY_MAPPING if CATEGORY_MAPPING else {}
        except (ImportError, AttributeError):
            # If mapping doesn't exist or is empty, create empty dict
            pass
        
        return jsonify({
            'success': True,
            'categories': categories,
            'subcategories': subcategories,
            'category_mapping': category_mapping
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error fetching categories: {str(e)}'
        }), 500

@app.route('/api/category-editor/categories', methods=['POST'])
def api_update_categories():
    """Update categories and subcategories in categories.py"""
    try:
        data = request.get_json()
        categories = data.get('categories', [])
        subcategories = data.get('subcategories', [])
        category_mapping = data.get('category_mapping', {})
        
        # Debug: log received data
        print(f"📥 Received save request:")
        print(f"  Categories: {len(categories)}")
        print(f"  Subcategories: {len(subcategories)}")
        print(f"  Category mapping: {len(category_mapping)} categories")
        if category_mapping:
            for cat, subcats in list(category_mapping.items())[:3]:
                print(f"    {cat}: {len(subcats)} subcategories")
        
        if not isinstance(categories, list) or not isinstance(subcategories, list):
            return jsonify({
                'success': False,
                'error': 'Categories and subcategories must be arrays'
            }), 400
        
        # Path to categories.py file
        categories_file = os.path.join(os.path.dirname(__file__), 'scripts', 'product_creator', 'categories.py')
        
        # Read the current file
        with open(categories_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Generate new categories list string
        categories_str = '[\n'
        for cat in categories:
            cat_escaped = cat.replace('"', '\\"').replace('\\', '\\\\')
            categories_str += f'    "{cat_escaped}",\n'
        categories_str += ']'
        
        # Generate new subcategories list string with category headings
        # Use the mapping to add category comments before each group
        subcategories_str = '[\n'
        
        # Track which subcategories we've already added
        added_subcats = set()
        
        # Iterate through categories in order and add their subcategories with headings
        for cat in categories:
            if cat in category_mapping and category_mapping[cat] and len(category_mapping[cat]) > 0:
                # Add category heading as comment
                subcategories_str += f'    # {cat}\n'
                
                # Add subcategories for this category
                for subcat in category_mapping[cat]:
                    if subcat in subcategories and subcat not in added_subcats:
                        subcat_escaped = subcat.replace('"', '\\"').replace('\\', '\\\\')
                        subcategories_str += f'    "{subcat_escaped}",\n'
                        added_subcats.add(subcat)
        
        # Add any subcategories not in the mapping (shouldn't happen, but safety check)
        for subcat in subcategories:
            if subcat not in added_subcats:
                subcat_escaped = subcat.replace('"', '\\"').replace('\\', '\\\\')
                subcategories_str += f'    "{subcat_escaped}",\n'
                added_subcats.add(subcat)
        
        subcategories_str += ']'
        
        # Generate category mapping dictionary string
        # Only include categories that have subcategories
        mapping_str = '{\n'
        mapping_has_content = False
        if category_mapping:
            for cat in categories:
                if cat in category_mapping and category_mapping[cat] and len(category_mapping[cat]) > 0:
                    cat_escaped = cat.replace('"', '\\"').replace('\\', '\\\\')
                    mapping_str += f'    "{cat_escaped}": [\n'
                    for subcat in category_mapping[cat]:
                        subcat_escaped = subcat.replace('"', '\\"').replace('\\', '\\\\')
                        mapping_str += f'        "{subcat_escaped}",\n'
                    mapping_str += '    ],\n'
                    mapping_has_content = True
        mapping_str += '}'
        
        # Replace CATEGORIES list - match from CATEGORIES = to the closing bracket
        import re
        # Match CATEGORIES = [ ... ] including newlines
        cat_pattern = r'(CATEGORIES\s*=\s*)\[[\s\S]*?\]'
        content = re.sub(cat_pattern, r'\1' + categories_str, content, count=1, flags=re.DOTALL)
        
        # Replace SUBCATEGORIES list - match from SUBCATEGORIES = to the closing bracket
        subcat_pattern = r'(SUBCATEGORIES\s*=\s*)\[[\s\S]*?\]'
        content = re.sub(subcat_pattern, r'\1' + subcategories_str, content, count=1, flags=re.DOTALL)
        
        # Replace or add CATEGORY_MAPPING (only if it has content)
        if mapping_has_content:
            # Check if CATEGORY_MAPPING exists in the file
            if 'CATEGORY_MAPPING' in content:
                # Replace existing mapping - match from CATEGORY_MAPPING = to the closing brace
                # Handle both empty {} and multi-line dictionaries
                mapping_pattern = r'(CATEGORY_MAPPING\s*=\s*)\{[\s\S]*?\}'
                content = re.sub(mapping_pattern, r'\1' + mapping_str, content, count=1, flags=re.DOTALL)
            else:
                # Add mapping after SUBCATEGORIES list
                # Find the end of SUBCATEGORIES list (closing bracket followed by newline)
                subcat_pattern_end = r'(SUBCATEGORIES\s*=\s*\[[\s\S]*?\])\n'
                replacement = r'\1\n\n# Category to subcategory mapping\n# This dictionary stores which subcategories belong to which categories\n# Format: {"Category Name": ["Subcategory1", "Subcategory2", ...]}\nCATEGORY_MAPPING = ' + mapping_str + '\n'
                content = re.sub(subcat_pattern_end, replacement, content, count=1, flags=re.DOTALL)
        else:
            print("⚠️ No category mapping content to save - mapping is empty")
        
        # Debug: print mapping to console
        if category_mapping:
            print(f"📝 Saving category mapping with {len(category_mapping)} categories")
            for cat, subcats in category_mapping.items():
                if subcats:
                    print(f"  {cat}: {len(subcats)} subcategories - {subcats[:3]}{'...' if len(subcats) > 3 else ''}")
        else:
            print(f"⚠️ No category mapping received in save request")
        
        # Write back to file
        with open(categories_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Sync to Shopify metafield definitions
        sync_result = None
        try:
            sync_result = sync_metafield_definitions(categories, subcategories)
            if not sync_result['success']:
                errors = sync_result.get('errors', [])
                error_msg = '; '.join(errors) if errors else 'Unknown error'
                print(f"⚠️ Warning: Failed to sync metafield definitions: {error_msg}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"⚠️ Warning: Error syncing metafield definitions: {str(e)}")
            sync_result = {'success': False, 'errors': [str(e)]}
            # Don't fail the save operation if sync fails
        
        # Sync collections - pass the category_mapping so it uses the correct mapping
        collections_result = None
        try:
            # Add delay to ensure metafield definition updates have propagated
            if sync_result and sync_result.get('success'):
                print("⏳ Waiting 3 seconds for metafield definition updates to propagate...")
                import time
                time.sleep(3)
            
            collections_result = sync_category_collections(categories, subcategories, category_mapping=category_mapping)
            if not collections_result['success']:
                errors = collections_result.get('errors', [])
                error_msg = '; '.join(errors) if errors else 'Unknown error'
                print(f"⚠️ Warning: Failed to sync collections: {error_msg}")
            else:
                # Only print errors if there are any
                if collections_result.get('errors'):
                    print(f"⚠️ Collection sync errors: {len(collections_result.get('errors', []))} error(s)")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"⚠️ Warning: Error syncing collections: {str(e)}")
            collections_result = {'success': False, 'errors': [str(e)]}
            # Don't fail the save operation if collections fail
        
        return jsonify({
            'success': True,
            'message': 'Categories and subcategories updated successfully',
            'sync_result': sync_result if 'sync_result' in locals() else None,
            'collections_result': collections_result if 'collections_result' in locals() else None
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Error updating categories: {str(e)}'
        }), 500

if __name__ == '__main__':
    app.run(debug=False)
