from flask import Flask, render_template, jsonify, Response, make_response, request, session, redirect, url_for
import os
import subprocess
import requests
import time
import threading
import sys
from datetime import datetime
import json

from config import ACCESS_TOKEN, API_VERSION, STORE_DOMAIN, FLASK_SECRET_KEY, FLASK_SESSION_SECURE, STOREFRONT_URL, MAX_UPLOAD_MB, PORTAL_PAGE_URL  # type: ignore
from portal_auth import (  # type: ignore
    check_staff_credentials,
    is_staff_authenticated,
    login_staff,
    logout_staff,
    establish_client_session,
    get_client_customer_id,
    get_client_email,
    get_client_shop_url,
    clear_client_session,
    is_client_path,
    is_staff_public_path,
    can_access_order,
)
from maintenance import init_maintenance  # type: ignore
from dev_browser import init_dev_browser  # type: ignore

print(f"🔧 Config loaded — STORE_DOMAIN={'✅ set (' + STORE_DOMAIN[:20] + '...)' if STORE_DOMAIN else '❌ EMPTY'}, "
      f"ACCESS_TOKEN={'✅ set' if ACCESS_TOKEN else '❌ EMPTY'}, API_VERSION={API_VERSION}", flush=True)

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# Max upload size (artwork/proof files); matches Office API default cap
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024

# Re-read HTML templates from disk on each request so UI edits show up on a refresh
# (Flask caches compiled templates when debug is off). Negligible overhead for this app.
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

app.config['SECRET_KEY'] = FLASK_SECRET_KEY
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = FLASK_SESSION_SECURE
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7

print("🔐 Staff login enabled", flush=True)

# Tracks in-flight requests and dumps thread stacks when the pool saturates.
# Registered first so every request is accounted for; it never short-circuits,
# so the maintenance/auth ordering below is unaffected.
try:
    from scripts.thread_watchdog import init_watchdog as _init_watchdog  # type: ignore
    _init_watchdog(app)
except Exception as _wd_err:
    print(f"⚠️ Thread watchdog not started: {_wd_err}", flush=True)

# Registered before portal_auth_gate below: Flask runs before_request handlers
# in registration order, so the maintenance page must win over the staff auth
# redirect. Also registers /healthz and /maint-exit.
init_maintenance(app)

# Read-only Dev file browser (/app/Dev). Staff-only via portal_auth_gate.
init_dev_browser(app)

# Background product-save worker (write-behind saves). Guarded by SAVE_WORKER_ENABLED.
try:
    from scripts.product_save_worker import start_worker as _start_save_worker  # type: ignore
    _start_save_worker(app)
except Exception as _sw_err:
    print(f"⚠️ Save worker not started: {_sw_err}", flush=True)

# Warm the customers overview off the request path so the first staff visit
# after boot does not compete with Render's /healthz for a free gunicorn thread.
try:
    from scripts.Customers import warm_customers_cache_async as _warm_customers  # type: ignore

    def _warm_caches_soon():
        time.sleep(2)  # let gunicorn finish binding before we hit Shopify
        try:
            _warm_customers()
        except Exception as _warm_err:
            print(f"⚠️ Customers cache warm skipped: {_warm_err}", flush=True)

    threading.Thread(target=_warm_caches_soon, daemon=True).start()
except Exception as _warm_imp_err:
    print(f"⚠️ Customers cache warm not scheduled: {_warm_imp_err}", flush=True)


@app.errorhandler(413)
def request_entity_too_large(_e):
    if (request.path or "").startswith("/api/"):
        return jsonify({
            "success": False,
            "error": f"File too large (max {MAX_UPLOAD_MB} MB)",
        }), 413
    return make_response("File too large", 413)


@app.errorhandler(404)
def api_not_found(_e):
    if (request.path or "").startswith("/api/"):
        return jsonify({"success": False, "error": "Not found"}), 404
    return make_response("Not Found", 404)


@app.errorhandler(500)
def api_internal_error(_e):
    if (request.path or "").startswith("/api/"):
        return jsonify({"success": False, "error": "Internal server error"}), 500
    return make_response("Internal Server Error", 500)


@app.before_request
def portal_auth_gate():
    path = request.path or ""
    if path.startswith("/static/"):
        return None
    if request.method == "OPTIONS":
        return None
    if is_staff_public_path(path) or is_client_path(path):
        return None
    if is_staff_authenticated():
        return None
    if path.startswith("/api/"):
        return jsonify({"success": False, "error": "Staff login required"}), 401
    return redirect(url_for("staff_login", next=path))


@app.route("/staff/login", methods=["GET", "POST"])
def staff_login():
    if is_staff_authenticated():
        return redirect(request.args.get("next") or url_for("index"))
    next_url = request.args.get("next") or "/"
    in_iframe = request.headers.get("Sec-Fetch-Dest") == "iframe"
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if check_staff_credentials(username, password):
            login_staff()
            dest = request.form.get("next") or request.args.get("next") or url_for("index")
            if not dest.startswith("/") or dest.startswith("//"):
                dest = url_for("index")
            return redirect(dest)
        return render_template(
            "UI/Staff_Login.html",
            error="Invalid username or password",
            next_url=next_url,
            in_iframe=in_iframe,
        )
    return render_template("UI/Staff_Login.html", next_url=next_url, in_iframe=in_iframe)


@app.route("/staff/logout")
def staff_logout():
    logout_staff()
    return redirect(url_for("staff_login"))


@app.route("/client/orders")
@app.route("/portal")
def client_orders_page():
    customer_id = request.args.get("customer_id")
    email = request.args.get("email")
    shop_url = (request.args.get("shop_url") or "").strip()
    if customer_id and email:
        from scripts.Client_Orders import verify_customer  # type: ignore
        if verify_customer(customer_id, email):
            establish_client_session(customer_id, email, shop_url=shop_url or None)
        else:
            return render_template(
                "UI/Client_Orders.html",
                error="We couldn't verify your account. Please open this page from your profile on the store.",
                profile=None,
                orders=[],
                logout_url=_client_logout_url(),
                deep_link={"order": "", "item": "", "proof": ""},
            )
    cid = get_client_customer_id()
    if not cid:
        return render_template(
            "UI/Client_Orders.html",
            error="Please open this page from your account on the store.",
            profile=None,
            orders=[],
            logout_url=_client_logout_url(),
            deep_link={"order": "", "item": "", "proof": ""},
        )
    try:
        from scripts.Client_Orders import get_customer_orders, get_customer_profile  # type: ignore
        profile_result = get_customer_profile(cid)
        profile = profile_result.get("profile") if profile_result.get("success") else None
        orders_result = get_customer_orders(cid)
        orders = orders_result.get("orders") or [] if orders_result.get("success") else []
    except Exception as e:
        print(f"Client portal error: {e}", flush=True)
        return render_template(
            "UI/Client_Orders.html",
            error="Sorry, we couldn't load your account right now. Please try again later.",
            profile=None,
            orders=[],
            logout_url=_client_logout_url(),
            deep_link={"order": "", "item": "", "proof": ""},
        )
    deep_link = {
        "order": (request.args.get("order") or "").strip(),
        "item": (request.args.get("item") or "").strip(),
        "proof": (request.args.get("proof") or "").strip(),
        "action": (request.args.get("action") or "").strip(),
    }
    return render_template(
        "UI/Client_Orders.html",
        profile=profile,
        orders=orders,
        error=None,
        logout_url=_client_logout_url(),
        deep_link=deep_link,
    )


def _client_logout_url() -> str:
    base = get_client_shop_url() or STOREFRONT_URL
    return f"{base.rstrip('/')}/account/logout"


@app.route("/portal-register")
def client_register_page():
    shop_url = (request.args.get("shop_url") or "").strip()
    return render_template(
        "UI/Client_Register.html",
        shop_url=shop_url,
        storefront_url=STOREFRONT_URL,
        portal_page_url=PORTAL_PAGE_URL,
    )


@app.route("/api/client/check-email", methods=["POST"])
def api_client_check_email():
    """Public: check if email exists in Shopify; return prefilled login URL when it does."""
    data = request.get_json(silent=True) or {}
    try:
        from scripts.Client_Orders import check_client_email  # type: ignore
        result = check_client_email(data)
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/client/register", methods=["POST"])
def api_client_register():
    """Public: create a new Shopify customer (Pending tag) from the registration form."""
    data = request.get_json(silent=True) or {}
    try:
        from scripts.Client_Orders import register_client_customer  # type: ignore
        result = register_client_customer(data)
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/client/profile", methods=["GET", "PUT"])
def api_client_profile():
    cid = get_client_customer_id()
    if not cid:
        return jsonify({"success": False, "error": "Not signed in as a customer"}), 403
    try:
        from scripts.Client_Orders import get_customer_profile, update_client_profile  # type: ignore
        if request.method == "PUT":
            data = request.get_json(silent=True) or {}
            result = update_client_profile(cid, data)
            if not result.get("success"):
                return jsonify(result), 400
            return jsonify(result)
        return jsonify(get_customer_profile(cid))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/client/logout", methods=["POST"])
def api_client_logout():
    clear_client_session()
    return jsonify({"success": True, "logout_url": _client_logout_url()})


@app.route("/api/client/orders")
def api_client_orders():
    cid = get_client_customer_id()
    if not cid:
        return jsonify({"success": False, "error": "Not signed in as a customer"}), 403
    try:
        from scripts.Client_Orders import get_customer_orders  # type: ignore
        return jsonify(get_customer_orders(cid))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.after_request
def add_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    response.headers['Content-Security-Policy'] = "frame-ancestors *"
    return response

# Dynamically detect available tools (scripts) by listing filenames in scripts folder
def get_tools():
    scripts_dir = os.path.join(os.path.dirname(__file__), 'scripts')
    files = [f[:-3] for f in os.listdir(scripts_dir)
             if f.endswith('.py') and f not in (
                 'app.py', '__init__.py', 'Customers.py', 'Client_Orders.py', 'Orders.py',
                 'Diary.py', 'diary_store.py', 'diary_helpers.py',
             )]
    return files

