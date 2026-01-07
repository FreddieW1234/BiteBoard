import os
import sys
import json
import time
import zipfile
import tempfile
import io
import requests

# UTF-8 encoding handled at subprocess level in backend

# Allow importing config from backend
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION
except ImportError:
    print("ERROR: Could not import config. Make sure config.py exists in the backend directory.")
    sys.exit(1)

HEADERS = {
    'X-Shopify-Access-Token': ACCESS_TOKEN,
    'Content-Type': 'application/json',
}

def graphql(query, variables=None):
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
    # Handle redirects for GraphQL requests
    resp = requests.post(url, headers=HEADERS, json={'query': query, 'variables': variables or {}}, allow_redirects=False)
    
    # If redirected, follow it silently
    if resp.status_code in [301, 302, 303, 307, 308]:
        redirect_url = resp.headers.get('Location', url)
        if redirect_url.startswith('/'):
            from urllib.parse import urlparse
            parsed = urlparse(url)
            redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
        resp = requests.post(redirect_url, headers=HEADERS, json={'query': query, 'variables': variables or {}}, allow_redirects=True)
    
    resp.raise_for_status()
    data = resp.json()
    if 'errors' in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data.get('data')

def fetch_product_basic(product_id):
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
    # GET requests can use default redirect handling
    r = requests.get(url, headers={'X-Shopify-Access-Token': ACCESS_TOKEN})
    r.raise_for_status()
    return r.json().get('product', {})

def fetch_metafield_artworktemplates(product_id):
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json?namespace=custom&key=artworktemplates"
    # GET requests can use default redirect handling
    r = requests.get(url, headers={'X-Shopify-Access-Token': ACCESS_TOKEN})
    if r.status_code != 200:
        return None
    items = r.json().get('metafields', [])
    return items[0] if items else None

def set_metafield_artworktemplates(product_id, global_file_id):
    # Use metafieldsSet to set file_reference
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
            'value': global_file_id
        }]
    }
    data = graphql(mutation, variables)
    errors = data['metafieldsSet'].get('userErrors') if data and 'metafieldsSet' in data else None
    if errors:
        raise RuntimeError(f"Metafield set errors: {errors}")
    return True

def staged_upload(filename, mime_type):
    mutation = """
    mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
      stagedUploadsCreate(input: $input) {
        stagedTargets { url resourceUrl parameters { name value } }
        userErrors { field message }
      }
    }
    """
    variables = {
        'input': [{
            'filename': filename,
            'mimeType': mime_type,
            'resource': 'FILE'
        }]
    }
    data = graphql(mutation, variables)
    result = data['stagedUploadsCreate']
    if result.get('userErrors'):
        raise RuntimeError(result['userErrors'])
    return result['stagedTargets'][0]

def file_create_from_staged(staged_target, alt_text):
    mutation = """
    mutation fileCreate($files: [FileCreateInput!]!) {
      fileCreate(files: $files) {
        files { id alt }
        userErrors { field message }
      }
    }
    """
    variables = {
        'files': [{
            'originalSource': staged_target['url'].split('?')[0],
            'alt': ''  # create with blank alt text
        }]
    }
    data = graphql(mutation, variables)
    if data['fileCreate'].get('userErrors'):
        raise RuntimeError(data['fileCreate']['userErrors'])
    return data['fileCreate']['files'][0]['id']

def upload_bytes_to_staged(staged_target, content_bytes, mime_type):
    # Default to PUT first
    r = requests.put(staged_target['url'], data=content_bytes, headers={'Content-Type': mime_type})
    if r.status_code in (200, 201, 204):
        return True
    # Fallback to POST multipart
    files = {'file': ('upload', io.BytesIO(content_bytes), mime_type)}
    r = requests.post(staged_target['url'], data={p['name']: p['value'] for p in staged_target['parameters']}, files=files)
    return r.status_code in (200, 201, 204)

def zip_files_to_bytes(file_list):
    # file_list: list of dicts with keys: filename, content (bytes)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in file_list:
            name = item.get('filename') or 'file'
            content = item.get('content') or b''
            # Ensure unique names inside ZIP
            zf.writestr(name, content)
    buf.seek(0)
    return buf.read()

def upload_zip_and_set_metafield(product_id, filename, files, explicit_version: int | None = None):
    # files is list of { filename, content(bytes), content_type }
    zip_bytes = zip_files_to_bytes(files)
    # sanitize base name server-side as well (without extension)
    base = (filename or '').strip().replace('\n',' ').replace('\r',' ')
    for ch in '<>:"/\\|?*':
        base = base.replace(ch, '')
    base = '_'.join([p for p in base.split() if p])
    if base.lower().endswith('.zip'):
        base = base[:-4]
    if not base:
        base = 'artwork_templates'

    if explicit_version and isinstance(explicit_version, int) and explicit_version >= 1:
        next_version = explicit_version
    else:
        # Compute next version based on existing files in Shopify Admin > Files
        next_version = 1
        try:
            import sys as _sys
            import os as _os
            _sys.path.append(_os.path.join(_os.path.dirname(__file__), '..'))
            from Artwork_Updater import fetch_files_with_graphql  # type: ignore
            existing = fetch_files_with_graphql() or []
            import re as _re
            pattern = _re.compile(rf"^{_re.escape(base)}_(\\d+)\\.zip$", _re.IGNORECASE)
            for f in existing:
                name = f.get('filename') or f.get('alt') or ''
                if not name and f.get('url'):
                    # derive from URL tail if needed
                    url_tail = f.get('url').split('/')[-1].split('?')[0]
                    name = url_tail
                m = pattern.match(str(name))
                if m:
                    try:
                        v = int(m.group(1))
                        if v >= next_version:
                            next_version = v + 1
                    except Exception:
                        continue
        except Exception:
            next_version = 1 if next_version < 1 else next_version

    versioned_filename = f"{base}_{next_version}.zip"

    staged_target = staged_upload(versioned_filename, 'application/zip')
    ok = upload_bytes_to_staged(staged_target, zip_bytes, 'application/zip')
    if not ok:
        raise RuntimeError('Failed uploading ZIP to staged target')
    file_gid = file_create_from_staged(staged_target, '')
    # file_gid is a global id already
    set_metafield_artworktemplates(product_id, file_gid)
    return {'success': True, 'file_gid': file_gid}

if __name__ == '__main__':
    print('Templates Uploader script loaded')


