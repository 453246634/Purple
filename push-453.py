#!/usr/bin/env python3
"""Purple 项目 API 推送 - 推送到 453246634/Purple 备用仓库"""
import json, os, sys, base64, urllib.request, urllib.error, ssl, socket

OWNER = "453246634"
REPO = "Purple"
BRANCH = "main"
WORKDIR = os.path.dirname(os.path.abspath(__file__))
API = f"https://api.github.com/repos/{OWNER}/{REPO}"

# Token from env var or local .token_453 file (453246634 token)
TOKEN = os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    token_file = os.path.join(WORKDIR, ".token_453")
    if os.path.exists(token_file):
        with open(token_file) as f:
            TOKEN = f.read().strip()
if not TOKEN:
    print("Error: Set GITHUB_TOKEN env var or create .token_453 file", flush=True)
    sys.exit(1)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# DNS monkey-patch: 强制 api.github.com 指向已知 IP（本地DNS解析失败时的解决方案）
_orig_getaddrinfo = socket.getaddrinfo
_GITHUB_IP = '20.205.243.168'
def _patched_getaddrinfo(host, port, *args, **kwargs):
    if host == 'api.github.com':
        return _orig_getaddrinfo(_GITHUB_IP, port, *args, **kwargs)
    return _orig_getaddrinfo(host, port, *args, **kwargs)
socket.getaddrinfo = _patched_getaddrinfo

def api(method, path, data=None):
    url = f"{API}/{path}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"token {TOKEN}")
    req.add_header("User-Agent", "Purple-Push")
    req.add_header("Accept", "application/vnd.github+json")
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=body, context=ctx, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:500]
        print(f"API Error {e.code}: {err}", flush=True)
        sys.exit(1)

def main():
    os.chdir(WORKDIR)
    msg = sys.argv[1] if len(sys.argv) > 1 else "更新代码"
    print(f"=== Push to 453246634/Purple ===", flush=True)
    print(f"Message: {msg}", flush=True)

    # 1. Get remote ref
    print("[1/4] Getting remote ref...", flush=True)
    ref = api("GET", f"git/refs/heads/{BRANCH}")
    parent_sha = ref["object"]["sha"]
    commit = api("GET", f"git/commits/{parent_sha}")
    base_tree = commit["tree"]["sha"]
    print(f"  Parent: {parent_sha[:10]}", flush=True)

    # 2. Get local file list (os.walk, 排除 node_modules/data/.git/token 等)
    EXCLUDE_DIRS = {'node_modules', 'data', '.git', '__pycache__'}
    EXCLUDE_FILES = {'.token', '.token_453', '.DS_Store', 'package-lock.json'}
    files = []
    for root, dirs, filenames in os.walk(WORKDIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn in EXCLUDE_FILES:
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, WORKDIR).replace('\\', '/')
            files.append(rel)
    files.sort()
    print(f"[2/4] Processing {len(files)} files...", flush=True)

    # 3. Create blobs
    tree_items = []
    for filepath in files:
        full_path = os.path.join(WORKDIR, filepath)
        if not os.path.isfile(full_path):
            continue
        with open(full_path, "rb") as f:
            content = f.read()

        # Avoid large files (>10MB) from crashing the API
        if len(content) > 10_000_000:
            print(f"  SKIP (too large, {len(content)} bytes): {filepath}", flush=True)
            continue

        b64 = base64.b64encode(content).decode("ascii")
        blob = api("POST", "git/blobs", {"content": b64, "encoding": "base64"})
        tree_items.append({"path": filepath, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  OK: {filepath} ({len(content)} bytes)", flush=True)

    # 4. Create tree
    print(f"[3/4] Creating tree...", flush=True)
    tree = api("POST", "git/trees", {"base_tree": base_tree, "tree": tree_items})
    print(f"  Tree: {tree['sha'][:10]}", flush=True)

    # 5. Create commit and update ref
    print(f"[4/4] Creating commit...", flush=True)
    new_commit = api("POST", "git/commits", {
        "message": msg,
        "tree": tree["sha"],
        "parents": [parent_sha]
    })
    print(f"  Commit: {new_commit['sha'][:10]}", flush=True)

    api("PATCH", f"git/refs/heads/{BRANCH}", {"sha": new_commit["sha"]})

    print(f"\n=== Push Complete ===", flush=True)
    print(f"https://github.com/{OWNER}/{REPO}/commit/{new_commit['sha']}", flush=True)

if __name__ == "__main__":
    main()