@app.route('/api/health')
def api_health():
    """Quick diagnostic: checks config and Shopify connectivity."""
    info = {
        "store_domain": STORE_DOMAIN[:25] + "..." if len(STORE_DOMAIN) > 25 else STORE_DOMAIN or "(empty)",
        "api_version": API_VERSION,
        "access_token_set": bool(ACCESS_TOKEN),
    }
    if STORE_DOMAIN and ACCESS_TOKEN:
        try:
            url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/shop.json"
            r = requests.get(url, headers={"X-Shopify-Access-Token": ACCESS_TOKEN}, timeout=10)
            info["shopify_status"] = r.status_code
            if r.status_code == 200:
                shop = r.json().get("shop", {})
                info["shop_name"] = shop.get("name", "?")
            else:
                info["shopify_body"] = r.text[:200]
        except Exception as e:
            info["shopify_error"] = f"{type(e).__name__}: {e}"
    else:
        info["shopify_status"] = "skipped — missing config"
    return jsonify(info)

@app.route('/api/perf-check')
def api_perf_check():
    """Where is the time actually going?

    Page data is served from cache, so when the site feels slow it is nearly
    always one of the things underneath: the office server (every cached read
    goes through it) or Shopify. Times each separately and reports whether this
    instance's caches are warm — each instance has its own, so a freshly scaled
    instance starts cold.
    """
    out = {'instance': os.environ.get('RENDER_INSTANCE_ID', '?')}

    # Sampled first: the timed calls below take ~1s, by which point other
    # requests may have finished. Includes this request itself.
    try:
        from scripts import thread_watchdog
        out['inflight'] = thread_watchdog.snapshot()
    except Exception as e:
        out['inflight_error'] = f"{type(e).__name__}: {e}"

    start = time.perf_counter()
    try:
        from scripts import office_api
        office_api.get_snapshot('parent_child_tree')
        out['office_ms'] = round((time.perf_counter() - start) * 1000)
    except Exception as e:
        out['office_ms'] = round((time.perf_counter() - start) * 1000)
        out['office_error'] = f"{type(e).__name__}: {e}"

    start = time.perf_counter()
    try:
        r = requests.get(
            f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/shop.json",
            headers={"X-Shopify-Access-Token": ACCESS_TOKEN},
            timeout=15,
        )
        out['shopify_ms'] = round((time.perf_counter() - start) * 1000)
        out['shopify_status'] = r.status_code
        # "32/40" means 32 of 40 cost points used — near the cap means throttling.
        out['shopify_call_limit'] = r.headers.get('X-Shopify-Shop-Api-Call-Limit')
    except Exception as e:
        out['shopify_ms'] = round((time.perf_counter() - start) * 1000)
        out['shopify_error'] = f"{type(e).__name__}: {e}"

    try:
        from scripts.product_creator import Product_Creator as pc
        overview_at = pc._PRODUCTS_OVERVIEW_CACHE_AT
        out['cache'] = {
            'products_overview_warm': pc._PRODUCTS_OVERVIEW_CACHE is not None,
            'products_overview_age_s': round(time.time() - overview_at) if overview_at else None,
            'named_snapshots_warm': sorted(pc._NAMED_CACHE.keys()),
            'product_details_cached': len(pc._PRODUCT_DETAIL_CACHE),
        }
    except Exception as e:
        out['cache_error'] = f"{type(e).__name__}: {e}"

    try:
        from scripts import product_save_queue as queue
        start = time.perf_counter()
        jobs = queue.list_jobs()
        out['queue_list_ms'] = round((time.perf_counter() - start) * 1000)
        out['queue_jobs'] = len(jobs)
        out['queue_active'] = sum(1 for j in jobs if j.get('status') in ('queued', 'running'))
    except Exception as e:
        out['queue_error'] = f"{type(e).__name__}: {e}"

    return jsonify(out)


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


@app.route('/api/live-products-count')
def api_live_products_count():
    """Return the number of active (live) products on the store."""
    try:
        import sys
        sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
        from Price_Bandit import get_all_products  # type: ignore
        products = get_all_products()
        return jsonify({'success': True, 'count': len(products)})
    except Exception as e:
        try:
            print(f"💥 Live products count error: {str(e)}")
        except (OSError, ValueError):
            pass
        return jsonify({'success': False, 'count': 0})

# Full Shopify Content > Files list is expensive (paginated GraphQL). Cache in
# this process so concurrent Product Creator tabs don't each hold a request
# thread for the entire scan. Singleflight: one rebuild at a time.
_SHOPIFY_FILES_CACHE = {"at": 0.0, "files": None}
_SHOPIFY_FILES_LOCK = threading.Lock()
_SHOPIFY_FILES_BUILDING = False
try:
    from config import SHOPIFY_FILES_MEM_TTL  # type: ignore
except Exception:
    SHOPIFY_FILES_MEM_TTL = 120


def _invalidate_shopify_files_cache():
    with _SHOPIFY_FILES_LOCK:
        _SHOPIFY_FILES_CACHE["at"] = 0.0
        _SHOPIFY_FILES_CACHE["files"] = None


def _build_shopify_files_cache():
    """Fetch Shopify Files into the in-process cache. Caller owns the build flag."""
    global _SHOPIFY_FILES_BUILDING
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
    from Artwork_Updater import fetch_files_with_graphql  # type: ignore
    try:
        files = fetch_files_with_graphql() or []
        with _SHOPIFY_FILES_LOCK:
            _SHOPIFY_FILES_CACHE["files"] = files
            _SHOPIFY_FILES_CACHE["at"] = time.time()
        try:
            print(f"📁 Loaded {len(files)} files (cached {SHOPIFY_FILES_MEM_TTL}s)", flush=True)
        except (OSError, ValueError):
            pass
        return files
    finally:
        with _SHOPIFY_FILES_LOCK:
            _SHOPIFY_FILES_BUILDING = False


@app.route('/api/shopify/files')
def api_shopify_files():
    global _SHOPIFY_FILES_BUILDING
    try:
        now = time.time()
        refresh = (request.args.get("refresh") or "").strip().lower() in ("1", "true", "yes")
        ttl = float(SHOPIFY_FILES_MEM_TTL)

        with _SHOPIFY_FILES_LOCK:
            cached = _SHOPIFY_FILES_CACHE.get("files")
            age = now - float(_SHOPIFY_FILES_CACHE.get("at") or 0)
            fresh = cached is not None and age < ttl
            building = _SHOPIFY_FILES_BUILDING
            if fresh and not refresh:
                return jsonify(cached)

            # Stale-while-revalidate: return the last list immediately and rebuild
            # in a background thread so this request (and /healthz) stay free.
            if cached is not None and not refresh:
                if not building:
                    _SHOPIFY_FILES_BUILDING = True
                    threading.Thread(target=_build_shopify_files_cache, daemon=True).start()
                return jsonify(cached)

            # Cold miss (or explicit refresh with no cache yet): one thread builds.
            if building:
                claim = False
            else:
                _SHOPIFY_FILES_BUILDING = True
                claim = True

        if not claim:
            # Wait briefly for the in-flight cold build; do not hold a thread for
            # the full Shopify pagination (that is what starved /healthz before).
            for _ in range(40):
                time.sleep(0.25)
                with _SHOPIFY_FILES_LOCK:
                    cached = _SHOPIFY_FILES_CACHE.get("files")
                    if cached is not None:
                        return jsonify(cached)
                    if not _SHOPIFY_FILES_BUILDING:
                        break
            return jsonify([])

        files = _build_shopify_files_cache()
        return jsonify(files)
    except Exception as e:
        with _SHOPIFY_FILES_LOCK:
            _SHOPIFY_FILES_BUILDING = False
        try:
            print(f"💥 Error loading files: {str(e)}", flush=True)
        except (OSError, ValueError):
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

            if isinstance(result, dict) and result.get('success'):
                print(f"✅ Upload successful: {file.filename}")
                _invalidate_shopify_files_cache()
                return jsonify({
                    'success': True,
                    'filename': result.get('filename') or file.filename,
                    'message': 'File uploaded successfully to Shopify',
                    'id': result.get('id'),
                    'global_id': result.get('global_id'),
                    'content_type': file.content_type,
                    'size': os.path.getsize(temp_file_path),
                    'created_at': datetime.now().isoformat(),
                })
            else:
                error_msg = (result.get('error') if isinstance(result, dict) else None) or 'Upload function returned no result'
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
def update_products_to_file():
    """Update products to use a specific file"""
    try:
        print(f"[API] Update products to file endpoint called")
        data = request.get_json() or {}
        print(f"[API] Received data: {data}")

        target_filename = data.get('targetFilename')
        column = data.get('column')
        target_file_id = data.get('targetFileId')
        target_file_global_id = data.get('targetFileGlobalId')

        if not target_filename and not target_file_global_id and not target_file_id:
            return jsonify({'success': False, 'error': 'No target filename or file id provided'}), 400

        from scripts.Artwork_Updater import update_products_to_specific_file  # type: ignore

        result = update_products_to_specific_file(
            target_filename,
            column,
            target_file_id=target_file_id,
            target_file_global_id=target_file_global_id,
        )

        print(f"[API] Update function returned: {result}")

        if result.get('error'):
            return jsonify({'success': False, **result}), 400

        return jsonify({'success': True, **result})

    except Exception as e:
        print(f"[ERROR] Update products to file failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'updatedCount': 0,
            'totalCount': 0
        }), 500

def _parse_product_id(product_id):
    """Return positive int product ID or None if invalid."""
    if product_id is None or (isinstance(product_id, str) and not product_id.strip()):
        return None
    try:
        pid = int(product_id)
        return pid if pid > 0 else None
    except (TypeError, ValueError):
        return None


@app.route('/api/product/<product_id>')
def api_product_detail(product_id):
    try:
        pid = _parse_product_id(product_id)
        if pid is None:
            return jsonify({"error": "Invalid product ID"}), 400
        product_id = pid
        import sys
        import os
        sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
        
        from Field_Finder import fetch_all_metafields  # type: ignore
        
        headers = {"X-Shopify-Access-Token": ACCESS_TOKEN}
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        response, err = _shopify_get_with_retry(url, headers)
        if err:
            return jsonify({"error": "Failed to fetch product", "detail": err.get("detail", "")}), 400
        if response.status_code != 200:
            err_body = response.text[:500] if response.text else ""
            return jsonify({"error": "Failed to fetch product", "detail": err_body}), 400
        product_data = response.json().get("product", {})
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

