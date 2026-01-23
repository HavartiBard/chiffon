# Windows GPU Machine Bootstrap Guide

Setup script for Windows machines running WSL2 that will host llama.cpp inference servers and other GPU workloads.

**Target:** Chiffon deployment uses SSH for automated llama.cpp deployment and management.

## Prerequisites

- Windows 10/11 with WSL2 enabled
- Docker Desktop with WSL2 backend
- NVIDIA GPU with CUDA support (recommended for inference)
- Administrator access to Windows

## Part 1: Install OpenSSH Server in WSL2

Open **WSL2 terminal** and run:

```bash
# Update package list
sudo apt update

# Install OpenSSH Server and client
sudo apt install -y openssh-server openssh-client

# Start SSH service
sudo service ssh start

# Enable SSH to start automatically on WSL2 boot
sudo systemctl enable ssh

# Verify SSH is running
sudo systemctl status ssh
# Should show "active (running)"

# Verify SSH is listening on port 22
sudo ss -tulpn | grep 22
# Should show:
#   LISTEN 0.0.0.0:22
#   LISTEN [::]:22
```

## Part 2: Configure Windows Firewall

Open **PowerShell as Administrator** and run:

```powershell
# Create inbound firewall rule for SSH
New-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -DisplayName "OpenSSH Server (sshd)" -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

Verify the rule was created:

```powershell
Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP"
```

Should show `Enabled : True`

## Part 3: Configure Port Forwarding (WSL2 → Windows Host)

**Important:** WSL2 runs in a Hyper-V virtual network, not directly on the Windows network interface. We need to forward port 22 from the Windows host to WSL2.

In **PowerShell (as Administrator)**, run:

```powershell
# Get your Windows host IP (should be 192.168.20.x in homelab)
Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.InterfaceAlias -like "*Ethernet*" -or $_.InterfaceAlias -like "*Wi-Fi*"}

# Get WSL2 IP
wsl hostname -I

# Add port forwarding rule (replace IPs with your values)
# Replace 192.168.20.154 with your Windows host IP
# Replace 172.20.90.75 with your WSL2 IP (from wsl hostname -I)
netsh interface portproxy add v4tov4 listenport=22 listenaddress=192.168.20.154 connectport=22 connectaddress=172.20.90.75

# Verify the rule
netsh interface portproxy show all
```

**Expected output from `netsh interface portproxy show all`:**

```
Listen on ipv4:   Connect to ipv4:
Address         Port  Address         Port
192.168.20.154  22    172.20.90.75    22
```

## Part 4: Test SSH Access (From Dev Machine)

From your development machine (Linux/Mac):

```bash
# Test SSH connectivity
ssh ubuntu@spraycheese.lab.klsll.com
# Or use the IP:
ssh ubuntu@192.168.20.154

# Should prompt for WSL2 password
# Enter your WSL2 user password
```

If successful, you'll see the WSL2 prompt.

## Part 5: Set Up Passwordless SSH Key Authentication

For automated deployment without password prompts, set up SSH key auth.

**From your dev machine, copy your public key to the Windows box:**

```bash
# Option 1: Automatic key copy (if ssh-copy-id is available)
ssh-copy-id -i ~/.ssh/id_ed25519_homelab ubuntu@spraycheese.lab.klsll.com

# Option 2: Manual key copy
# First, copy your public key
cat ~/.ssh/id_ed25519_homelab.pub

# Then SSH to Windows
ssh ubuntu@spraycheese.lab.klsll.com

# In the WSL2 terminal, create SSH directory and add your key
mkdir -p ~/.ssh
# Paste your public key content:
echo "ssh-ed25519 AAAA..." >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
chmod 700 ~/.ssh
exit

# Back on dev machine, test passwordless login
ssh ubuntu@spraycheese.lab.klsll.com
# Should NOT prompt for password
```

## Part 6: Set Up Directory Structure for Chiffon

From your dev machine (via SSH):

```bash
ssh ubuntu@spraycheese.lab.klsll.com

# In WSL2, create the chiffon directory
mkdir -p ~/chiffon/models
mkdir -p ~/chiffon/cache

