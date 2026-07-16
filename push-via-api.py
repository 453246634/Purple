#!/usr/bin/env python3
"""Purple 项目 API 推送 - 通过 GitHub REST API 推送代码"""
import json, os, sys, base64, urllib.request, urllib.error, ssl, subprocess

OWNER = "453246634"
REPO = "Purple"
BRANCH = "main"
WORKDIR = os.path.dirname(os.path.abspath(__file__))
API = f"https://api.github.com/repos/{OWNER}/{REPO}"

# Token from env var, local .token_453 file, or fallback .token file
TOKEN = os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    token_file = os.path.join(WORKDIR, ".token_453")
    if os.path.exists(token_file):
        with open(token_file) as f:
            TOKEN = f.read().strip()
if not TOKEN:
    token_file2 = os.path.join(WORKDIR, ".token")
    if os.path.exists(token_file2):
        with open(token_file2) as f:
            TOKEN = f.read().strip()
if not TOKEN:
    print("Error: Set GITHUB_TOKEN env var or create .token_453 / .token file", flush=True)
    sys.exit(1)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

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
    print(f"=== Purple API Push ===", flush=True)
    print(f"Message: {msg}", flush=True)

    # 1. Get remote ref
    print("[1/4] Getting remote ref...", flush=True)
    ref = api("GET", f"git/refs/heads/{BRANCH}")
    parent_sha = ref["object"]["sha"]
    commit = api("GET", f"git/commits/{parent_sha}")
    base_tree = commit["tree"]["sha"]
    print(f"  Parent: {parent_sha[:10]}", flush=True)

    # 2. Get local file list from git
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip() and not f.startswith("node-runtime/")]
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