def _shopify_get_with_retry(url, headers, max_retries=2):
    """GET request to Shopify with 429 rate-limit retry. Returns (response, None) or (None, error_dict)."""
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
        except requests.exceptions.Timeout:
            print(f"⚠️ Shopify GET timeout (attempt {attempt+1}/{max_retries+1}): {url[:80]}", flush=True)
            if attempt < max_retries:
                continue
            return None, {"error": "Request timed out", "detail": f"Shopify API did not respond after {max_retries + 1} attempts"}
        except requests.exceptions.RequestException as e:
            print(f"❌ Shopify GET error (attempt {attempt+1}/{max_retries+1}): {type(e).__name__}: {e}", flush=True)
            return None, {"error": f"Connection failed: {type(e).__name__}", "detail": str(e)[:300]}
        if resp.status_code == 429:
            if attempt < max_retries:
                time.sleep(2)
                continue
            return None, {"error": "Rate limit exceeded", "detail": resp.text[:500] if resp.text else ""}
        return resp, None
    return None, {"error": "Request failed", "detail": ""}


@app.route('/api/product/<product_id>/prices')
def api_product_prices(product_id):
    """Special endpoint for Price Manager that returns all metafields including pricejson ones.

    Served from the shared office snapshot (stale-while-revalidate) so opening a
    product is instant; pass ?refresh=1 to force a background rebuild from Shopify.
    """
    try:
        pid = _parse_product_id(product_id)
        if pid is None:
            return jsonify({"error": "Invalid product ID"}), 400
        # A queued/running save fully locks the product so it can't be opened.
        try:
            from scripts import product_save_queue as queue
            if pid in set(queue.locked_product_ids()):
                return jsonify({
                    "error": "This product is being saved and is temporarily locked.",
                    "locked": True
                }), 423
        except Exception:
            pass
        from scripts.product_creator.Product_Creator import get_product_detail
        refresh = (request.args.get('refresh') or '').lower() in ('1', 'true', 'yes')
        formatted_product = get_product_detail(pid, refresh=refresh)
        if not formatted_product or not formatted_product.get('id'):
            return jsonify({"error": "Failed to fetch product"}), 400
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

        if key == "unit_weight":
            from scripts.product_creator.Product_Creator import normalize_unit_weight_value  # type: ignore
            value = normalize_unit_weight_value(value)

        metafield_id = create_metafield(product_id, namespace, key, value, metafield_type)
        
        if metafield_id:
            try:
                from scripts.product_creator.Product_Creator import sync_product_snapshot
                sync_product_snapshot(product_id)
            except Exception:
                pass
            return jsonify({"message": "Metafield created successfully", "id": metafield_id})
        else:
            return jsonify({"error": "Failed to create metafield"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/update_metafield', methods=['POST'])
def api_update_metafield():
    """Update a product metafield using Product Manager's create_metafields (same code path as product editor)."""
    try:
        data = request.get_json()
        product_id = data.get('product_id')
        metafield_key = data.get('metafield_key')
        metafield_value = data.get('metafield_value')

        if not all([product_id, metafield_key, metafield_value is not None]):
            return jsonify({'error': 'Missing required fields'}), 400

        # REST uses numeric product ID (not GID)
        if isinstance(product_id, str) and product_id.startswith("gid://"):
            try:
                product_id = product_id.split("/")[-1]
            except Exception:
                pass
        product_id = str(product_id).strip()
        try:
            product_id_int = int(product_id)
        except ValueError:
            product_id_int = product_id

        if isinstance(metafield_value, (list, dict)):
            value_to_save = json.dumps(metafield_value, separators=(',', ': '))
        else:
            value_to_save = str(metafield_value)

        metafield_type = data.get('metafield_type') or "single_line_text_field"
        if metafield_key in ("pricejsontr", "pricejsoner"):
            metafield_type = "single_line_text_field"

        from scripts.product_creator.Product_Creator import create_metafields

        metafields_data = [
            {
                "namespace": "custom",
                "key": metafield_key,
                "value": value_to_save,
                "type": metafield_type,
            }
        ]
        print(f"[update_metafield] product_id={product_id} key={metafield_key} type={metafield_type} value_len={len(value_to_save)} (using Product Manager create_metafields)", flush=True)

        result = create_metafields(product_id_int, metafields_data, shopify_domain=None)

        if not result.get("success") or result.get("success_count", 0) < 1:
            errors = result.get("errors", [])
            msg = "; ".join(errors) if errors else "Metafield save failed"
            print(f"[update_metafield] create_metafields failed: {errors}", flush=True)
            return jsonify({"error": msg}), 400

        print(f"[update_metafield] Success for {metafield_key}", flush=True)
        try:
            run_price_bandit_for_product(product_id)
        except Exception as e:
            print(f"⚠️ Price Bandit run failed: {str(e)}")
        try:
            from scripts.product_creator.Product_Creator import sync_product_snapshot
            sync_product_snapshot(product_id)
        except Exception:
            pass
        return jsonify({"success": True, "message": "Metafield updated successfully and Price Bandit triggered"})

    except Exception as e:
        print(f"💥 Metafield update error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/update_price_metafields', methods=['POST'])
def api_update_price_metafields():
    """Save both price metafields (trade + end customer) in one call, then run Price Bandit once. Faster than two separate update_metafield calls."""
    try:
        data = request.get_json()
        product_id = data.get('product_id')
        trade = data.get('trade')  # array for pricejsontr
        end_customer = data.get('end_customer')  # array for pricejsoner

        if not product_id:
            return jsonify({'error': 'Missing product_id'}), 400
        if (not trade or not isinstance(trade, list)) and (not end_customer or not isinstance(end_customer, list)):
            return jsonify({'error': 'Provide at least one of trade or end_customer (arrays)'}), 400

        if isinstance(product_id, str) and product_id.startswith("gid://"):
            try:
                product_id = product_id.split("/")[-1]
            except Exception:
                pass
        product_id = str(product_id).strip()
        try:
            product_id_int = int(product_id)
        except ValueError:
            product_id_int = product_id

        from scripts.product_creator.Product_Creator import create_metafields

        metafields_data = []
        if trade and isinstance(trade, list):
            metafields_data.append({
                "namespace": "custom",
                "key": "pricejsontr",
                "value": json.dumps(trade, separators=(',', ': ')),
                "type": "single_line_text_field",
            })
        if end_customer and isinstance(end_customer, list):
            metafields_data.append({
                "namespace": "custom",
                "key": "pricejsoner",
                "value": json.dumps(end_customer, separators=(',', ': ')),
                "type": "single_line_text_field",
            })

        if not metafields_data:
            return jsonify({"error": "No valid price data to save"}), 400

        print(f"[update_price_metafields] product_id={product_id} saving {len(metafields_data)} metafields (batch)", flush=True)
        result = create_metafields(product_id_int, metafields_data, shopify_domain=None)

        expected = len(metafields_data)
        success_count = result.get("success_count", 0)
        if not result.get("success") or success_count < expected:
            errors = result.get("errors", [])
            msg = "; ".join(errors) if errors else f"Saved {success_count}/{expected} metafields"
            print(f"[update_price_metafields] partial/fail: {errors}", flush=True)
            return jsonify({"error": msg, "saved": success_count, "total": expected}), 400

        print(f"[update_price_metafields] Success for product {product_id}", flush=True)
        try:
            run_price_bandit_for_product(product_id)
        except Exception as e:
            print(f"⚠️ Price Bandit run failed: {str(e)}")
        try:
            from scripts.product_creator.Product_Creator import sync_product_snapshot
            sync_product_snapshot(product_id)
        except Exception:
            pass
        return jsonify({"success": True, "message": "Price metafields saved and Price Bandit triggered"})

    except Exception as e:
        print(f"💥 update_price_metafields error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/bulk-update-field', methods=['POST'])
def api_bulk_update_field():
    """
    Bulk-update a single column across many products from the All Products page.

    Body: { "column": "<key>", "updates": [ { "id": <product_id>,
                                              "title": "<new title>"?,        # title column only
                                              "metafields": [ {namespace,key,type,value}, ... ]? } ] }

    Each product is updated independently using the same code path as Product Manager
    (create_metafields), so list/clearable handling, rate-limit retries and redirects
    all behave identically. Title updates use a product PUT.
    """
    try:
        data = request.get_json() or {}
        column = data.get('column')
        updates = data.get('updates') or []
        if not isinstance(updates, list) or not updates:
            return jsonify({"error": "No updates provided"}), 400

        LONG_TEXT_BULK_COLUMNS = frozenset({
            "description", "productinfo", "ingredients", "nutritional_info",
            "whats_inside", "print_info", "recycle_info",
        })
        BULK_LONG_TEXT_MAX = 20

        if column in LONG_TEXT_BULK_COLUMNS and len(updates) > BULK_LONG_TEXT_MAX:
            return jsonify({
                "error": (
                    f"Long-text columns can only update up to {BULK_LONG_TEXT_MAX} products "
                    f"per save (you have {len(updates)}). Edit fewer rows or save in batches."
                ),
            }), 400

        from scripts.product_creator.Product_Creator import create_metafields

        domain = STORE_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
        headers = {"X-Shopify-Access-Token": ACCESS_TOKEN, "Content-Type": "application/json"}

        saved = 0
        failed = 0
        errors = []
        touched_ids = set()

        def _normalize_id(pid):
            if isinstance(pid, str) and pid.startswith("gid://"):
                pid = pid.split("/")[-1]
            try:
                return int(str(pid).strip())
            except (TypeError, ValueError):
                return None

        for i, upd in enumerate(updates):
            if not isinstance(upd, dict):
                continue
            pid = _normalize_id(upd.get('id'))
            if pid is None:
                failed += 1
                errors.append(f"Invalid product id: {upd.get('id')}")
                continue
            touched_ids.add(pid)

            # Light pacing between products to stay within Shopify's REST bucket
            if i > 0:
                time.sleep(0.2)

            try:
                # Title is a product field, not a metafield
                if 'title' in upd:
                    new_title = str(upd.get('title') or '').strip()
                    if not new_title:
                        failed += 1
                        errors.append(f"Product {pid}: title cannot be empty")
                        continue
                    url = f"https://{domain}/admin/api/{API_VERSION}/products/{pid}.json"
                    payload = {"product": {"id": pid, "title": new_title}}
                    r = requests.put(url, headers=headers, json=payload, allow_redirects=True)
                    if r.status_code in (200, 201):
                        saved += 1
                    else:
                        failed += 1
                        errors.append(f"Product {pid}: title update failed ({r.status_code})")
                    continue

                metafields = upd.get('metafields') or []
                if not metafields:
                    continue
                result = create_metafields(pid, metafields, shopify_domain=domain or None)
                expected = len(metafields)
                got = result.get("success_count", 0)
                if result.get("success") and got >= expected:
                    saved += 1
                else:
                    failed += 1
                    errs = result.get("errors", [])
                    errors.append(f"Product {pid}: " + ("; ".join(errs) if errs else f"saved {got}/{expected}"))
            except Exception as e:
                failed += 1
                errors.append(f"Product {pid}: {e}")

        print(f"[bulk-update-field] column={column} saved={saved} failed={failed}", flush=True)
        if touched_ids:
            try:
                from scripts.product_creator.Product_Creator import (
                    invalidate_product_detail_cache,
                    _kick_products_refresh,
                )
                for tid in touched_ids:
                    invalidate_product_detail_cache(tid)
                # One background overview rebuild so the All Products list converges.
                _kick_products_refresh()
            except Exception:
                pass
        return jsonify({
            "success": failed == 0,
            "saved": saved,
            "failed": failed,
            "errors": errors[:50],
        })
    except Exception as e:
        print(f"💥 bulk-update-field error: {str(e)}")
        import traceback
        traceback.print_exc()
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
    if tool_name == 'All_Products':
        return redirect('/app/Products?view=all')

    if tool_name == 'Product_Creator':
        if request.args.get('embed') == '1':
            response = make_response(render_template('UI/Product_Creator.html'))
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
        qs = request.query_string.decode('utf-8')
        target = '/app/Products?view=manager'
        if qs:
            target += '&' + qs
        return redirect(target)

    if tool_name == 'Products':
        response = make_response(render_template('UI/Products.html'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    template_path = f'UI/{tool_name}.html'
    try:
        return render_template(template_path)
    except Exception:
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

def _parse_product_form(req):
    """Parse a create/enqueue product request (multipart or JSON) into the
    create_product() input dict.

    Returns (data, error) where error is a (payload_dict, status_code) tuple on
    an unsupported content type, else None. Shared by /api/create-product and the
    background /api/product-queue enqueue endpoint.
    """
    # Multipart form data (with or without files).
    if req.content_type and req.content_type.startswith('multipart/form-data'):
        data = {}
        for key, value in req.form.items():
            if key.startswith('media_'):
                continue  # Media files live in req.files
            if key in ['metafields', 'charge_vat', 'colour_images', 'categories', 'subcategories', 'storefront_options', 'is_calendar']:
                try:
                    if key == 'metafields':
                        data[key] = json.loads(value) if (value and value.strip()) else []
                    elif key in ('charge_vat', 'is_calendar'):
                        data[key] = value.lower() in ['true', '1', 'yes'] if isinstance(value, str) else bool(value)
                    elif key == 'colour_images':
                        data[key] = json.loads(value) if (value and value.strip()) else {}
                    elif key in ('categories', 'subcategories'):
                        if value and value.strip():
                            parsed = json.loads(value)
                            data[key] = parsed if isinstance(parsed, list) else [parsed]
                        else:
                            data[key] = []
                    elif key == 'storefront_options':
                        if value and value.strip():
                            parsed = json.loads(value)
                            data[key] = parsed if isinstance(parsed, dict) else {}
                        else:
                            data[key] = {}
                    else:
                        data[key] = value
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"⚠️ Failed to parse {key}: {e}", flush=True)
                    data[key] = value
            else:
                data[key] = value

        # Media files (new format, with fallback to media_${index}).
        media_files = []
        if 'media_files' in req.files:
            for file in req.files.getlist('media_files'):
                if file and file.filename:
                    media_files.append({'filename': file.filename, 'content': file.read(), 'content_type': file.content_type})
                    print(f"[API] Added media file: {file.filename} ({file.content_type})")
        else:
            media_count = int(req.form.get('media_count', 0))
            for i in range(media_count):
                file_key = f'media_{i}'
                if file_key in req.files:
                    file = req.files[file_key]
                    if file and file.filename:
                        media_files.append({'filename': file.filename, 'content': file.read(), 'content_type': file.content_type})
        data['media_files'] = media_files

        # Selected Shopify media IDs to keep. Only set when the editor sent a
        # media state (media_order present) — an omitted key means "leave images
        # alone", while media_order=[] with no ids means "delete all".
        shopify_media_ids = req.form.getlist('shopify_media_ids')
        if shopify_media_ids:
            data['shopify_media_ids'] = [int(i) if i.isdigit() else i for i in shopify_media_ids]
        elif 'media_order' in req.form:
            data['shopify_media_ids'] = []

        data['media_explicitly_cleared'] = req.form.get('media_explicitly_cleared', 'false').lower() in ('true', '1', 'yes')
        data['main_image_to_children'] = req.form.get('main_image_to_children', 'false').lower() in ('true', '1', 'yes')

        removals_str = req.form.get('family_image_removals', '')
        if removals_str and removals_str.strip():
            try:
                parsed = json.loads(removals_str)
                data['family_image_removals'] = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, ValueError):
                data['family_image_removals'] = []
        else:
            data['family_image_removals'] = []

        if 'media_order' in req.form:
            media_order_str = req.form.get('media_order') or '[]'
            try:
                data['media_order'] = json.loads(media_order_str) if media_order_str else []
            except (json.JSONDecodeError, ValueError):
                data['media_order'] = []

        media_urls_str = req.form.get('media_urls', '')
        if media_urls_str and media_urls_str.strip():
            try:
                parsed = json.loads(media_urls_str)
                data['media_urls'] = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, ValueError):
                data['media_urls'] = []
        else:
            data['media_urls'] = []
        return data, None

    # JSON body (backward compatibility).
    if req.is_json:
        data = req.get_json()
        if data is None:
            data = {}
        data.setdefault('media_files', [])
        return data, None

    return None, ({'success': False, 'error': f"Unsupported content type: {req.content_type}"}, 400)


@app.route('/api/create-product', methods=['POST'])
def api_create_product():
    """Create a new product in Shopify with media uploads (synchronous path)."""
    try:
        print(f"[API] Create product endpoint called")
        data, err = _parse_product_form(request)
        if err is not None:
            payload, status = err
            return jsonify(payload), status

        from scripts.product_creator.Product_Creator import create_product, validate_product_data

        validation = validate_product_data(data)
        if not validation["valid"]:
            return jsonify({
                'success': False,
                'error': f"Validation failed: {', '.join(validation['errors'])}"
            }), 400

        result = create_product(data)

        # Immediate Shopify → office cross-check for every product this save
        # touched (bypasses the 30-minute full-catalog TTL window).
        try:
            if isinstance(result, dict) and result.get('success'):
                from scripts.product_creator.Product_Creator import (
                    product_ids_from_save_result,
                    sync_products_after_save,
                )
                ids = product_ids_from_save_result(result)
                if ids:
                    sync_products_after_save(ids)
        except Exception as _sync_err:
            print(f"[API] product snapshot sync skipped: {_sync_err}", flush=True)

        return jsonify(result)

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Failed to create product: {str(e)}"
        }), 500


def _queue_extract_product_id(data):
    pid = data.get('product_id')
    if pid in (None, '', 'null'):
        return None
    try:
        return int(pid)
    except (TypeError, ValueError):
        return None


# Shared answer for the queue poll. Every open tab hits /api/product-queue on a
# timer; without this each one costs a separate office round trip.
_QUEUE_LIST_CACHE = {'at': 0.0, 'payload': None}
_QUEUE_LIST_TTL = 2.5
_QUEUE_LIST_LOCK = threading.Lock()


def _invalidate_queue_list_cache():
    """Drop the cached poll answer so a queue change shows up on the next poll."""
    _QUEUE_LIST_CACHE['at'] = 0.0


class _ThreadStdoutCapture:
    """Tee this thread's stdout into a buffer, leaving other threads alone.

    A synchronous save runs for minutes, and contextlib.redirect_stdout swaps
    sys.stdout for the whole process — with a single gunicorn worker running 12
    threads that swallows every other request's logging into this buffer for the
    duration of the save.
    """

    MAX_CHARS = 200_000

    def __init__(self):
        import io
        self._buf = io.StringIO()
        self._size = 0
        self._owner = threading.get_ident()
        self._prev = sys.stdout

    def write(self, s):
        if threading.get_ident() == self._owner and self._size < self.MAX_CHARS:
            self._buf.write(s)
            self._size += len(s)
        return self._prev.write(s)

    def flush(self):
        self._prev.flush()

    def getvalue(self):
        return self._buf.getvalue()

    def __enter__(self):
        sys.stdout = self
        return self

    def __exit__(self, *exc):
        sys.stdout = self._prev
        return False


@app.route('/api/product-queue', methods=['POST'])
def api_product_queue_enqueue():
    """Enqueue a write-behind product save.

    New image files are uploaded here, because binary content can't be parked in
    the queue store — but only the upload. Everything after it (metafields, Price
    Bandit, child propagation) goes to the background worker and is verified
    against Shopify, so a save never occupies this single-worker web process for
    longer than the upload takes.

    Falls back to a fully synchronous save when the job can't be made
    self-describing: a brand-new product (nothing to attach images to yet), a
    copy-from-URL duplicate, or the office queue store being down.
    """
    try:
        data, err = _parse_product_form(request)
        if err is not None:
            payload, status = err
            return jsonify(payload), status

        from scripts.product_creator.Product_Creator import (
            create_product,
            validate_product_data,
            product_ids_from_save_result,
            sync_products_after_save,
        )
        from scripts import product_save_queue as queue

        validation = validate_product_data(data)
        if not validation["valid"]:
            return jsonify({
                'success': False,
                'error': f"Validation failed: {', '.join(validation['errors'])}"
            }), 400

        product_id = _queue_extract_product_id(data)
        title = (data.get('title') or '').strip()

        # Refuse to queue a product that already has an active save (concurrency lock).
        try:
            if product_id and product_id in set(queue.locked_product_ids()):
                return jsonify({
                    'success': False,
                    'locked': True,
                    'error': 'This product already has a save in the queue.'
                }), 409
        except Exception:
            pass

        try:
            queue_ready = queue._available()
        except Exception:
            queue_ready = False

        # New images can't be parked in the queue store, so upload them now and
        # rewrite the job to reference the media IDs that came back. That keeps
        # the expensive part of the save (metafields, pricing, child propagation)
        # out of this single-worker web process. Editing an existing product only:
        # a brand-new product has nothing to attach images to yet.
        if queue_ready and product_id and data.get('media_files') and not data.get('media_urls'):
            try:
                from scripts.product_creator.Product_Creator import preupload_media_for_background_save
                preupload_media_for_background_save(product_id, data)
            except Exception as _ue:
                print(f"[API] media pre-upload skipped: {_ue}", flush=True)

        needs_sync = bool(data.get('media_files')) or bool(data.get('media_urls'))

        # Synchronous path: new images present, or the office queue store is down.
        if needs_sync or not queue_ready:
            cap = _ThreadStdoutCapture()
            try:
                with cap:
                    result = create_product(data)
            except Exception as exc:
                result = {'success': False, 'error': str(exc)}
            logs = cap.getvalue()

            success = bool(isinstance(result, dict) and result.get('success'))
            pid = None
            if isinstance(result, dict):
                pid = (result.get('product') or {}).get('id') or result.get('product_id')
            pid = pid or product_id

            verify = []
            if success and pid:
                try:
                    verify = queue.verify_product(data, pid)
                except Exception:
                    verify = []
                try:
                    ids = product_ids_from_save_result(
                        result if isinstance(result, dict) else {}, pid
                    )
                    sync_products_after_save(ids)
                except Exception as _e:
                    print(f"[API] snapshot sync skipped: {_e}", flush=True)

            ok = success and all(r.get('ok') for r in verify)
            job_id = None
            if queue_ready:
                try:
                    job = queue.enqueue(data, pid, title)
                    err_msg = None if ok else ((result or {}).get('error') if not success else 'verification mismatch')
                    queue.complete(job['job_id'], 'done' if ok else 'failed',
                                   verify=verify, logs=logs, error=err_msg)
                    job_id = job['job_id']
                except Exception as _qe:
                    print(f"[API] queue record skipped: {_qe}", flush=True)

            payload = dict(result) if isinstance(result, dict) else {'success': success}
            payload['queued'] = False
            payload['job_id'] = job_id
            payload['verify'] = verify
            return jsonify(payload), (200 if success else 500)

        # Background path: metadata-only edit — return instantly.
        # If this is a parent product, lock its children too — the save
        # propagates parent fields to every child in the family.
        # Resolved from the cached families tree: the live lookup paginates the
        # whole catalog and would stall this request (and the instance) for as
        # long as that takes. If the cache can't answer, the children simply
        # aren't greyed out until the tree next refreshes.
        locked_ids = None
        try:
            pcv = (data.get('parent_child') or '').strip()
            if pcv:
                from scripts.product_creator.Product_Creator import get_child_product_ids_cached
                locked_ids = get_child_product_ids_cached(pcv)
        except Exception as _le:
            print(f"[API] child lock resolution skipped: {_le}", flush=True)

        job = queue.enqueue(data, product_id, title, locked_ids=locked_ids)
        _invalidate_queue_list_cache()
        return jsonify({
            'success': True,
            'queued': True,
            'job_id': job['job_id'],
            'product_id': product_id
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f"Failed to enqueue save: {str(e)}"}), 500


@app.route('/api/product-family-image-check', methods=['GET'])
def api_product_family_image_check():
    """Is this image the one the product family shares as its main image?

    The editor asks before removing an image so it can offer to remove it across
    the family. Answered from the warm families tree plus at most two image
    reads, so it stays cheap enough to run on a click.
    """
    try:
        src = (request.args.get('src') or '').strip()
        parent_child = (request.args.get('parent_child') or '').strip()
        if not src or not parent_child:
            return jsonify({'shared': False})
        from scripts.product_creator.Product_Creator import family_image_usage
        return jsonify(family_image_usage(
            parent_child,
            src,
            request.args.get('product_id'),
            request.args.get('image_id'),
        ))
    except Exception as e:
        return jsonify({'shared': False, 'error': str(e)})


@app.route('/api/product-queue', methods=['GET'])
def api_product_queue_list():
    """Queue summary + locked product ids, for polling/greying on both pages.

    Every open editor/Products tab polls this, so the office round trip is
    shared. Within the TTL everyone gets the same cached answer, and while one
    thread is refreshing the rest are handed the previous one rather than
    queueing up behind it — with a single gunicorn worker, a pile-up here is
    enough to stop the whole site responding.
    """
    now = time.time()
    cached = _QUEUE_LIST_CACHE.get('payload')
    if cached is not None and (now - _QUEUE_LIST_CACHE.get('at', 0)) < _QUEUE_LIST_TTL:
        return jsonify(cached)

    # Only wait for the refresh if we have nothing at all to serve.
    if not _QUEUE_LIST_LOCK.acquire(blocking=(cached is None)):
        return jsonify(cached)
    try:
        cached = _QUEUE_LIST_CACHE.get('payload')
        if cached is not None and (time.time() - _QUEUE_LIST_CACHE.get('at', 0)) < _QUEUE_LIST_TTL:
            return jsonify(cached)  # another thread just refreshed it

        from scripts import product_save_queue as queue
        jobs = queue.list_jobs()
        summary = []
        for j in jobs:
            verify = j.get('verify') or []
            summary.append({
                'job_id': j.get('job_id'),
                'product_id': j.get('product_id'),
                'title': j.get('title'),
                'status': j.get('status'),
                'attempts': j.get('attempts'),
                'max_attempts': j.get('max_attempts'),
                'created_at': j.get('created_at'),
                'finished_at': j.get('finished_at'),
                'error': j.get('error'),
                'verify_ok': (all(r.get('ok') for r in verify) if verify else None),
                # Running, but its worker has gone quiet — offer a manual requeue.
                'stalled': queue.is_stalled(j),
            })
        payload = {'jobs': summary, 'locked': queue.locked_product_ids(jobs=jobs)}
        _QUEUE_LIST_CACHE['payload'] = payload
        _QUEUE_LIST_CACHE['at'] = time.time()
        return jsonify(payload)
    except Exception as e:
        if cached is not None:
            return jsonify(cached)
        return jsonify({'jobs': [], 'locked': [], 'error': str(e)})
    finally:
        _QUEUE_LIST_LOCK.release()


@app.route('/api/product-queue/<job_id>', methods=['GET'])
def api_product_queue_detail(job_id):
    """Full job incl. logs + verification diff (Logs tab)."""
    try:
        from scripts import product_save_queue as queue
        job = queue.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        job['logs'] = queue.get_logs(job_id)   # logs are stored separately now
        return jsonify(job)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/product-queue/<job_id>/cancel', methods=['POST'])
def api_product_queue_cancel(job_id):
    try:
        from scripts import product_save_queue as queue
        job = queue.cancel(job_id)
        if not job:
            return jsonify({'success': False, 'error': 'Job not found'}), 404
        _invalidate_queue_list_cache()
        return jsonify({'success': True, 'status': job.get('status')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/product-queue/<job_id>/retry', methods=['POST'])
def api_product_queue_retry(job_id):
    try:
        from scripts import product_save_queue as queue
        job = queue.retry(job_id)
        if not job:
            return jsonify({'success': False, 'error': 'Job not found'}), 404
        _invalidate_queue_list_cache()
        return jsonify({'success': True, 'status': job.get('status')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/products/<int:product_id>/sync-tab-description', methods=['POST'])
def api_sync_product_tab_description(product_id):
    """Clear Shopify native body_html for a product (legacy sync endpoint)."""
    try:
        from scripts.product_creator.Product_Creator import sync_product_tab_body_from_metafields  # type: ignore
        result = sync_product_tab_body_from_metafields(product_id)
        status = 200 if result.get("success") else 500
        return jsonify(result), status
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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
        elif namespace_key == 'custom.parent_child' and request.args.get('all') == '1':
            from scripts.product_creator.categories import get_parent_child_choices
            choices = get_parent_child_choices()
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

@app.route('/api/category-groups', methods=['GET'])
def api_category_groups():
    """Get categories with their subcategories for the combined Category & Subcategory dropdown"""
    try:
        from scripts.product_creator.categories import get_category_subcategory_groups
        groups = get_category_subcategory_groups()
        return jsonify({
            'success': True,
            'groups': groups or []
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error fetching category groups: {str(e)}'
        }), 500

@app.route('/api/filter-groups', methods=['GET'])
def api_filter_groups():
    """Get the grouped filter options for the combined Filters dropdown"""
    try:
        from scripts.product_creator.categories import get_filter_groups
        groups = get_filter_groups()
        return jsonify({
            'success': True,
            'groups': groups or []
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error fetching filter groups: {str(e)}'
        }), 500

@app.route('/api/products-parent-child', methods=['GET'])
def api_products_parent_child():
    """Return products that have a Parent - X parent_child metafield and which Parent values are taken."""
    try:
        from scripts.product_creator.Product_Creator import get_products_parent_child
        refresh = (request.args.get('refresh') or '').lower() in ('1', 'true', 'yes')
        result = get_products_parent_child(refresh=refresh)
        return jsonify(result)
    except Exception as e:
        return jsonify({'parentProducts': [], 'takenParentValues': [], 'error': str(e)}), 500

@app.route('/api/products-parent-child-tree', methods=['GET'])
def api_products_parent_child_tree():
    """Return parent-child tree. ?parents_only=1 returns instantly with empty children (hardcoded parents only)."""
    try:
        from scripts.product_creator.Product_Creator import get_parent_child_tree
        parents_only = request.args.get('parents_only', '').strip() in ('1', 'true', 'yes')
        refresh = (request.args.get('refresh') or '').lower() in ('1', 'true', 'yes')
        result = get_parent_child_tree(parents_only=parents_only, refresh=refresh)
        return jsonify(result)
    except Exception as e:
        return jsonify({'tree': [], 'error': str(e)}), 500

@app.route('/api/all-products', methods=['GET'])
def api_all_products():
    """Return every product organised by category -> subcategory (alphabetical) with SKU + title for the All Products page."""
    try:
        from scripts.product_creator.Product_Creator import get_all_products_overview
        refresh = (request.args.get('refresh') or '').lower() in ('1', 'true', 'yes')
        result = get_all_products_overview(refresh=refresh)
        result['success'] = True
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'groups': [], 'unassigned': [], 'error': str(e)}), 500


@app.route('/api/all-products/<int:product_id>', methods=['GET'])
def api_all_products_one(product_id):
    """Fresh All Products row(s) for a single product after Product Manager save."""
    try:
        from scripts.product_creator.Product_Creator import get_product_overview_slice
        slice_data = get_product_overview_slice(product_id)
        if not slice_data:
            return jsonify({'success': False, 'error': 'Product not found'}), 404
        return jsonify({'success': True, 'product_id': product_id, 'slice': slice_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/orders/<order_id>/order-info', methods=['PUT'])
def api_order_info_update(order_id):
    """Update order note / custom attributes (staff Orders page)."""
    try:
        from scripts.order_helpers import update_order_info  # type: ignore
        data = request.get_json(silent=True) or {}
        note = data.get("note", "")
        attributes = data.get("attributes") or []
        note_sections = data.get("note_sections")
        return jsonify(update_order_info(order_id, note, attributes, note_sections=note_sections))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/orders/<order_id>/production-notes")
def production_notes_page(order_id):
    """Printable production notes — one page per product line item (staff only)."""
    if not is_staff_authenticated():
        return redirect(url_for("staff_login", next=request.path))
    if not can_access_order(order_id):
        return "Order not found", 404
    from scripts.production_note import get_production_notes_for_order  # type: ignore

    line_number = request.args.get("line", type=int)
    embed = request.args.get("embed") == "1"
    auto_print = request.args.get("print") == "1"
    result = get_production_notes_for_order(order_id, line_number=line_number)
    if not result.get("success"):
        return result.get("error") or "Order not found", 404
    notes = result.get("notes") or []
    if not notes:
        return "No product line items on this order", 404
    return render_template(
        "UI/Production_Note.html",
        order_name=result.get("order_name") or "",
        notes=notes,
        embed=embed,
        auto_print=auto_print,
    )


@app.route("/orders/<order_id>/art-job-sheet")
def art_job_sheet_page(order_id):
    """Printable personalised art job sheet — one page per product line (staff only)."""
    if not is_staff_authenticated():
        return redirect(url_for("staff_login", next=request.path))
    if not can_access_order(order_id):
        return "Order not found", 404
    from scripts.art_job_sheet import get_art_job_sheets_for_order  # type: ignore

    line_number = request.args.get("line", type=int)
    embed = request.args.get("embed") == "1"
    auto_print = request.args.get("print") == "1"
    result = get_art_job_sheets_for_order(order_id, line_number=line_number)
    if not result.get("success"):
        return result.get("error") or "Order not found", 404
    sheets = result.get("sheets") or []
    if not sheets:
        return "No product line items on this order", 404
    return render_template(
        "UI/Art_Job_Sheet.html",
        order_name=result.get("order_name") or "",
        sheets=sheets,
        embed=embed,
        auto_print=auto_print,
    )


@app.route("/api/client/orders/<order_id>/order-info", methods=["PUT"])
def api_client_order_info_update(order_id):
    """Order info editing is staff-only."""
    return jsonify({"success": False, "error": "Order info can only be edited by staff"}), 403


def _office_client_id():
    """Prefer client session on /api/client/* routes even if staff is also logged in."""
    if (request.path or "").startswith("/api/client/"):
        cid = get_client_customer_id()
        if cid:
            return cid
    return get_client_customer_id() if not is_staff_authenticated() else None


def _office_access(order_id, *, refresh=False):
    from scripts.order_helpers import resolve_order_access  # type: ignore
    return resolve_order_access(
        order_id,
        refresh=refresh,
        client_customer_id=_office_client_id(),
    )


def _rewrite_office_files(office_view, order_id, item_id, api_prefix):
    if not office_view:
        return
    from urllib.parse import quote
    for f in office_view.get("files") or []:
        fname = f.get("name")
        if fname:
            f["download_url"] = (
                f"{api_prefix}/{quote(str(order_id), safe='')}"
                f"/items/{quote(item_id, safe='')}"
                f"/files/{quote(fname, safe='')}"
            )


def _office_tracking_response(order_id, entry, api_prefix):
    from scripts.order_helpers import attach_office_tracking  # type: ignore
    from scripts.office_api import OfficeApiError  # type: ignore

    order = entry.get("order")
    if not order:
        return jsonify({"success": False, "error": "Order data unavailable"}), 500
    try:
        attach_office_tracking(order, seed=True)
    except OfficeApiError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"success": False, "error": "Order tracking unavailable"}), 503

    items_out = []
    for item in order.get("order_items") or []:
        office = item.get("office")
        if office:
            _rewrite_office_files(office, order_id, item.get("office_item_id"), api_prefix)
        items_out.append({
            "line_number": item.get("line_number"),
            "office_item_id": item.get("office_item_id"),
            "title": item.get("title"),
            "office": office,
        })

    notify = {"order": entry.get("name") or "", "enabled": True, "email": None, "updated_at": None}
    try:
        from scripts.office_api import get_notify  # type: ignore
        order_name = entry.get("name") or ""
        if order_name:
            notify = get_notify(order_name)
    except Exception:
        pass

    payload = {
        "success": True,
        "order": order.get("name"),
        "items": items_out,
        "notify": notify,
        "customer_email": (order.get("customer_email") or "").strip(),
    }
    if api_prefix.startswith("/api/client"):
        payload["session_email"] = get_client_email()
    return jsonify(payload)


def _office_item_context(order_id, item):
    entry = _office_access(order_id)
    if not entry:
        return None, None
    from scripts.order_helpers import validate_office_item  # type: ignore
    if not validate_office_item(entry, item):
        return None, None
    return entry, entry.get("name") or ""


@app.route("/api/orders/<order_id>/tracking", methods=["GET"])
def api_order_tracking(order_id):
    if not can_access_order(order_id):
        return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    refresh = request.args.get("refresh", "").lower() in ("1", "true", "yes")
    entry = _office_access(order_id, refresh=refresh)
    if not entry:
        return jsonify({"success": False, "error": "Order not found"}), 404
    return _office_tracking_response(order_id, entry, "/api/orders")


@app.route("/api/client/orders/<order_id>/tracking", methods=["GET"])
def api_client_order_tracking(order_id):
    if not can_access_order(order_id):
        return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    refresh = request.args.get("refresh", "").lower() in ("1", "true", "yes")
    entry = _office_access(order_id, refresh=refresh)
    if not entry:
        return jsonify({"success": False, "error": "Order not found"}), 404
    return _office_tracking_response(order_id, entry, "/api/client/orders")


def _fetch_office_items_for_indicator(entry):
    """Lightweight status dots: one get_order read; never seeds items (expand order for that)."""
    from scripts.office_api import get_order, item_key, OfficeApiError  # type: ignore

    order_name = entry.get("name") or ""
    order = entry.get("order") or {}
    items_out = []
    office_by_item: dict[str, dict] = {}
    try:
        data = get_order(order_name)
        if data and data.get("items"):
            for view in data["items"]:
                key = str(view.get("item") or view.get("item_id") or view.get("id") or "").strip()
                if key:
                    office_by_item[key] = view
    except OfficeApiError:
        pass

    for item in order.get("order_items") or []:
        ln = item.get("line_number")
        if ln is None:
            continue
        oid = item.get("office_item_id") or item_key(ln, item.get("title") or "")
        items_out.append({"office": office_by_item.get(oid)})
    return items_out


def _office_indicator_response(order_id):
    entry = _office_access(order_id)
    if not entry:
        return jsonify({"success": False, "error": "Order not found"}), 404
    return jsonify({"success": True, "items": _fetch_office_items_for_indicator(entry)})


@app.route("/api/orders/<order_id>/indicator", methods=["GET"])
def api_order_indicator(order_id):
    if not can_access_order(order_id):
        return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    return _office_indicator_response(order_id)


@app.route("/api/client/orders/<order_id>/indicator", methods=["GET"])
def api_client_order_indicator(order_id):
    if not can_access_order(order_id):
        return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    return _office_indicator_response(order_id)


def _office_file_download(order_id, item, filename, api_prefix):
    entry, order_name = _office_item_context(order_id, item)
    if not entry:
        return jsonify({"success": False, "error": "Not authorised or item not found"}), 403
    try:
        from scripts.office_api import fetch_file, OfficeApiError  # type: ignore
        import mimetypes
        resp = fetch_file(order_name, item, filename)
        content_type = resp.headers.get("Content-Type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        inline = request.args.get("inline", "").lower() in ("1", "true", "yes")
        disposition = "inline" if inline else "attachment"

        def generate():
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        return Response(
            generate(),
            content_type=content_type,
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 502


def _office_file_kind(file_meta: dict) -> str:
    kind = (file_meta.get("kind") or "").strip().lower()
    if kind in ("artwork", "proof"):
        return kind
    name = (file_meta.get("name") or "").lower()
    if name.startswith("customer-artwork") or "artwork" in name:
        return "artwork"
    if name.startswith("proof"):
        return "proof"
    return "other"


def _client_may_delete_file(office_item: dict, filename: str) -> tuple[bool, str]:
    stage = (office_item.get("current_stage") or "").strip()
    if stage not in ("received", "artwork"):
        return False, "Files cannot be removed after proofing has started"
    files = office_item.get("files") or []
    match = next((f for f in files if (f.get("name") or "") == filename), None)
    if not match:
        return False, "File not found"
    if _office_file_kind(match) != "artwork":
        return False, "You can only remove your own artwork uploads"
    return True, ""


def _office_delete_file(order_id, item, filename, *, client_mode: bool = False):
    entry, order_name = _office_item_context(order_id, item)
    if not entry:
        return jsonify({"success": False, "error": "Item not found on this order"}), 404
    try:
        from scripts.office_api import get_item, delete_file, OfficeApiError  # type: ignore
        office_item = get_item(order_name, item)
        if not office_item:
            return jsonify({"success": False, "error": "Item not found on this order"}), 404
        if client_mode:
            allowed, reason = _client_may_delete_file(office_item, filename)
            if not allowed:
                return jsonify({"success": False, "error": reason}), 403
        elif not is_staff_authenticated():
            return jsonify({"success": False, "error": "Not authorised"}), 403
        delete_file(order_name, item, filename)
        return jsonify({"success": True})
    except OfficeApiError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502


@app.route("/api/orders/<order_id>/items/<path:item>/files/<path:filename>", methods=["GET", "DELETE"])
def api_order_office_file(order_id, item, filename):
    if not can_access_order(order_id):
        return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    if request.method == "DELETE":
        return _office_delete_file(order_id, item, filename)
    return _office_file_download(order_id, item, filename, "/api/orders")


@app.route("/api/client/orders/<order_id>/items/<path:item>/files/<path:filename>", methods=["GET", "DELETE"])
def api_client_order_office_file(order_id, item, filename):
    if not can_access_order(order_id):
        return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    if request.method == "DELETE":
        return _office_delete_file(order_id, item, filename, client_mode=True)
    return _office_file_download(order_id, item, filename, "/api/client/orders")


def _office_notify_get(order_id):
    entry = _office_access(order_id)
    if not entry:
        return jsonify({"success": False, "error": "Order not found"}), 404
    order_name = entry.get("name") or ""
    try:
        from scripts.office_api import get_notify, OfficeApiError  # type: ignore
        notify = get_notify(order_name)
        payload = {"success": True, "notify": notify}
        if not is_staff_authenticated():
            payload["session_email"] = get_client_email()
        return jsonify(payload)
    except OfficeApiError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502


def _office_notify_set(order_id):
    entry = _office_access(order_id)
    if not entry:
        return jsonify({"success": False, "error": "Order not found"}), 404
    order_name = entry.get("name") or ""
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))
    email = (data.get("email") or "").strip()
    if enabled and not email and not is_staff_authenticated():
        email = (get_client_email() or "").strip()
    try:
        from scripts.office_api import set_notify, OfficeApiError  # type: ignore
        notify = set_notify(order_name, enabled, email)
        return jsonify({"success": True, "notify": notify})
    except OfficeApiError as exc:
        msg = str(exc)
        status = 400 if "email" in msg.lower() else 502
        return jsonify({"success": False, "error": msg}), status


@app.route("/api/orders/<order_id>/notify", methods=["GET", "POST"])
def api_order_notify(order_id):
    if not can_access_order(order_id):
        return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    if request.method == "GET":
        return _office_notify_get(order_id)
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    return _office_notify_set(order_id)


@app.route("/api/orders/<order_id>/production-notify", methods=["POST"])
def api_order_production_notify(order_id):
    """Staff: send a production update email via Klaviyo after explicit confirmation."""
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    if not can_access_order(order_id):
        return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    entry = _office_access(order_id)
    if not entry:
        return jsonify({"success": False, "error": "Order not found"}), 404

    data = request.get_json(silent=True) or {}
    update_type = (data.get("update_type") or "").strip()
    item_title = (data.get("item_title") or "").strip()
    item_id = (data.get("item_id") or "").strip()
    email_override = (data.get("email") or "").strip()

    from scripts.klaviyo_api import (  # type: ignore
        NOTIFY_WORTHY_UPDATE_TYPES,
        KlaviyoError,
        build_portal_url,
        klaviyo_configured,
        latest_proof_filename,
        send_production_update,
    )

    if not klaviyo_configured():
        return jsonify({"success": False, "error": "Email notifications are not configured"}), 503
    if update_type not in NOTIFY_WORTHY_UPDATE_TYPES:
        return jsonify({"success": False, "error": "Invalid update type"}), 400

    order_name = entry.get("name") or ""
    try:
        from scripts.office_api import get_notify, OfficeApiError  # type: ignore
        notify = get_notify(order_name) if order_name else {}
    except OfficeApiError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502

    if not notify.get("enabled"):
        return jsonify({"success": False, "error": "Production updates are disabled for this order"}), 400

    email = email_override or (notify.get("email") or "").strip()
    if not email:
        return jsonify({"success": False, "error": "No email address for this order"}), 400

    proof_filename = (data.get("proof_filename") or "").strip()

    proof = proof_filename
    if update_type == "proof_uploaded" and not proof and item_id:
        proof = latest_proof_filename(order_name, item_id)

    try:
        send_production_update(
            email,
            order_name,
            update_type,
            order_id=str(order_id),
            item_title=item_title,
            item_id=item_id,
            proof_filename=proof,
            order=entry.get("order"),
        )
    except KlaviyoError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502

    portal_url = build_portal_url(
        str(order_id),
        item_id=item_id,
        proof_filename=proof if update_type == "proof_uploaded" else "",
    )
    return jsonify({
        "success": True,
        "email": email,
        "update_type": update_type,
        "portal_url": portal_url,
    })


@app.route("/api/client/orders/<order_id>/notify", methods=["GET", "POST"])
def api_client_order_notify(order_id):
    if not can_access_order(order_id):
        return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    if request.method == "GET":
        return _office_notify_get(order_id)
    return _office_notify_set(order_id)


def _office_list_files(order_id, item, api_prefix):
    entry, order_name = _office_item_context(order_id, item)
    if not entry:
        return jsonify({"success": False, "error": "Item not found on this order"}), 404
    try:
        from scripts.office_api import list_files, OfficeApiError  # type: ignore
        from urllib.parse import quote
        data = list_files(order_name, item)
        files_out = []
        for f in data.get("files") or []:
            fname = f.get("name")
            if fname:
                f = dict(f)
                f["download_url"] = (
                    f"{api_prefix}/{quote(str(order_id), safe='')}"
                    f"/items/{quote(item, safe='')}"
                    f"/files/{quote(fname, safe='')}"
                )
            files_out.append(f)
        return jsonify({"success": True, "files": files_out})
    except OfficeApiError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502


@app.route("/api/orders/<order_id>/items/<path:item>/files", methods=["GET"])
def api_order_office_files_list(order_id, item):
    if not can_access_order(order_id):
        return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    return _office_list_files(order_id, item, "/api/orders")


@app.route("/api/office-files", methods=["GET"])
def api_office_files_browse():
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    search = (request.args.get("search") or "").strip()
    try:
        max_orders = int(request.args.get("max_orders", 150))
    except ValueError:
        max_orders = 150
    try:
        from scripts.Office_Files import browse_office_files  # type: ignore
        return jsonify(browse_office_files(search=search, max_orders=max_orders))
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/client/orders/<order_id>/items/<path:item>/files", methods=["GET"])
def api_client_order_office_files_list(order_id, item):
    if not can_access_order(order_id):
        return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    return _office_list_files(order_id, item, "/api/client/orders")


def _office_upload_artwork(order_id, item, api_prefix, *, staff=False):
    if staff:
        if not is_staff_authenticated():
            return jsonify({"success": False, "error": "Staff login required"}), 403
    else:
        cid = get_client_customer_id()
        if not cid:
            return jsonify({"success": False, "error": "Customer login required"}), 403
        from scripts.order_helpers import resolve_order_access  # type: ignore
        if not resolve_order_access(order_id, client_customer_id=cid):
            return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    entry, order_name = _office_item_context(order_id, item)
    if not entry:
        return jsonify({"success": False, "error": "Item not found on this order"}), 404
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"success": False, "error": "No file provided"}), 400
    try:
        from scripts.office_api import upload_artwork, OfficeApiError  # type: ignore
        office = upload_artwork(order_name, item, f.stream, f.filename)
        _rewrite_office_files(office, order_id, item, api_prefix)
        return jsonify({"success": True, "office": office})
    except OfficeApiError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502


def _office_upload_proof(order_id, item, api_prefix):
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Proof upload is for staff only"}), 403
    entry, order_name = _office_item_context(order_id, item)
    if not entry:
        return jsonify({"success": False, "error": "Item not found on this order"}), 404
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"success": False, "error": "No file provided"}), 400
    try:
        from scripts.office_api import upload_proof, OfficeApiError  # type: ignore
        office = upload_proof(order_name, item, f.stream, f.filename)
        _rewrite_office_files(office, order_id, item, api_prefix)
        return jsonify({"success": True, "office": office})
    except OfficeApiError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502


