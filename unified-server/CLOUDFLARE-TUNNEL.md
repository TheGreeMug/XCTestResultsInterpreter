# Hiding your IP with Cloudflare Tunnel

This guide walks through putting your unified API behind Cloudflare so that:

- Your **real home IP is never exposed** (DNS resolves to Cloudflare).
- You **no longer need port forwarding** for the API (the Mac connects outbound to Cloudflare).
- The frontend (on cPanel / assurance.st) keeps working; you only change the API base URL.

**Your current setup (summary):**

- **Frontend:** Static HTML (xcoderesults.html, mp3-strip.html, etc.) on cPanel, served at e.g. `https://assurance.st` (or www).
- **API:** Mac at home; Flask on `127.0.0.1:5050`, Caddy on 443; router forwards 80/443 to the Mac; API domain e.g. `astudvpn.asuscomm.com` (Asus DDNS) points to your home IP.
- **Flow:** Browser loads assurance.st → JS calls `https://astudvpn.asuscomm.com/xctest/api/...` and `.../mp3/api/...`.

**Target setup after this:**

- **Frontend:** Unchanged (still on cPanel at assurance.st).
- **API:** Same Flask app on the Mac; **Cloudflare Tunnel** runs on the Mac and connects outbound to Cloudflare. Public URL for the API becomes e.g. `https://api.assurance.st` (no Caddy, no port forwarding for the API).
- **Flow:** Browser loads assurance.st → JS calls `https://api.assurance.st/xctest/api/...` and `https://api.assurance.st/mp3/api/...`. DNS for `api.assurance.st` resolves to Cloudflare; your IP is never the target.

**Requirement:** You must be able to manage DNS for a domain that will host the API. The cleanest case is if you control **assurance.st** (or the same domain as the frontend). Then we use a subdomain like `api.assurance.st` for the API. If assurance.st is not yours (e.g. it’s the host’s domain and you can’t change nameservers), you’ll need a different domain you control (e.g. a subdomain of another domain you own) and use that for the API base URL instead.

---

## Part 1: Cloudflare account and domain

### 1.1 Create a Cloudflare account

