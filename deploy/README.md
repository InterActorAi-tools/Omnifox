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
- **Back up the database:**
  `docker compose -f docker-compose.server.yml exec db pg_dump -U omnifox omnifox > ~/omnifox-$(date +%F).sql`
- **Move to a real domain later:** point the domain's DNS at the server, set `SITE_ADDRESS` to it in `.env`,
  and run `up -d`.