@app.route("/api/client/orders/<order_id>/items/<path:item>/artwork", methods=["POST"])
def api_client_order_artwork(order_id, item):
    return _office_upload_artwork(order_id, item, "/api/client/orders", staff=False)


@app.route("/api/orders/<order_id>/items/<path:item>/artwork", methods=["POST"])
def api_order_artwork(order_id, item):
    return _office_upload_artwork(order_id, item, "/api/orders", staff=True)


@app.route("/api/orders/<order_id>/items/<path:item>/proof", methods=["POST"])
def api_order_proof(order_id, item):
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    return _office_upload_proof(order_id, item, "/api/orders")


def _office_set_status(order_id, item, api_prefix, *, client_mode=False):
    if client_mode:
        cid = get_client_customer_id()
        if not cid:
            return jsonify({"success": False, "error": "Customer login required"}), 403
        from scripts.order_helpers import resolve_order_access  # type: ignore
        if not resolve_order_access(order_id, client_customer_id=cid):
            return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    elif not can_access_order(order_id):
        return jsonify({"success": False, "error": "Not authorised for this order"}), 403
    entry, order_name = _office_item_context(order_id, item)
    if not entry:
        return jsonify({"success": False, "error": "Item not found on this order"}), 404
    data = request.get_json(silent=True) or {}
    stage = (data.get("stage") or "").strip()
    note = (data.get("note") or "").strip()
    by = (data.get("by") or "").strip()
    if not stage:
        return jsonify({"success": False, "error": "stage is required"}), 400
    if client_mode or not is_staff_authenticated():
        by = "customer"
        if stage == "approved":
            pass
        elif note and stage.startswith("proof_"):
            pass  # request changes — same stage, note in history
        else:
            return jsonify({"success": False, "error": "Invalid status update"}), 400
    elif not by:
        by = "staff"
    if stage == "in_production" and not note:
        note = "In Production"
    previous_stage = ""
    if stage == "approved":
        try:
            from scripts.office_api import get_item  # type: ignore
            current = get_item(order_name, item)
            if current:
                previous_stage = (current.get("current_stage") or "").strip()
        except Exception:
            pass
    try:
        from scripts.office_api import set_status, get_item, OfficeApiError  # type: ignore
        office = set_status(order_name, item, stage, note=note, by=by)
    except OfficeApiError as exc:
        if stage != "in_production":
            return jsonify({"success": False, "error": str(exc)}), 502
        current = get_item(order_name, item)
        if not current or current.get("current_stage") != "printing":
            return jsonify({"success": False, "error": str(exc)}), 502
        try:
            office = set_status(order_name, item, "printing", note=note or "In Production", by=by)
        except OfficeApiError:
            office = current
    _rewrite_office_files(office, order_id, item, api_prefix)
    if stage == "approved" and previous_stage != "approved":
        _fire_proof_approved_klaviyo(order_id, entry, order_name, item, approved_by=by)
    return jsonify({"success": True, "office": office})


