# Deployment Guide

This covers taking the Kronos web app (and the Discord/WhatsApp bots) from
"running on my laptop" to "running somewhere that stays up." Read the
**Security first** section before exposing anything beyond `127.0.0.1`.

## Table of contents

1. [Security first](#security-first)
2. [Option A -- keep it local (simplest, recommended to start)](#option-a----keep-it-local)
3. [Option B -- always-on on your own machine/VPS](#option-b----always-on-on-your-own-machinevps)
4. [Option C -- Docker](#option-c----docker)
5. [Option D -- a cloud VM (DigitalOcean/Hetzner/AWS EC2/etc.)](#option-d----a-cloud-vm)
6. [Option E -- PaaS (Render/Railway/Fly.io)](#option-e----paas-renderrailwayflyio)
7. [Deploying the Discord/WhatsApp bots](#deploying-the-discordwhatsapp-bots)
8. [Hardware/cost expectations](#hardwarecost-expectations)
9. [Troubleshooting](#troubleshooting)

---

## Security first

**As shipped, `webapp/` has no login system.** Anyone who can reach the
port can forecast, backtest, and edit the watchlist. That's fine on
`127.0.0.1` (only your machine can reach it). It is **not** fine to expose
directly to the internet without addressing at least one of these:

- **Simplest**: put it behind a reverse proxy with HTTP Basic Auth (nginx
  `auth_basic`, Caddy `basicauth`, or your PaaS's built-in password
  protection if it has one) -- a few lines of config, not a real user
  system, but stops randoms from finding it.
- **Better**: add a real login (Flask-Login + a users table) before putting
  it anywhere public. Not built here -- see `WEBAPP_README.md`'s "What I'd
  recommend adding next" for the seam to extend (`_user_id()` in
  `webapp/app.py` is where session-based identity currently lives).
- **Always**: run behind HTTPS (see nginx/Caddy configs below) and set a
  real `WEBAPP_SECRET_KEY` (see each option below) -- the default in
  `webapp/app.py` is a placeholder, not safe to ship as-is.
- **Never** run with `WEBAPP_DEBUG=true` (Flask's debugger) on anything
  reachable by anyone but you -- Flask's interactive debugger allows
  arbitrary code execution if someone finds it.

---

## Option A -- keep it local

The default, and honestly the right choice for a personal tool like this
unless you specifically need to reach it from another device.

```bash
cd Kronos-master
python webapp/app.py
```
Open http://127.0.0.1:5050. Nothing outside your machine can reach it.
Stop it with Ctrl+C. Nothing more to deploy.

**Want it reachable from your phone on the same WiFi, nothing more?**
```bash
# find your machine's LAN IP first (ipconfig on Windows, ifconfig/ip addr on Mac/Linux)
python webapp/app.py
```
Then from your phone (same network), visit `http://<your-lan-ip>:5050`.
Still not exposed to the internet -- just your local network.

---

## Option B -- always-on on your own machine/VPS

Runs the app in the background, restarts it if it crashes, and starts it
automatically on boot. Use a real WSGI server instead of Flask's dev server.

**1. Install a production server** (already in `requirements.txt`):
```bash
pip install gunicorn      # Linux/Mac
# or
pip install waitress      # Windows, or if you prefer a pure-Python option
```

**2. Set production environment variables** in `.env`:
```bash
WEBAPP_DEBUG=false
WEBAPP_SECRET_KEY=<generate one -- see below>
WEBAPP_PORT=5050
```
Generate a real secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**3. Run with gunicorn** (Linux/Mac):
```bash
gunicorn --workers 1 --threads 4 --timeout 300 --bind 0.0.0.0:5050 "webapp.app:app"
```
- `--workers 1`: Kronos's model is loaded once per worker process
  (`assistant/model_loader.py`'s singleton) -- multiple workers means
  multiple copies of the model in memory, which on 8GB RAM you generally
  don't want. Stick to 1 worker; `--threads 4` still lets it handle a few
  concurrent requests.
- `--timeout 300`: forecasts and especially backtests can take a while on
  CPU -- the default 30s timeout will kill long requests otherwise.

**Or with waitress** (Windows-friendly):
```bash
waitress-serve --host=0.0.0.0 --port=5050 --threads=4 webapp.app:app
```

**4. Keep it running with systemd** (Linux):
```ini
# /etc/systemd/system/kronos-webapp.service
[Unit]
Description=Kronos web app
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/Kronos-master
Environment="PATH=/path/to/Kronos-master/kronos_env/bin"
EnvironmentFile=/path/to/Kronos-master/.env
ExecStart=/path/to/Kronos-master/kronos_env/bin/gunicorn --workers 1 --threads 4 --timeout 300 --bind 0.0.0.0:5050 webapp.app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kronos-webapp
sudo systemctl status kronos-webapp     # check it's up
journalctl -u kronos-webapp -f          # tail logs
```

**5. Put nginx in front** (adds HTTPS + lets you use port 80/443):
```nginx
# /etc/nginx/sites-available/kronos
server {
    listen 80;
    server_name your-domain.com;

    # optional but recommended if you don't have a real login system yet
    auth_basic "Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;   # match gunicorn's --timeout above
    }
}
```
```bash
sudo apt install apache2-utils   # for htpasswd, if you used auth_basic above
sudo htpasswd -c /etc/nginx/.htpasswd yourusername
sudo ln -s /etc/nginx/sites-available/kronos /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```
Then add real HTTPS with Certbot (free, Let's Encrypt):
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## Option C -- Docker

Useful if you want a reproducible environment or plan to deploy to a
container platform (many of the PaaS options below accept a Dockerfile
directly).

Create `Dockerfile` in the project root (not included by default -- add it
if you want this path):
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV WEBAPP_DEBUG=false
EXPOSE 5050

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--timeout", "300", \
     "--bind", "0.0.0.0:5050", "webapp.app:app"]
```

Build and run:
```bash
docker build -t kronos-webapp .
docker run -d --name kronos -p 5050:5050 \
  --env-file .env \
  -v kronos_data:/app/assistant_data \
  -v kronos_models:/root/.cache/huggingface \
  kronos-webapp
```
The two `-v` volumes matter: without them, every container restart
re-downloads the Kronos model from Hugging Face and loses your watchlist
and conversation history.

**Memory limit note (8GB RAM machines)**: if running Docker on the same
laptop discussed earlier in this project, give the container a sensible
cap so it can't starve the host OS:
```bash
docker run -d --name kronos -p 5050:5050 --memory=6g --env-file .env ... kronos-webapp
```

---

## Option D -- a cloud VM

(DigitalOcean, Hetzner, Linode, AWS EC2, etc. -- any plain Linux box.)

1. Provision a VM. **Minimum spec: 2 vCPU, 8GB RAM** -- Kronos-base on CPU
   needs comparable resources to your laptop; go smaller only with
   Kronos-small (see [hardware expectations](#hardwarecost-expectations)).
2. SSH in, install Python 3.10+, git, clone/upload your project.
3. Follow **Option B** above (venv, gunicorn, systemd, nginx, certbot) --
   that whole section is written for exactly this scenario.
4. Point your domain's DNS A record at the VM's IP before running certbot.

Rough monthly cost for a 2 vCPU / 8GB box: **$20-48/month** depending on
provider (Hetzner tends to be cheapest, AWS/GCP most expensive for the same
specs). No GPU needed unless you want faster inference -- see below.

---

## Option E -- PaaS (Render/Railway/Fly.io)

Fastest path to "it's online" with no server management, at the cost of
less control and (usually) higher price per GB of RAM than a raw VM.

**General steps** (specifics vary by platform):
1. Push this repo to a GitHub repository (private is fine, most platforms
   support that).
2. Create a new "Web Service" pointing at the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn --workers 1 --threads 4 --timeout 300 --bind 0.0.0.0:$PORT webapp.app:app`
   (most PaaS inject `$PORT` -- don't hardcode 5050 here)
5. Set environment variables in the platform's dashboard: `WEBAPP_DEBUG=false`,
   `WEBAPP_SECRET_KEY=<generated>`, plus any of the optional API keys from
   `.env.example` you want.
6. **Pick a plan with at least 8GB RAM** for Kronos-base, or switch to
   `KRONOS_MODEL_ID=NeoQuasar/Kronos-small` for a plan with less.
7. **Add a persistent volume** if the platform supports one, mounted at
   `assistant_data/` -- otherwise your watchlist/conversation history/model
   cache resets on every redeploy. (Render: "Disks". Railway: "Volumes".
   Fly.io: `fly volumes create`.)

Rough cost: most PaaS 8GB-RAM tiers run **$25-50/month**; check current
pricing directly, it changes often.

---

## Deploying the Discord/WhatsApp bots

These are separate long-running processes from the web app -- run them
alongside it (same machine or a different one), not instead of it.

**Discord** (`integrations/discord_bot.py`): needs to run continuously to
stay connected. Same systemd pattern as Option B, just a different
`ExecStart`:
```ini
ExecStart=/path/to/kronos_env/bin/python integrations/discord_bot.py
```
No gunicorn needed here -- it's not a web server, it holds a persistent
connection to Discord's gateway.

**WhatsApp** (`integrations/whatsapp_bot.py`): this one *is* a small Flask
app (receiving Twilio's webhook), so it follows Option B/C/D/E the same way
the main webapp does, just with its own port and a public URL Twilio can
reach (ngrok for testing, a real domain for production).

---

## Hardware/cost expectations

| Setup | RAM | Notes |
|---|---|---|
| `Kronos-mini` | 2-4GB | Fastest, least accurate. Fine for a cheap VM/PaaS tier. |
| `Kronos-small` | 4-6GB | Balanced. Reasonable default for a budget deployment. |
| `Kronos-base` | 8GB+ | What this project defaults to. CPU-only is fine but slower per forecast; see `KRONOS_CPU_THREADS` in `.env.example` to tune. |

No GPU is required anywhere in this guide -- everything above assumes
CPU-only inference, same as the 8GB-RAM/no-GPU laptop this project was
tuned for earlier. A GPU (a cloud instance with one, e.g. AWS `g4dn` or
similar) would speed up forecasts/backtests significantly but roughly
doubles-to-quintuples hosting cost -- worth it only if response time really
matters for your use case.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| App works locally but 502/timeout when deployed | Increase your reverse proxy's `proxy_read_timeout` and gunicorn's `--timeout` -- forecasts/backtests take longer than typical web request timeouts (30s default in most proxies). |
| Watchlist/chat history resets after every deploy | You're not persisting `assistant_data/` -- add a volume/disk (see Docker and PaaS sections above). |
| "Out of memory" / process killed on a small instance | Your plan doesn't have enough RAM for `Kronos-base`. Switch to `Kronos-small` (`KRONOS_MODEL_ID` in `.env`) or upgrade the instance. |
| Multiple users' forecasts seem to interfere with each other | Make sure gunicorn/waitress is running with `--workers 1` -- see the note in Option B about why multiple workers duplicate the model in memory (this is about resource usage, not correctness, but it's the setting to check first). |
| Discord bot keeps disconnecting | Usually networking/firewall on the host, or the process getting killed (OOM) -- check `journalctl -u <service> -f` for the actual error, and confirm the systemd `Restart=always` is in place so it self-heals. |
| Can't get HTTPS working with Certbot | Confirm your domain's DNS A record actually points at the server's IP first (`dig your-domain.com`) -- Certbot can't issue a certificate for a domain that doesn't resolve to the box it's running on. |
