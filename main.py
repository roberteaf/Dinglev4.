"""
DingleV4Hub - main.py
======================
A deployable web proxy server.
Deploy this on Render, Railway, or any Python host.

How to deploy on Render (free):
  1. Push this repo to GitHub (include main.py, DingleV4Hub.html, requirements.txt)
  2. Go to render.com → New → Web Service → connect your GitHub repo
  3. Set:  Build Command:  pip install -r requirements.txt
           Start Command:  python main.py
  4. Deploy — your proxy will be live at your .onrender.com URL

requirements.txt contents:
  flask
  requests
"""

import os
import requests
from flask import Flask, request, Response, send_file, abort
from urllib.parse import urlparse, urljoin

app = Flask(__name__)

# Path to the HTML file (same directory as main.py)
HTML_PATH = os.path.join(os.path.dirname(__file__), "DingleV4Hub.html")

# ── Realistic browser headers sent to upstream sites ─────────────────────────
HEADERS = {
    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36",
    "Accept":
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Headers we strip from upstream responses before forwarding
HOP_BY_HOP = {
    "transfer-encoding", "content-encoding", "content-length",
    "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers", "upgrade",
    # remove frame-blocking headers so pages load inside the proxy
    "x-frame-options", "content-security-policy",
    "x-content-security-policy", "x-webkit-csp",
}


def inject_base(html: bytes, url: str) -> bytes:
    """Inject <base href> so relative links resolve correctly."""
    parsed = urlparse(url)
    base = f'{parsed.scheme}://{parsed.netloc}/'
    tag = f'<base href="{base}" target="_blank">'.encode()
    for marker in [b"<head>", b"<HEAD>"]:
        idx = html.find(marker)
        if idx != -1:
            pos = idx + len(marker)
            return html[:pos] + tag + html[pos:]
    return tag + html


def rewrite_links(html: bytes, base_url: str) -> bytes:
    """Rewrite absolute href/src links to go through our proxy."""
    # Simple approach: rewrite https:// and http:// links to /proxy?url=...
    import re
    proxy_base = "/proxy?url="

    def replacer(m):
        attr, url = m.group(1), m.group(2)
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith(("http://", "https://")):
            return f'{attr}"{proxy_base}{requests.utils.quote(url, safe="")}"'
        return m.group(0)

    html_str = html.decode("utf-8", errors="replace")
    html_str = re.sub(r'(href|src|action)="((?:https?:|//)[^"]+)"', replacer, html_str)
    html_str = re.sub(r"(href|src|action)='((?:https?:|//)[^']+)'", replacer, html_str)
    return html_str.encode("utf-8")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the hub UI."""
    if not os.path.exists(HTML_PATH):
        return "<h1>DingleV4Hub.html not found</h1><p>Place it in the same folder as main.py</p>", 404
    return send_file(HTML_PATH, mimetype="text/html")


@app.route("/proxy")
def proxy():
    """
    Fetch any URL and relay it back, stripping blocking headers.
    Usage: /proxy?url=https://example.com
    """
    url = request.args.get("url", "").strip()
    if not url:
        return "Missing ?url= parameter", 400

    # Auto-add scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Validate it looks like a real URL
    parsed = urlparse(url)
    if not parsed.netloc:
        return "Invalid URL", 400

    try:
        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=18,
            allow_redirects=True,
            stream=True,
        )
    except requests.exceptions.ConnectionError:
        return f"Could not connect to {url}", 502
    except requests.exceptions.Timeout:
        return f"Request to {url} timed out", 504
    except Exception as e:
        return f"Proxy error: {e}", 500

    content_type = resp.headers.get("Content-Type", "text/html")
    body = resp.content

    # For HTML: inject base tag + rewrite links
    if "text/html" in content_type:
        body = inject_base(body, url)
        body = rewrite_links(body, url)

    # Build clean response headers
    out_headers = {}
    for k, v in resp.headers.items():
        if k.lower() not in HOP_BY_HOP:
            out_headers[k] = v

    # Force allow framing
    out_headers["X-Frame-Options"] = "ALLOWALL"
    out_headers["Access-Control-Allow-Origin"] = "*"
    out_headers.pop("Content-Security-Policy", None)

    return Response(body, status=resp.status_code,
                    headers=out_headers, content_type=content_type)


@app.route("/proxy", methods=["POST"])
def proxy_post():
    """Handle POST form submissions through the proxy."""
    url = request.args.get("url", "").strip()
    if not url:
        return "Missing ?url= parameter", 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        resp = requests.post(
            url,
            headers=HEADERS,
            data=request.form,
            timeout=18,
            allow_redirects=True,
        )
    except Exception as e:
        return f"Proxy POST error: {e}", 500

    content_type = resp.headers.get("Content-Type", "text/html")
    body = resp.content
    if "text/html" in content_type:
        body = inject_base(body, url)
        body = rewrite_links(body, url)

    out_headers = {k: v for k, v in resp.headers.items()
                   if k.lower() not in HOP_BY_HOP}
    out_headers["X-Frame-Options"] = "ALLOWALL"
    out_headers["Access-Control-Allow-Origin"] = "*"
    out_headers.pop("Content-Security-Policy", None)

    return Response(body, status=resp.status_code,
                    headers=out_headers, content_type=content_type)


# ── Start ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"\n🌊  DingleV4Hub running on http://0.0.0.0:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
