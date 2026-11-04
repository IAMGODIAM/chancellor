#!/usr/bin/env python3
"""Direct-upload deployment to a Cloudflare Pages project (no git source).

Protocol per the proven house flow (backlink-work/justiceforkohen/deploy.py):
  1. GET upload-token (API token) -> JWT
  2. POST /pages/assets/check-missing (JWT) -> missing hashes
  3. POST /pages/assets/upload (JWT) batched base64 file payloads
  4. POST /pages/assets/upsert-hashes (JWT)
  5. POST .../projects/{name}/deployments (API token, multipart manifest)

Usage: deploy_pages.py PROJECT served_path=local_file [served_path=local_file ...]
The JWT is kept in memory only, never printed or persisted.
"""
import base64, hashlib, json, mimetypes, os, sys, time, urllib.request

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response

import blake3

API = "https://api.cloudflare.com/client/v4"
ACCOUNT = os.environ.get("CF_ACCOUNT_ID")
if not ACCOUNT:
    raise SystemExit(
        "CF_ACCOUNT_ID environment variable is not set — refusing to run. "
        "Set it to the Cloudflare account ID for the target account."
    )


def api_request(method, path, body=None, jwt=None, multipart=None):
    url = API + path
    if multipart is not None:
        boundary = "----" + hashlib.md5(os.urandom(16)).hexdigest()
        parts = []
        for name, content in multipart.items():
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n'
                f"Content-Type: application/json\r\n\r\n{content}\r\n"
            )
        parts.append(f"--{boundary}--\r\n")
        body = "".join(parts).encode()
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    else:
        req = urllib.request.Request(
            url,
            data=(json.dumps(body).encode() if body is not None else None),
            method=method,
        )
        req.add_header("Content-Type", "application/json")
    if jwt:
        req.add_header("Authorization", "Bearer " + jwt)
    else:
        add_surrogate_to_request(req, "custom.cloudflare-personal", allowed_hosts=["api.cloudflare.com"])
    resp = urllib.request.urlopen(req, timeout=600)
    return read_json_response(resp)


def file_hash(data: bytes, filename: str) -> str:
    base = os.path.basename(filename)
    ext = base.rsplit(".", 1)[-1] if "." in base[1:] else ""
    if base.startswith(".") and base.count(".") == 1:
        ext = ""
    digest = blake3.blake3((base64.b64encode(data).decode() + ext).encode()).digest()
    return digest.hex()[:32]


def main():
    project = sys.argv[1]
    pairs = sys.argv[2:]
    if not pairs:
        raise SystemExit("no files given")
    files = {}  # served_path -> (data, hash)
    for pair in pairs:
        served, local = pair.split("=", 1)
        if not served.startswith("/"):
            served = "/" + served
        with open(os.path.expanduser(local), "rb") as f:
            data = f.read()
        files[served] = (data, file_hash(data, os.path.basename(local)))
        print(f"file {served}: {len(data)} bytes hash {files[served][1]}", flush=True)

    token = api_request("GET", f"/accounts/{ACCOUNT}/pages/projects/{project}/upload-token")
    jwt = token["result"]["jwt"]
    print("upload token acquired", flush=True)

    hashes = [h for _, h in files.values()]
    missing = api_request("POST", "/pages/assets/check-missing", body={"hashes": hashes}, jwt=jwt)
    missing_set = set(missing["result"])
    print(f"missing: {len(missing_set)} of {len(hashes)}", flush=True)

    hash_to_path = {h: p for p, (_, h) in files.items()}
    batch = []
    for h in missing_set:
        served = hash_to_path[h]
        data = files[served][0]
        ctype = mimetypes.guess_type(served)[0] or "application/octet-stream"
        batch.append({
            "key": h,
            "value": base64.b64encode(data).decode(),
            "metadata": {"contentType": ctype},
            "base64": True,
        })
    if batch:
        for attempt in range(5):
            try:
                api_request("POST", "/pages/assets/upload", body=batch, jwt=jwt)
                break
            except Exception as exc:
                print(f"upload attempt {attempt + 1} failed: {exc}", flush=True)
                time.sleep(2 * (attempt + 1))
        else:
            raise SystemExit("upload failed after retries")
        print("uploaded", flush=True)
    else:
        print("nothing to upload", flush=True)

    api_request("POST", "/pages/assets/upsert-hashes", body={"hashes": hashes}, jwt=jwt)
    print("hashes upserted", flush=True)

    manifest = {p: h for p, (_, h) in files.items()}
    dep = api_request(
        "POST",
        f"/accounts/{ACCOUNT}/pages/projects/{project}/deployments",
        multipart={"manifest": json.dumps(manifest)},
    )
    result = dep["result"]
    print(json.dumps({"id": result.get("id"), "url": result.get("url"),
                      "environment": result.get("environment")}, indent=2))


if __name__ == "__main__":
    main()
