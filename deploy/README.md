# Deploy OmniFox on an Ubuntu server

Runs OmniFox, Postgres and Caddy with Docker on one server (Ubuntu 22.04 or newer). Caddy gets a
free HTTPS certificate automatically.

You need:

- A server with a public IP address and SSH access.
- A web address for the app. Either a domain or subdomain whose DNS points at the server
  (for example `omnifox.example.com`), or, without a domain, `<server-ip-with-dashes>.sslip.io`
  (for example `203-0-113-10.sslip.io` for the IP 203.0.113.10), which always points at that IP.
- API keys for Gemini and ExportComments.

In the steps below, `<repo-url>` is the SSH address of the GitHub repository holding this code
(for example `git@github.com:your-org/omnifox.git`).

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
git clone <repo-url> ~/omnifox
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

Set `SITE_ADDRESS` to the web address (no `https://`). Paste the three generated lines into `.env`, then fill in `GEMINI_API_KEY`,
`EXPORTCOMMENTS_API_KEY`, `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD` (12+ characters,
letters and non-letters). `RESEND_API_KEY`, `EMAIL_FROM` and the Google values can stay empty (see Email below).

Only email addresses on the allowed domains can join or be invited. These are set in
`ALLOWED_DOMAINS` in `backend/utils/whitelist.py`.

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

## Email (Resend)

OmniFox can email people their Create Account link, a welcome when their join request is
accepted, and "Forgot password?" reset links. Without email setup everything still works: admins
copy the links from Team Members and send them by hand.

This needs someone who can change DNS for a domain the company owns. Use a subdomain
such as `mail.example.com` so the company's normal email is not affected.

1. **Add the domain in Resend.** Sign in at resend.com, open **Domains > Add domain**, and enter
   the subdomain (for example `mail.example.com`).
2. **Add the DNS records.** Resend lists a few records (an MX and TXT record for SPF, and a TXT
   record for DKIM). Add each one exactly as shown at the DNS provider, then click **Verify** in
   Resend. It can take from a few minutes to a few hours.
3. **Create an API key.** In Resend open **API Keys > Create API key**, choose **Sending access**,
   and limit it to that domain.
4. **Add two lines to `deploy/.env` on the server:**

   ```
   RESEND_API_KEY=re_xxxxxxxxxxxx
   EMAIL_FROM="OmniFox <omnifox@mail.example.com>"
   ```

   The address in `EMAIL_FROM` must be on the verified domain. It doesn't need a real mailbox.
5. **Apply it:** `docker compose -f docker-compose.server.yml up -d`

To check it, open the login page. It now shows a **Forgot your password?** link. Request a reset
for your own account and the email should arrive within a minute. If it doesn't, look for
`Email failed` in `docker compose -f docker-compose.server.yml logs backend`.

To turn email off again, empty both lines and run `up -d`.

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