- Go to [https://dash.cloudflare.com/sign-up](https://dash.cloudflare.com/sign-up) and create a free account.

### 1.2 Add your domain (e.g. assurance.st)

- In the dashboard: **Add a site** → enter the domain (e.g. `assurance.st`).
- Choose the **Free** plan.
- Cloudflare will show a summary of DNS records it detected (imported from the current DNS). Review and continue.
- You’ll get **two nameservers** (e.g. `ada.ns.cloudflare.com` and `bob.ns.cloudflare.com`).

### 1.3 Point the domain to Cloudflare

- Go to the **registrar** where you bought the domain (where assurance.st is registered).
- Find **DNS / Nameservers** settings.
- Replace the current nameservers with the two Cloudflare gave you. Save.
- Back in Cloudflare: **Check nameservers**. It can take a few minutes up to 24–48 hours; often it’s within an hour.

**Important:** After the switch, **all** DNS for assurance.st is managed in Cloudflare. Your frontend (cPanel) must still be reachable. In Cloudflare DNS you should have (or add) records so that the **frontend** keeps working, for example:

- **Type A** – Name: `@` (or `assurance.st`) → IP of your cPanel host.
- **Type A** or **CNAME** – Name: `www` → same (or cPanel’s hostname).

Do **not** delete these. We will add the API subdomain in a later step via the tunnel.

If you are **not** using assurance.st (e.g. frontend is on a host’s domain you can’t move), add instead a domain you do control, then use a subdomain of that for the API (e.g. `api.yourdomain.com`). The rest of the steps are the same; only the hostname changes.

---

## Part 2: Cloudflare Tunnel on the Mac

### 2.1 Install cloudflared on the Mac

```bash
brew install cloudflared
```

If you don’t use Homebrew, download the binary from [https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/).

### 2.2 Log in to Cloudflare (one-time)

```bash
cloudflared tunnel login
```

- A browser window opens; choose your Cloudflare account and allow the requested permission.
- This saves a certificate under `~/.cloudflared/` that ties this machine to your account.

### 2.3 Create a tunnel

```bash
cloudflared tunnel create unified-api
```

- Use any name you like instead of `unified-api` (e.g. `assurance-api`).
- You’ll see a message that the tunnel was created and given an ID (UUID). A config file will reference this ID.

### 2.4 Create the config file

Create (or edit) `~/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /Users/<YOUR_USERNAME>/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: api.assurance.st
    service: http://127.0.0.1:5050
  - service: http_status:404
```

Replace:

- `<TUNNEL_ID>` with the UUID from step 2.3 (e.g. from `~/.cloudflared/` you’ll see a file like `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.json`; the filename without `.json` is the tunnel ID).
- `<YOUR_USERNAME>` with your Mac username (or use the full path to the JSON file that `tunnel create` showed).
- `api.assurance.st` with your chosen API hostname (must be a hostname whose domain is in your Cloudflare account; e.g. if your domain is `example.com`, use `api.example.com`).

The last `service: http_status:404` rule is required: it’s the “catch-all” so that no other hostnames are routed through this tunnel.

**If your domain is not assurance.st:** use that subdomain (e.g. `api.yourdomain.com`) and the same `config.yml` structure.

### 2.5 Route the hostname to the tunnel (DNS in Cloudflare)

Cloudflare can create the DNS record for you when you run the tunnel. First time, run:

```bash
cloudflared tunnel route dns unified-api api.assurance.st
```

- `unified-api` is the tunnel name you used in 2.3.
- `api.assurance.st` must match the `hostname` in `config.yml`.

This creates a **CNAME** for `api.assurance.st` pointing at `<TUNNEL_ID>.cfargotunnel.com`, so traffic to `api.assurance.st` goes to Cloudflare and then through the tunnel to your Mac.

Alternatively, in the Cloudflare dashboard: **Zero Trust** → **Networks** → **Tunnels** → your tunnel → **Public Hostname** → Add: hostname `api.assurance.st`, service `http://127.0.0.1:5050`. That also creates the DNS record if the tunnel is linked to the zone.

### 2.6 Start the tunnel

**Manual run (for testing):**

```bash
cloudflared tunnel run unified-api
```

Leave this terminal open. Visit `https://api.assurance.st/health` in a browser (or use `curl`). You should get the JSON health response. If so, the tunnel and Flask are working.

**Run as a service (recommended so it survives reboot):**

```bash
sudo cloudflared service install
```

This installs a launchd service that uses `~/.cloudflared/config.yml`. Ensure that config has exactly one tunnel and the correct `tunnel:` ID and `credentials-file:` path. Then:

```bash
sudo launchctl start com.cloudflare.cloudflared
```

To check status:

```bash
sudo launchctl list | grep cloudflare
```

Logs (if needed):

```bash
sudo launchctl start com.cloudflare.cloudflared
# or
/opt/homebrew/bin/cloudflared tunnel run unified-api
```

---

## Part 3: Run the Flask app (no Caddy needed for the API)

On the Mac, the API is only reached via the tunnel, which talks to `http://127.0.0.1:5050`. So:

1. **Start Flask** as usual (from the parent directory of `unified-server`):

```bash
cd /Users/marius/Projects/XCTestResultsInterpreter   # or your repo path
source unified-server/.venv/bin/activate
python3 -m unified-server.app \
  --host 127.0.0.1 \
  --port 5050 \
  --api-key "YOUR_API_KEY" \
  --origins "https://assurance.st,https://www.assurance.st" \
  --xctest-max-upload-gb 1.0 \
  --xctest-ttl 30 \
  --mp3-max-upload-mb 100
```

2. **Caddy** – You can stop and disable Caddy for the API. It’s no longer in the path. (You can keep it for something else on the Mac if you want.)

3. **Port forwarding** – You can remove the **80 and 443** port forwards for the Mac. The tunnel uses outbound HTTPS to Cloudflare; no inbound ports are needed for the API. (Leave forwarding in place only if you still need direct access to something else on the Mac on 80/443.)

---

## Part 4: Point the frontend at the new API URL

The frontend (on cPanel) currently uses something like `API_URL = 'https://astudvpn.asuscomm.com/xctest'` and `.../mp3`. Change it to the new hostname.

### 4.1 XCResult frontend (e.g. xcoderesults.html)

In the script config at the top:

```javascript
var API_URL = 'https://api.assurance.st/xctest';
var API_KEY = 'YOUR_API_KEY';
```

(Use your real API key and, if you used a different subdomain, that hostname instead of `api.assurance.st`.)

### 4.2 MP3 frontend (e.g. mp3-strip.html)

```javascript
var API_URL = 'https://api.assurance.st/mp3';
var API_KEY = 'YOUR_API_KEY';
```

### 4.3 CORS

You already use `--origins "https://assurance.st,https://www.assurance.st"`. No change needed: the **origin** of the page is still assurance.st (or www); only the **API** host changed to api.assurance.st.

### 4.4 Upload updated HTML

Upload the modified `xcoderesults.html` and `mp3-strip.html` (or whatever names you use) to cPanel so the live site uses the new `API_URL` values.

---

## Part 5: Checks and optional hardening

### 5.1 Verify end-to-end

1. Open `https://assurance.st/xcoderesults.html` (or your frontend URL).
2. Upload a small .xcresult.zip and confirm the report is generated and downloaded.
3. Open the MP3 tool, upload a small MP3, confirm you get the stripped file.
4. In the browser’s Network tab, confirm requests go to `https://api.assurance.st/...`, not to astudvpn.asuscomm.com.

### 5.2 Confirm your IP is hidden

From another machine or a friend’s network:

```bash
nslookup api.assurance.st
```

You should see Cloudflare IPs (e.g. 104.x.x.x, 172.x.x.x), not your home IP. So “someone using the app” can no longer resolve the API hostname to your real address.

### 5.3 Optional: Restrict tunnel to your API

In `config.yml` you only have one hostname (`api.assurance.st`) and a 404 catch-all, so no other hostnames are served by this tunnel. If you add more hostnames later, add more `ingress` entries before the `http_status:404` rule.

### 5.4 Optional: Keep Caddy and tunnel to Caddy

If you prefer to keep Caddy on the Mac (e.g. for local HTTPS or another site), you can point the tunnel at Caddy instead of Flask:

- Run Caddy on 443 (or 8443) and proxy to `127.0.0.1:5050`.
- In `config.yml`, set `service: https://127.0.0.1:443` (or the port Caddy uses) instead of `http://127.0.0.1:5050`.

Then Caddy still terminates TLS locally; the tunnel still hides your IP. For “only the unified API” the simplest is tunnel → Flask directly.

---

## Summary

| Item | Before | After |
|------|--------|--------|
| API public URL | https://astudvpn.asuscomm.com/... | https://api.assurance.st/... |
| DNS for API | astudvpn.asuscomm.com → your home IP | api.assurance.st → Cloudflare IPs |
| Port forwarding | 80, 443 → Mac | Not needed for API |
| Caddy on Mac | Terminates HTTPS for API | Optional; can be stopped for API |
| Frontend | assurance.st (cPanel) | Unchanged |
| Flask | 127.0.0.1:5050 | Unchanged; tunnel connects to it |

After this, only Cloudflare’s IPs are exposed for the API; your home IP is no longer discoverable via the app’s API hostname.
