# Azure Linux Standard_B2s — deploy notes

This bot is a single Python process + SQLite file. **Standard_B2s** (2 vCPU, 4 GiB RAM, burstable) is enough. Prefer **Ubuntu 22.04/24.04 LTS** in **Central India** (`centralindia`) if you want lower latency to CoinDCX.

## Rough cost (verify in the Azure Pricing Calculator)

Published Linux Pay-as-you-go figures (compute only, ~2026; they move):

| Item | Ballpark |
| --- | --- |
| Standard_B2s Linux, Central India | ~**$0.0448 / hour** ≈ **$33 / month** if left running 24×7 |
| East US (often cheaper) | ~$0.0416 / hour ≈ $30 / month |
| 32 GiB Standard HDD OS disk | a few USD / month |
| Egress | tiny for this bot (public REST every 2 minutes) |
| Public IP | small extra if you attach one |

**24×7 paper trading ≈ $35–45 / month** all-in at list price. Student / Azure credits can cover that — which is why a **budget alert** is mandatory so the VM does not silently eat the rest of a credit balance (disks, IPs, and a forgotten VM keep billing).

B2s is **burstable**. This loop is idle most of the second; CPU credits will not be the constraint. Disk **is**: keep `data/ledger.sqlite` on the **OS managed disk**, not the ephemeral resource disk (`/mnt` on many Ubuntu images).

Stopped vs deallocated: **Stop from the Azure Portal (deallocate)** or `az vm deallocate`. “Stopped” from inside the guest still bills cores.

## Minimal VM setup

```bash
# on the VM
sudo apt-get update
sudo apt-get install -y python3 python3-venv git
sudo useradd --system --home /opt/paperbot --shell /usr/sbin/nologin paperbot || true
sudo mkdir -p /opt/paperbot
sudo rsync -a --exclude .venv --exclude data ./ /opt/paperbot/   # from your copy of the repo
sudo mkdir -p /opt/paperbot/data
sudo cp /opt/paperbot/.env.example /opt/paperbot/.env
sudo chown -R paperbot:paperbot /opt/paperbot

cd /opt/paperbot
sudo -u paperbot python3 -m paperbot doctor
sudo -u paperbot python3 -m paperbot run --once

sudo cp /opt/paperbot/deploy/paperbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now paperbot
sudo journalctl -u paperbot -f
```

Kill switch on the box: `sudo -u paperbot python3 -m paperbot kill` (creates `/opt/paperbot/data/KILL` if `WorkingDirectory` is `/opt/paperbot`).

## Docker Compose

From the repo root, with a `.env` copied from `.env.example`:

```bash
docker compose -f deploy/docker-compose.yml up --build -d
docker compose -f deploy/docker-compose.yml logs -f
```

Ledger lives in `./data` on the host.

## How to set Azure budget alerts (so credits are not burned)

Do this **before** leaving the VM running.

1. Portal → **Cost Management + Billing** → select your subscription / billing scope.
2. **Budgets** → **Add**.
3. Scope: this subscription (or a resource group that contains *only* this VM + disk + IP).
4. Amount: something you will notice, e.g. **$15** or **₹1,000** for a credit-guard, not the full student grant.
5. Reset period: **Monthly**.
6. Alert conditions: **50%**, **80%**, **100%** of budget.
7. Alert recipients: **your email**. Add a second action group SMS if credits are scarce.
8. (Strongly recommended) Create the VM in a **dedicated resource group** named like `rg-paperbot` so the budget can target that group only.

Also:

- Enable **Cost analysis** anomaly / scheduled export if available on your offer.
- Set an **auto-shutdown** schedule on the VM (Portal → VM → Auto-shutdown) if you only need daytime paper data. Unattended 24×7 is optional.
- Delete unused **Public IPs** and **disks** after you deallocate; they bill separately.
- Do **not** attach extra Standard_SSD / Premium disks for this project.
- Spending credits: some offers exclude marketplace images; use Canonical Ubuntu from Azure.

Official docs: [Create and manage Azure budgets](https://learn.microsoft.com/azure/cost-management-billing/costs/tutorial-acm-create-budgets).

## Network

Outbound HTTPS to `api.coindcx.com` (and `public.coindcx.com` if you later add sockets) is required. No inbound ports are needed for the bot. If you SSH, use key auth and restrict NSG to your IP.

## What not to put on this VM

CoinDCX **API keys**. Phase-1 will refuse to start if keys or `ARM_LIVE_TRADING` are present. Keys on a $33 box are a gift to attackers.
