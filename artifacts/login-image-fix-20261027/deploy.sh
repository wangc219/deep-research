#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
exec 9>/var/lock/deepquest-web-assets.lock
flock -n 9
backup=/var/backups/deepquest/login-image-fix-20261027
mkdir -p "$backup" /var/tmp/deepquest-login-image-fix
image=$(docker inspect deepquest-web-1 --format '{{.Config.Image}}')
docker tag "$(docker inspect deepquest-web-1 --format '{{.Image}}')" deepquest-web:before-login-image-fix-20261027
stat -c '%a %n' web/public/equipment-login-hero.png > "$backup/source-permission-before.txt"
cat > /var/tmp/deepquest-login-image-fix/Dockerfile <<'EOF'
FROM deepquest-web:before-login-image-fix-20261027
RUN find /usr/share/nginx/html -type d -exec chmod 755 {} \; \
    && find /usr/share/nginx/html -type f -exec chmod 644 {} \;
EOF
docker build -q -t deepquest-web:login-image-fixed-20261027 /var/tmp/deepquest-login-image-fix
rollback() {
 docker tag deepquest-web:before-login-image-fix-20261027 "$image"
 CLOUD_WECHAT_COLLECTOR=1 bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 120 web
}
trap rollback ERR
chmod 644 web/public/equipment-login-hero.png
docker tag deepquest-web:login-image-fixed-20261027 "$image"
CLOUD_WECHAT_COLLECTOR=1 bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 120 web
test "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 https://www.deepquest.space/equipment-login-hero.png)" = 200
docker exec deepquest-web-1 sh -c 'test -z "$(find /usr/share/nginx/html -type f ! -perm -004 -print -quit)"'
trap - ERR
printf 'Static assets readable; production login image HTTP 200\n'