# Verify
ls -la ~/chiffon
# Should show: models/ and cache/ directories
```

## Part 7: Verify Complete Setup

From your dev machine:

```bash
# Test SSH access
ssh ubuntu@spraycheese.lab.klsll.com "echo 'SSH access OK'"

# Test Docker is available
ssh ubuntu@spraycheese.lab.klsll.com "docker ps"

# Check available GPU
ssh ubuntu@spraycheese.lab.klsll.com "nvidia-smi"
# Should list your NVIDIA GPU(s)
```

All three commands should succeed without password prompts.

## Part 8: Deployment

Once bootstrap is complete, you can deploy llama.cpp:

From your dev machine, in the chiffon project directory:

```bash
# Copy llama.cpp docker-compose
scp -i ~/.ssh/id_ed25519_homelab docker-compose.llamacpp.yml ubuntu@spraycheese.lab.klsll.com:~/chiffon/docker-compose.yml

# SSH and start the service
ssh -i ~/.ssh/id_ed25519_homelab ubuntu@spraycheese.lab.klsll.com "cd ~/chiffon && docker-compose up -d"

# Verify llama.cpp is running
ssh -i ~/.ssh/id_ed25519_homelab ubuntu@spraycheese.lab.klsll.com "curl -s http://localhost:8000/health"
# Should return: {"status":"ok"}
```

Or use the automated deployment script:

```bash
./scripts/deploy-production.sh --windows-llamacpp
```

## Troubleshooting

### SSH Connection Timeout

```bash
# Check if SSH is running on Windows
# In WSL2 terminal on Windows:
sudo systemctl status ssh

# Check if firewall rule exists
# In PowerShell on Windows:
Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" | Select Enabled

# Check if port forwarding is configured
# In PowerShell on Windows:
netsh interface portproxy show all
```

### Port Forwarding Not Working

If port forwarding was added but doesn't work, remove and re-add it:

```powershell
# In PowerShell (as Administrator)

# Remove old rule
netsh interface portproxy delete v4tov4 listenport=22 listenaddress=192.168.20.154

# Get current IPs
wsl hostname -I
# Get Windows host IP:
Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.InterfaceAlias -like "*Ethernet*"}

# Re-add with correct IPs
netsh interface portproxy add v4tov4 listenport=22 listenaddress=192.168.20.154 connectport=22 connectaddress=172.20.90.75

# Verify
netsh interface portproxy show all
```

### SSH Key Not Working

```bash
# Verify public key is in authorized_keys
ssh ubuntu@spraycheese.lab.klsll.com "cat ~/.ssh/authorized_keys"

# Should list your public key (ssh-ed25519 AAAA...)

# Check SSH key permissions
ssh ubuntu@spraycheese.lab.klsll.com "ls -la ~/.ssh/"
# Should show:
#   -rw------- (600) authorized_keys
#   drwx------ (700) .ssh directory
```

### Docker Not Available in WSL2

```bash
# Ensure Docker Desktop is running on Windows
# Then in WSL2:
docker ps

# If still not found, reinstall Docker context for WSL2:
# In PowerShell:
wsl --install --distribution Ubuntu
# Then in WSL2:
sudo apt install docker.io
sudo usermod -aG docker $USER
```

## Makefile (Optional)

For convenience, you can create a `Makefile` in `~/chiffon/` on each Windows machine:

```makefile
.PHONY: deploy logs status health

deploy:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f llamacpp

status:
	docker-compose ps

health:
	curl -s http://localhost:8000/health | jq .

inference-test:
	curl -s http://localhost:8000/v1/completions \
		-H "Content-Type: application/json" \
		-d '{"model":"mistral","prompt":"Hello world","max_tokens":100}' | jq .
```

Then deploy easily:

```bash
cd ~/chiffon
make deploy
make health
```

## Next Steps

1. Repeat this bootstrap on each Windows GPU machine in your fleet
2. Update `WINDOWS_HOST` variable in `/scripts/deploy-production.sh` for each new machine
3. Run `./scripts/deploy-production.sh --windows-llamacpp` to deploy llama.cpp
4. Run `./scripts/deploy-validate.sh` from orchestrator to validate all machines are accessible