def _fire_proof_approved_klaviyo(order_id, entry, order_name, item_id, *, approved_by=""):
    """Notify staff via Klaviyo when a line item reaches Proof Approved."""
    import logging

    try:
        from scripts.klaviyo_api import KlaviyoError, klaviyo_proof_approved_configured, send_proof_approved
    except ImportError:
        return
    if not klaviyo_proof_approved_configured():
        return

    item_title = ""
    for line in (entry.get("order") or {}).get("order_items") or []:
        if (line.get("office_item_id") or "") == item_id:
            item_title = (line.get("title") or "").strip()
            break

    try:
        send_proof_approved(
            order_name,
            order_id=str(order_id),
            item_title=item_title,
            item_id=item_id,
            approved_by=(approved_by or "").strip(),
        )
    except KlaviyoError as exc:
        logging.getLogger(__name__).warning("Klaviyo proof approved event not sent: %s", exc)


@app.route("/api/client/orders/<order_id>/items/<path:item>/status", methods=["POST"])
def api_client_order_status(order_id, item):
    return _office_set_status(order_id, item, "/api/client/orders", client_mode=True)


@app.route("/api/orders/<order_id>/items/<path:item>/status", methods=["POST"])
def api_order_status(order_id, item):
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    return _office_set_status(order_id, item, "/api/orders")


