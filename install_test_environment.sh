#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [[ "${EUID}" -eq 0 ]]; then
  printf 'Run this script as your normal user; it will request sudo when needed.\n' >&2
  exit 1
fi

if [[ ! -r /etc/os-release ]]; then
  printf 'Cannot identify this Linux distribution. Ubuntu and Debian are supported.\n' >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID}" != "ubuntu" && "${ID}" != "debian" ]]; then
  printf 'Unsupported distribution: %s. Ubuntu and Debian are supported.\n' "${ID}" >&2
  exit 1
fi

if [[ -z "${VERSION_CODENAME:-}" ]]; then
  printf 'Missing distribution codename in /etc/os-release.\n' >&2
  exit 1
fi

sudo -v
sudo apt-get update
sudo apt-get install -y ca-certificates curl python3 python3-venv python3-pip openssl

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
  "$(dpkg --print-architecture)" "${ID}" "${VERSION_CODENAME}" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "${USER}"

if [[ ! -f .env ]]; then
  cat > .env <<EOF
MYSQL_DATABASE=collectflow
MYSQL_USER=collectflow
MYSQL_PASSWORD=$(openssl rand -hex 24)
MYSQL_ROOT_PASSWORD=$(openssl rand -hex 24)
COLLECTFLOW_ADMIN_USERNAME=admin
COLLECTFLOW_ADMIN_PASSWORD=$(openssl rand -hex 24)
COLLECTFLOW_ADMIN_NAME=System Administrator
COLLECTFLOW_SEED_DEMO_DATA=false
SESSION_COOKIE_SECURE=false
EOF
  chmod 600 .env
  printf 'Created .env with unique local secrets (permissions 600).\n'
else
  printf 'Keeping existing .env; verify that its values are not placeholders.\n'
fi

if grep -q 'replace-with-' .env; then
  printf 'Replace placeholder values in .env before starting MySQL and CollectFlow.\n' >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest test_logic.py test_server.py

sudo docker compose up --build -d --wait --wait-timeout 180

if [[ -s collectflow.db ]]; then
  sudo docker compose exec -T collectflow python migrate_sqlite_to_mysql.py --source /migration/collectflow.db
fi

sudo docker compose exec -T collectflow python -m unittest test_logic.py test_server.py

python3 - <<'PY'
import json
import os
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

with open('.env', encoding='utf-8') as env_file:
    for line in env_file:
        key, separator, value = line.strip().partition('=')
        if separator and key and not key.startswith('#'):
            os.environ[key] = value.strip().strip('"').strip("'")

if 'replace-with-' in os.environ.get('COLLECTFLOW_ADMIN_PASSWORD', ''):
    raise SystemExit('Replace the placeholder admin password in .env, then rerun this script.')

base_url = 'http://127.0.0.1:8001'
with urllib.request.urlopen(f'{base_url}/health', timeout=10) as response:
    health = json.load(response)
assert health == {'status': 'ok', 'database': 'ok'}, health

anonymous_request = urllib.request.Request(f'{base_url}/api/users')
try:
    urllib.request.urlopen(anonymous_request, timeout=10)
except urllib.error.HTTPError as error:
    error.read()
    assert error.code == 401, error.code
else:
    raise AssertionError('Anonymous user-list access was not rejected')

cookie_jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
login = json.dumps({
    'username': os.environ['COLLECTFLOW_ADMIN_USERNAME'],
    'password': os.environ['COLLECTFLOW_ADMIN_PASSWORD'],
}).encode()
request = urllib.request.Request(
    f'{base_url}/api/login',
    data=login,
    headers={'Content-Type': 'application/json'},
    method='POST',
)
with opener.open(request, timeout=10) as response:
    user = json.load(response)['user']
assert user['role'] == 'admin', user

for endpoint in ('/api/users', '/api/audit', '/api/metrics'):
    with opener.open(f'{base_url}{endpoint}', timeout=10) as response:
        assert response.status == 200, (endpoint, response.status)

print('MySQL health, anonymous rejection, administrator login, users, audit, and metrics: OK')
PY

printf '\nCollectFlow is running at http://localhost:8001\n'
printf 'Administrator username: see COLLECTFLOW_ADMIN_USERNAME in .env\n'
printf 'Administrator password: see COLLECTFLOW_ADMIN_PASSWORD in .env\n'
printf 'Docker access was added to group "docker"; log out/in to use Docker without sudo.\n'