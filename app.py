import os, requests, time
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder="dashboard")

APOLLO_KEY  = os.environ.get("APOLLO_API_KEY", "I8cuKc9ZLzarxdjY8rjdOA")
APOLLO_BASE = "https://api.apollo.io/v1"
HEADERS     = {"X-Api-Key": APOLLO_KEY, "Content-Type": "application/json"}

LIST_ID     = "69c423ebe5c9a9000d5efe04"
PIPELINE_ID = "699355284e6cb30021f9f0dd"

# Simple in-memory cache (ttl = 1 hour)
_cache = {}
CACHE_TTL = 3600

def cache_get(key):
    entry = _cache.get(key)
    if entry and (time.time() - entry['ts']) < CACHE_TTL:
        return entry['data']
    return None

def cache_set(key, data):
    _cache[key] = {'data': data, 'ts': time.time()}

# ── Static ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("dashboard", "index.html")

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory("dashboard", filename)

@app.route("/ping")
def ping():
    return "ok", 200

# ── Helpers ───────────────────────────────────────────────────────────────────

def apollo_post(endpoint, body):
    r = requests.post(f"{APOLLO_BASE}/{endpoint}", headers=HEADERS, json=body, timeout=30)
    r.raise_for_status()
    return r.json()

def apollo_get(endpoint, params=None):
    r = requests.get(f"{APOLLO_BASE}/{endpoint}", headers=HEADERS, params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_page(endpoint, base_body, result_key, per_page, page):
    body = {**base_body, "page": page, "per_page": per_page}
    data = apollo_post(endpoint, body)
    return data.get(result_key, []), data.get("pagination", {})

def fetch_all_parallel(endpoint, base_body, result_key, per_page=50):
    """Fetch first page to get total_pages, then fetch remaining pages in parallel."""
    items, pagination = fetch_page(endpoint, base_body, result_key, per_page, 1)
    total_pages = pagination.get("total_pages", 1)

    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [
                ex.submit(fetch_page, endpoint, base_body, result_key, per_page, p)
                for p in range(2, total_pages + 1)
            ]
            for f in futures:
                batch, _ = f.result()
                items.extend(batch)
    return items

# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/contacts")
def api_contacts():
    cached = cache_get("contacts")
    if cached:
        return jsonify(cached)
    contacts = fetch_all_parallel(
        "contacts/search", {"label_ids": [LIST_ID]}, "contacts", per_page=50
    )
    result = {"contacts": contacts, "total": len(contacts)}
    cache_set("contacts", result)
    return jsonify(result)


@app.route("/api/deals")
def api_deals():
    cached = cache_get("deals")
    if cached:
        return jsonify(cached)
    deals = fetch_all_parallel(
        "opportunities/search", {"pipeline_ids": [PIPELINE_ID]}, "opportunities", per_page=25
    )
    result = {"opportunities": deals, "total": len(deals)}
    cache_set("deals", result)
    return jsonify(result)


@app.route("/api/stages")
def api_stages():
    cached = cache_get("stages")
    if cached:
        return jsonify(cached)
    data = apollo_get("opportunity_stages")
    cache_set("stages", data)
    return jsonify(data)


@app.route("/api/sequences")
def api_sequences():
    cached = cache_get("sequences")
    if cached:
        return jsonify(cached)
    data = apollo_post("emailer_campaigns/search", {"page": 1, "per_page": 50})
    campaigns = data.get("emailer_campaigns", [])
    result = {"emailer_campaigns": campaigns, "total": len(campaigns)}
    cache_set("sequences", result)
    return jsonify(result)


@app.route("/api/cache/clear")
def clear_cache():
    _cache.clear()
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