@app.route('/api/diary', methods=['GET'])
def api_diary():
    """Flat product-line diary rows for staff dispatch planning."""
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    try:
        from scripts.Diary import get_diary_overview  # type: ignore
        return jsonify(get_diary_overview())
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "rows": [], "total": 0}), 500


@app.route('/api/diary/entry', methods=['PUT'])
def api_diary_entry():
    """Save dispatch date and/or carrier for one order line."""
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    data = request.get_json(silent=True) or {}
    try:
        from scripts.Diary import save_diary_entry  # type: ignore
        result = save_diary_entry(data)
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/build-info', methods=['GET'])
def api_build_info():
    """Git commit for the running deploy (Render env or local .git)."""
    try:
        from scripts.build_info import get_build_info  # type: ignore
        return jsonify({"success": True, **get_build_info()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "label": "unknown"}), 500


@app.route('/api/shipping/status', methods=['GET'])
def api_shipping_status():
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    try:
        from scripts.shipping import shipping_status  # type: ignore
        return jsonify({"success": True, "providers": shipping_status()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/shipping/prepare/<order_id>', methods=['GET'])
def api_shipping_prepare(order_id):
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    item_id = (request.args.get("item_id") or "").strip() or None
    try:
        from scripts.shipping import prepare_shipment  # type: ignore
        result = prepare_shipment(order_id, item_id=item_id)
        if not result.get("success"):
            return jsonify(result), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/shipping/quote', methods=['POST'])
def api_shipping_quote():
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    data = request.get_json(silent=True) or {}
    try:
        from scripts.shipping import quote_shipment  # type: ignore
        result = quote_shipment(data)
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/shipping/ship', methods=['POST'])
def api_shipping_ship():
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    data = request.get_json(silent=True) or {}
    try:
        from scripts.shipping import ship_order  # type: ignore
        result = ship_order(data)
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/shipping/reprint', methods=['POST'])
def api_shipping_reprint():
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    data = request.get_json(silent=True) or {}
    try:
        from scripts.shipping import reprint_label  # type: ignore
        result = reprint_label(data)
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/shipping/labels-status', methods=['POST'])
def api_shipping_labels_status():
    """Probe office server for stored ZPL labels (metadata only)."""
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    data = request.get_json(silent=True) or {}
    try:
        from scripts.shipping import labels_status  # type: ignore
        return jsonify(labels_status(data))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/orders', methods=['GET'])
def api_orders():
    """Return recent Shopify orders for the staff Orders page."""
    try:
        from scripts.Orders import get_orders_overview
        return jsonify(get_orders_overview())
    except Exception as e:
        return jsonify({'success': False, 'orders': [], 'total': 0, 'error': str(e)}), 500


@app.route('/api/customers', methods=['GET'])
def api_customers():
    """Return all Shopify customers grouped by Pending / trade / end-customer tags."""
    try:
        from scripts.Customers import get_customers_overview
        refresh = request.args.get('refresh', '').lower() in ('1', 'true', 'yes')
        return jsonify(get_customers_overview(refresh=refresh))
    except Exception as e:
        return jsonify({
            'success': False,
            'customers': [],
            'total': 0,
            'conflict_count': 0,
            'error': str(e),
        }), 500


@app.route('/api/companies', methods=['GET', 'POST'])
def api_companies():
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    try:
        from scripts.Companies import create_company, get_companies_overview  # type: ignore
        if request.method == 'GET':
            refresh = request.args.get('refresh', '').lower() in ('1', 'true', 'yes')
            return jsonify(get_companies_overview(refresh=refresh))
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        result = create_company(name)
        status = 400 if not result.get('success') else 200
        return jsonify(result), status
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/companies/<company_id>', methods=['GET', 'PUT', 'DELETE'])
def api_company_detail(company_id):
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    try:
        from scripts.Companies import delete_company, get_company_detail, rename_company  # type: ignore
        if request.method == 'GET':
            result = get_company_detail(company_id)
            return jsonify(result), (404 if not result.get('success') else 200)
        if request.method == 'DELETE':
            result = delete_company(company_id)
            return jsonify(result), (404 if result.get('error') == 'Company not found' else (400 if not result.get('success') else 200))
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        result = rename_company(company_id, name)
        return jsonify(result), (400 if not result.get('success') else 200)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/companies/<company_id>/members', methods=['POST'])
def api_company_add_member(company_id):
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    data = request.get_json(silent=True) or {}
    customer_id = (data.get('customer_id') or '').strip()
    try:
        from scripts.Companies import add_company_member  # type: ignore
        result = add_company_member(company_id, customer_id)
        return jsonify(result), (400 if not result.get('success') else 200)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/companies/<company_id>/members/<customer_id>', methods=['DELETE'])
def api_company_remove_member(company_id, customer_id):
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    try:
        from scripts.Companies import remove_company_member  # type: ignore
        result = remove_company_member(company_id, customer_id)
        return jsonify(result), (400 if not result.get('success') else 200)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/companies/<company_id>/notes', methods=['POST'])
def api_company_add_note(company_id):
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    data = request.get_json(silent=True) or {}
    try:
        from scripts.Companies import add_company_note  # type: ignore
        result = add_company_note(
            company_id,
            author=(data.get('author') or '').strip(),
            body=(data.get('body') or '').strip(),
            note_date=(data.get('note_date') or '').strip(),
        )
        return jsonify(result), (400 if not result.get('success') else 200)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/companies/<company_id>/notes/<note_id>', methods=['DELETE'])
def api_company_delete_note(company_id, note_id):
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403
    try:
        from scripts.Companies import delete_company_note  # type: ignore
        result = delete_company_note(company_id, note_id)
        status = 404 if result.get('error') == 'Note not found' else (400 if not result.get('success') else 200)
        return jsonify(result), status
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/customers/<customer_id>/orders', methods=['GET'])
def api_customer_orders(customer_id):
    """Return all orders for one customer (staff Customers page)."""
    try:
        from scripts.Client_Orders import get_customer_orders  # type: ignore
        result = get_customer_orders(customer_id, fetch_all=True)
        if not result.get("success"):
            return jsonify(result), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'orders': [], 'total': 0, 'error': str(e)}), 500


