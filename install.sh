#!/usr/bin/env bash
#
# GitGuardian AI — one-line installer
#
#   curl -fsSL https://raw.githubusercontent.com/Pavun57/gitguardian-ai/main/install.sh | bash
#
# What it does:
#   1. Checks prerequisites (docker, node, git; installs uv if missing)
#   2. Clones the repo (or updates in place if already cloned)
#   3. Creates .env with generated encryption/session secrets
#   4. Starts Postgres + Redis in Docker
#   5. Installs Python + dashboard dependencies, runs DB migrations
#   6. Prints the commands to start the app and the setup URL
#
set -euo pipefail

REPO_URL="https://github.com/Pavun57/gitguardian-ai.git"
INSTALL_DIR="${GG_INSTALL_DIR:-$HOME/gitguardian-ai}"

say()  { printf "\033[1;32m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[!]\033[0m %s\n" "$*"; }
die()  { printf "\033[1;31m[x]\033[0m %s\n" "$*" >&2; exit 1; }

# --- 1. prerequisites -------------------------------------------------------

say "Checking prerequisites..."
command -v git   >/dev/null || die "git is required: https://git-scm.com"
command -v node  >/dev/null || die "node 20+ is required: https://nodejs.org"
command -v docker >/dev/null || die "docker is required: https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1 || die "docker daemon is not running — start it and re-run"

if ! command -v uv >/dev/null; then
  say "Installing uv (Python package manager)..."
  curl -fsSL https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# --- 2. clone or update ------------------------------------------------------

if [ -d "$INSTALL_DIR/.git" ]; then
  say "Repo exists at $INSTALL_DIR — pulling latest..."
  git -C "$INSTALL_DIR" pull --ff-only || warn "pull failed, continuing with existing checkout"
else
  say "Cloning GitGuardian AI into $INSTALL_DIR..."
  git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# --- 3. .env with generated secrets ------------------------------------------

if [ ! -f .env ]; then
  say "Creating .env with generated secrets..."
  cp .env.example .env
  ENC_KEY=$(uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null \
            || python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
  SESSION_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))")
  sed -i "s|^MASTER_ENCRYPTION_KEY=.*|MASTER_ENCRYPTION_KEY=$ENC_KEY|" .env
  sed -i "s|^SESSION_SECRET=.*|SESSION_SECRET=$SESSION_KEY|" .env
else
  say ".env already exists — keeping it"
fi

# --- 4. databases -------------------------------------------------------------

say "Starting Postgres + Redis (Docker)..."
docker compose -f infrastructure/docker/docker-compose.yml up -d postgres redis

# --- 5. dependencies + migrations ---------------------------------------------

say "Installing Python dependencies..."
uv sync

say "Running database migrations..."
uv run alembic upgrade head

say "Installing dashboard dependencies..."
(cd apps/dashboard && npm install --no-fund --no-audit)

say "Building the test-runner image..."
docker build -t gitguardian/test-runner:latest -f infrastructure/docker/Dockerfile.test-runner infrastructure/docker

# --- 6. gitguardian CLI -------------------------------------------------------

say "Installing the gitguardian command..."
mkdir -p "$HOME/.local/bin"
cp bin/gitguardian "$HOME/.local/bin/gitguardian"
chmod +x "$HOME/.local/bin/gitguardian"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) warn "~/.local/bin is not on your PATH — add: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

# --- done ---------------------------------------------------------------------

cat <<EOF

$(printf '\033[1;32m')✔ GitGuardian AI installed$(printf '\033[0m')

Everything is one command away:

  gitguardian start       start all services (db, api, worker, dashboard, tunnel)
  gitguardian status      show what's running + URLs
  gitguardian stop        stop all services
  gitguardian logs api    tail a service log
  gitguardian uninstall   remove everything

Run it now:

  gitguardian start

Then open http://localhost:3000/setup — the wizard creates the GitHub App in
one click and stores your credentials (encrypted). The smee webhook channel is
enterable in the dashboard (Settings → Webhook tunnel) — no .env editing.
EOF
