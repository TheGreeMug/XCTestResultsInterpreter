## Unified server run commands

Short reference for starting everything you need.

---

### 1. Start the unified API server (Python / Flask)

From the XCTestResultsInterpreter repo root on the Mac:

```bash
cd /Users/marius/Projects/XCTestResultsInterpreter
source unified-server/.venv/bin/activate
python3 -m unified-server.app \
  --host 127.0.0.1 \
  --port 5050 \
  --api-key "wc6aLnN7YeYdmTjZdfMEYZgHyAENkdGW6z7DnBRiHnI" \
  --origins "https://assurance.st,https://www.assurance.st,https://api.assurance.st" \
  --xctest-max-upload-gb 1.0 \
  --xctest-ttl 30 \
  --mp3-max-upload-mb 100
```

Keep this terminal open while you use the tools.

---

### 2. Start the Cloudflare tunnel

#### Manual (for testing)

From any directory on the Mac:

```bash
cloudflared tunnel run unified-api
```

Leave this running as long as you want the API reachable at `https://api.assurance.st/...`.

#### As a background service (recommended)

One-time install (already done if you followed the tunnel guide):

```bash
sudo cloudflared service install
```

Then on each reboot / when you want to start it:

```bash
sudo launchctl start com.cloudflare.cloudflared
```

To stop it:

```bash
sudo launchctl stop com.cloudflare.cloudflared
```

With the service running you do **not** need to run `cloudflared tunnel run unified-api` manually.

---

### 3. (Optional) Run Caddy instead of Cloudflare Tunnel

You only need this if you decide to expose the API directly again (no tunnel) or want Caddy for some other site.

From the XCTestResultsInterpreter repo root:

```bash
cd /Users/marius/Projects/XCTestResultsInterpreter/unified-server
sudo caddy run --config ./Caddyfile
```

This assumes your router forwards ports 80/443 to the Mac and DNS for the API host (e.g. `astudvpn.asuscomm.com`) points at your public IP. When using Cloudflare Tunnel, Caddy is optional and you can keep it stopped for the unified API.