@app.route('/api/customers/<customer_id>/type-tag', methods=['POST'])
def api_customer_type_tag(customer_id):
    """Replace a customer's type tag (trade / end-customer / Pending) on Shopify."""
    try:
        from scripts.Customers import update_customer_type_tag, CUSTOMER_TYPE_TAGS
        data = request.get_json(silent=True) or {}
        type_tag = data.get('type_tag')
        if type_tag is not None and type_tag != '':
            key = str(type_tag).strip().lower()
            if key not in CUSTOMER_TYPE_TAGS:
                return jsonify({'success': False, 'error': 'Invalid type tag'}), 400
            type_tag = key
        else:
            type_tag = None
        customer = update_customer_type_tag(customer_id, type_tag)
        return jsonify({'success': True, 'customer': customer})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/customers/<customer_id>/type-assigned-notify', methods=['POST'])
def api_customer_type_assigned_notify(customer_id):
    """Staff: send Klaviyo event after pending → trade/end-customer (explicit confirmation)."""
    if not is_staff_authenticated():
        return jsonify({"success": False, "error": "Staff login required"}), 403

    data = request.get_json(silent=True) or {}
    customer_type = (data.get("customer_type") or "").strip().lower()
    email_override = (data.get("email") or "").strip()

    from scripts.klaviyo_api import (  # type: ignore
        ASSIGNED_CUSTOMER_TYPES,
        KlaviyoError,
        klaviyo_customer_type_configured,
        send_customer_type_assigned,
    )
    from scripts.Customers import _fetch_single_customer  # type: ignore

    if not klaviyo_customer_type_configured():
        return jsonify({"success": False, "error": "Email notifications are not configured"}), 503
    if customer_type not in ASSIGNED_CUSTOMER_TYPES:
        return jsonify({"success": False, "error": "Invalid customer type"}), 400

    try:
        customer = _fetch_single_customer(customer_id)
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 502

    email = email_override or (customer.get("email") or "").strip()
    if not email:
        return jsonify({"success": False, "error": "No email address for this customer"}), 400

    customer_name = (customer.get("name") or "").strip()

    try:
        send_customer_type_assigned(
            email,
            customer_name,
            customer_type,
            customer_id=str(customer_id),
        )
    except KlaviyoError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502

    return jsonify({
        "success": True,
        "email": email,
        "customer_type": customer_type,
    })


