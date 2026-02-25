# Option A (Expose your Mac backend): Security risks and mitigations

## Context
Option A means your Mac runs a public-facing service reachable from the internet (eg `site.asuscom.com:5454`), which accepts large uploads (up to ~1 GB), processes them using Xcode tooling, then returns generated HTML/PDF and deletes artefacts.

This is feasible, but you must treat it as an internet-exposed file ingestion and code-execution-adjacent service.

## Main security risks

### 1) Unauthorised use of your service (abuse)
**What can happen**
- Anyone who finds the endpoint can upload files and use your Mac to generate reports.
- Your CPU/disk/network get consumed, making the Mac slow or unusable.
- Your home bandwidth gets saturated.

**Mitigations**
- Require authentication on every endpoint (upload/status/download/cleanup).
  - At minimum: a long random API key in an HTTP header.
  - Better: short-lived signed tokens minted by your website.
- Rate limit by IP and by token.
- Add a hard maximum upload size and concurrency limit.

### 2) Denial of Service (DoS) and resource exhaustion
**What can happen**
- Large uploads or many parallel uploads fill disk, RAM, CPU.
- Zip bombs (tiny zip expands to huge) can fill disk fast.
- Many small requests to status endpoints can overload the service.

**Mitigations**
- Disk quotas for job directory and a global cap (eg refuse new jobs if > X GB in use).
- Limit concurrent jobs (eg 1-2 at a time).
- Refuse archives with suspicious compression ratio or too many files.
- Enforce timeouts and max processing time per job.
- Implement TTL cleanup (eg delete jobs older than 30-60 min, regardless of state).
- Rate limit status polling endpoints.

### 3) Remote code execution (RCE) via input handling
**What can happen**
- Malicious zip content exploits a parser, an unzip tool, or any library you use.
- Path traversal in zip entries (eg `../../...`) can overwrite files outside your job directory.
- If you shell out to tools incorrectly, input could lead to command injection.

**Mitigations**
- Never trust zip entry paths:
  - Extract only into a per-job directory.
  - Strip absolute paths.
  - Reject entries containing `..` segments.
- Prefer safe libraries for extraction; avoid `unzip` with unsafe flags.
- Never build shell commands by string concatenation.
  - Use subprocess with argument lists.
- Run the conversion under a dedicated low-privilege macOS user.
- Consider sandboxing:
  - Run the service in a container/VM if possible, or at least limit filesystem access.

### 4) Exposure of sensitive test artefacts
**What can happen**
- `.xcresult` bundles may include:
  - screenshots
  - logs
  - failure traces
  - internal URLs/tokens accidentally logged
- If your download URLs are guessable, others could retrieve private reports.

**Mitigations**
- Use unguessable job IDs (UUIDv4 is fine) and never allow directory listing.
- Require auth for download (do not rely on obscurity).
- Delete artefacts after download, plus TTL cleanup.
- Optionally encrypt at rest (less critical if TTL is short and disk is protected).

### 5) Transport security issues (MITM, credential leak)
**What can happen**
- Without HTTPS, uploads and tokens can be sniffed.
- With misconfigured TLS, browsers may refuse to connect or downgrade security.

**Mitigations**
- Require HTTPS only (redirect HTTP to HTTPS).
- Use modern TLS config via a mature reverse proxy (eg Caddy).
- Use HSTS if you’re confident the domain will always serve HTTPS.

### 6) Attacks on your home network via the exposed host
**What can happen**
- If the service or Mac is compromised, attacker may pivot:
  - scan your LAN
  - access other devices
  - steal files/keys
  - persist via launch agents

**Mitigations**
- Put the Mac on a separate VLAN/guest network if you can.
- Ensure macOS firewall is enabled and only exposes needed ports.
- Keep macOS and Xcode updated.
- Do not run the service as an admin account.
- Minimise what the service user can read/write (no access to personal folders).

### 7) Brute force and credential stuffing
**What can happen**
- If you use basic auth with a weak password, it will be hammered.
- Attackers will attempt common passwords repeatedly.

**Mitigations**
- If using basic auth: use long random passwords.
- Prefer token-based auth with rotation.
- Rate limit auth failures.
- Consider allowlisting IP ranges if your users are known (eg office VPN).

### 8) Logging leaks
**What can happen**
- You log request headers by accident (including API keys).
- Logs may contain file names, paths, or extracted content.

**Mitigations**
- Never log secrets (strip headers like `Authorization`, `X-API-Key`).
- Rotate logs and restrict permissions.
- Keep logs minimal.

### 9) Supply chain / dependency risk
**What can happen**
- Python packages or node packages for your UI could have vulnerabilities.

**Mitigations**
- Pin dependencies.
- Update regularly.
- Keep the backend small and dependency-light.

## Practical “minimum safe” checklist for Option A

### Network and TLS
- Terminate TLS with a reverse proxy (Caddy recommended).
- Expose only 443 publicly (avoid exposing 5454 directly if possible).
- Block all other inbound ports at the router and macOS firewall.

### Auth
- Require an API key on all endpoints.
- Rotate the key periodically.
- Store it server-side only if possible (best), otherwise accept that a browser-held key can be extracted.

### Resource controls
- Limit upload size (eg 1 GB max).
- Limit concurrent jobs to 1-2.
- Global disk cap for job directories (eg 5-10 GB).
- TTL cleanup (eg 30-60 minutes).

### Input safety
- Defend against zip traversal and zip bombs.
- Extract only to per-job directories.
- Run conversion as a dedicated low-privilege user.

### Privacy
- Require auth to download results.
- Use unguessable job IDs.
- Delete inputs/outputs after download and via TTL.

## Residual risk (what you cannot fully eliminate)
Even with good mitigations, Option A always carries higher risk than a tunnel approach because:
- your Mac is directly reachable and constantly scanned by bots
- any future bug in your service or dependencies becomes an internet-facing vulnerability

If the Mac contains important personal/work secrets, or if you cannot maintain patching and monitoring, prefer a tunnel (Option B) or a cloud Mac worker.

## Recommendation
Option A is acceptable if you:
- enforce HTTPS + auth everywhere
- implement strict resource limits
- harden zip handling
- run as a non-admin user
- keep the machine updated
- ideally isolate the Mac from your main LAN

If you want, I can provide:
- a hardened Caddy config (TLS, rate limit, size limits)
- a FastAPI backend skeleton with safe zip extraction, job queue, TTL cleanup, and endpoints
- frontend JS wiring for upload, polling, and auto-download