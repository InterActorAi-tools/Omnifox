# Deploy OmniFox on an Ubuntu server

Runs OmniFox, Postgres and Caddy with Docker on one server. Caddy gets a free HTTPS
certificate automatically. Without a domain, use `<your-ip-with-dashes>.sslip.io`
(for example `79-98-31-17.sslip.io`), which always points at that IP.

## 1. Update the server

```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

## 2. Open the firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable
```

If your hosting provider has its own firewall panel, allow ports 22, 80 and 443 there too.

## 3. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit
```

Log in again so the `docker` group applies.

## 4. Get the code

The repo is private, so give the server a read-only deploy key:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

Add the printed key in GitHub: repo **Settings > Deploy keys > Add deploy key** (leave write access off). Then:

```bash
git clone git@github.com:AboJadya/omnifox.git ~/omnifox
cd ~/omnifox/deploy
```

## 5. Create the settings file

```bash
cp .env.example .env
chmod 600 .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
echo "JWT_SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n')"
echo "DATA_ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_')"
nano .env
```

Paste the three generated lines into `.env`, then fill in `GEMINI_API_KEY`,
`EXPORTCOMMENTS_API_KEY`, `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD` (12+ characters,
letters and non-letters). `RESEND_API_KEY` and the Google values can stay empty.

Keep a copy of `.env` somewhere safe. Without `DATA_ENCRYPTION_KEY` the stored data can't be read.

## 6. Start it

```bash
docker compose -f docker-compose.server.yml up -d --build
docker compose -f docker-compose.server.yml ps
```

The first build takes a few minutes. Open `https://<SITE_ADDRESS>` and sign in with the admin email
and password. Then delete the `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD` lines from `.env` and run
`up -d` again.

## Day to day

- **Logs:** `docker compose -f docker-compose.server.yml logs -f backend`
- **Update:** `git pull && docker compose -f docker-compose.server.yml up -d --build`
- **Audit log:** admins see every sign-in, failed sign-in, role change, reset link, project change,
  upload, download and deletion in the **Audit Log** tab of the dashboard.
- **Move to a real domain later:** point the domain's DNS at the server, set `SITE_ADDRESS` to it in `.env`,
  and run `up -d`.

## Backups

`backup.sh` saves the database and uploaded files to `~/omnifox-backups` and keeps 14 days.
Run it every night at 3 AM:

```bash
(crontab -l 2>/dev/null; echo "0 3 * * * $HOME/omnifox/deploy/backup.sh") | crontab -
```

Copy the backups off the server now and then (for example `scp` to your Mac). They are useless
without `DATA_ENCRYPTION_KEY`, so keep `.env` in a separate safe place, not next to the backups.

To restore a database backup:

```bash
docker compose -f docker-compose.server.yml exec -T db pg_restore -U omnifox -d omnifox --clean < ~/omnifox-backups/db-YYYY-MM-DD.dump
```

## Security checklist

Already handled by the setup above:

- Only ports 22, 80 and 443 are open. Postgres and the backend are reachable only inside Docker.
- HTTPS everywhere, with HSTS. Sign-in cookies are HttpOnly and Secure.
- Production mode is forced (`DEBUG=False`), and the API docs pages are switched off.
- Content Security Policy, clickjacking and MIME-sniffing headers are set.
- Sign-in, 2FA, password, sign-up, reset and AI routes are rate limited.
- Stored comments, results and IPs are encrypted with `DATA_ENCRYPTION_KEY`.
- Container logs are capped at 50 MB each.

Worth doing yourself:

- Use SSH keys and turn off password login for SSH (`PasswordAuthentication no` in `/etc/ssh/sshd_config`).
- Turn on automatic security updates: `sudo apt install unattended-upgrades`.
- Sign in as admin and turn on 2FA under your profile.