@app.route('/api/customers/<customer_id>', methods=['PUT'])
def api_customer_update(customer_id):
    """Save customer email, type tag, and custom_fields metafields."""
    try:
        from scripts.Customers import update_customer_details, CUSTOMER_TYPE_TAGS, invalidate_customers_cache
        data = request.get_json(silent=True) or {}
        type_tag = data.get('type_tag')
        if type_tag is not None and type_tag != '':
            key = str(type_tag).strip().lower()
            if key not in CUSTOMER_TYPE_TAGS:
                return jsonify({'success': False, 'error': 'Invalid type tag'}), 400
            data['type_tag'] = key
        elif type_tag == '':
            data['type_tag'] = None
        customer = update_customer_details(customer_id, data)
        invalidate_customers_cache()
        return jsonify({'success': True, 'customer': customer})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


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

@app.route('/api/bag-colours', methods=['GET'])
def api_bag_colours():
    """Get the bag colours for autofill"""
    try:
        from scripts.product_creator.metafield_order import get_bag_colours
        colours = get_bag_colours()
        return jsonify({'success': True, 'colours': colours})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error fetching bag colours: {str(e)}'}), 500

@app.route('/api/foil-colours', methods=['GET'])
def api_foil_colours():
    """Get the foil stamp colours for autofill"""
    try:
        from scripts.product_creator.metafield_order import get_foil_colours
        colours = get_foil_colours()
        return jsonify({'success': True, 'colours': colours})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error fetching foil colours: {str(e)}'}), 500

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
    app.run(debug=False, threaded=True)
