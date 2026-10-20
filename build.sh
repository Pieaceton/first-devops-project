#!/usr/bin/env bash
#
# Сборка релизных пакетов приложения.
#
# Создаёт три формата релиза:
#   * dist/app-release.tar.gz             - исходники, метаданные и байткод;
#   * dist/devops-app.pyz                 - единый исполняемый файл (zipapp);
#   * dist/devops-app_<VERSION>_all.deb   - установочный пакет Debian/Ubuntu.
#
# Использование:
#   ./build.sh                - сборка с автоматическим определением коммита
#   VERSION=1.2.3 ./build.sh  - сборка с заданной версией
#
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

APP_NAME="app-release"
APP_BINARY="devops-app"
DIST_DIR="dist"
STAGE_DIR="${DIST_DIR}/${APP_NAME}"
ARCHIVE="${DIST_DIR}/${APP_NAME}.tar.gz"
PYZ_SRC="${DIST_DIR}/.pyz-src"
PYZ="${DIST_DIR}/${APP_BINARY}.pyz"
DEB_STAGE="${DIST_DIR}/.deb-stage"

VERSION="${VERSION:-1.0.0}"
DEB="${DIST_DIR}/${APP_BINARY}_${VERSION}_all.deb"

# Метаданные сборки: коммит, ветка, дата
if git rev-parse --git-dir > /dev/null 2>&1; then
    COMMIT_SHA="$(git rev-parse HEAD)"
    COMMIT_SHORT="$(git rev-parse --short HEAD)"
    COMMIT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
    COMMIT_DATE="$(git log -1 --format=%cI)"
    # При сборке по тегу checkout выполнен в detached HEAD: показываем имя тега
    if [ "$COMMIT_BRANCH" = "HEAD" ]; then
        COMMIT_BRANCH="$(git describe --tags --exact-match 2> /dev/null || echo "detached")"
    fi
else
    COMMIT_SHA="unknown"
    COMMIT_SHORT="unknown"
    COMMIT_BRANCH="unknown"
    COMMIT_DATE="unknown"
fi

BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PYTHON_VERSION="$(python3 --version 2>&1)"

echo "==> Очистка предыдущей сборки"
rm -rf "$STAGE_DIR" "$ARCHIVE" "$PYZ" "$PYZ_SRC" "$DEB_STAGE" "$DEB"
mkdir -p "$STAGE_DIR"

echo "==> Копирование исходников"
cp main.py "$STAGE_DIR/main.py"

echo "==> Компиляция байткода"
python3 -m compileall -q "$STAGE_DIR/main.py" > /dev/null

echo "==> Формирование BUILD_INFO.txt"
cat > "$STAGE_DIR/BUILD_INFO.txt" << EOF
name: ${APP_NAME}
version: ${VERSION}
commit: ${COMMIT_SHA}
commit_short: ${COMMIT_SHORT}
branch: ${COMMIT_BRANCH}
commit_date: ${COMMIT_DATE}
build_date: ${BUILD_DATE}
python: ${PYTHON_VERSION}
EOF

echo "==> Упаковка архива ${ARCHIVE}"
tar -czf "$ARCHIVE" -C "$DIST_DIR" "$APP_NAME"

echo "==> Сборка исполняемого файла ${PYZ} (zipapp)"
mkdir -p "$PYZ_SRC"
cp main.py "$PYZ_SRC/main.py"
python3 -m zipapp "$PYZ_SRC" -o "$PYZ" -p "/usr/bin/env python3" -m "main:main"
chmod 0755 "$PYZ"

echo "==> Подготовка структуры пакета ${DEB}"
mkdir -p "${DEB_STAGE}/DEBIAN" \
         "${DEB_STAGE}/usr/local/bin" \
         "${DEB_STAGE}/etc/systemd/system" \
         "${DEB_STAGE}/opt/${APP_BINARY}"

install -m 0755 "$STAGE_DIR/main.py" "${DEB_STAGE}/opt/${APP_BINARY}/main.py"
install -m 0644 "$STAGE_DIR/BUILD_INFO.txt" "${DEB_STAGE}/opt/${APP_BINARY}/BUILD_INFO.txt"

cat > "${DEB_STAGE}/usr/local/bin/${APP_BINARY}" << EOF
#!/bin/sh
# Лаунчер приложения DevOps-мониторинга (устанавливается пакетом ${APP_BINARY}).
exec /usr/bin/env python3 /opt/${APP_BINARY}/main.py "\$@"
EOF
chmod 0755 "${DEB_STAGE}/usr/local/bin/${APP_BINARY}"

cat > "${DEB_STAGE}/etc/systemd/system/${APP_BINARY}.service" << EOF
[Unit]
Description=DevOps monitoring application (/health, /metrics)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/${APP_BINARY}
Restart=always
RestartSec=5
User=${APP_BINARY}
Group=${APP_BINARY}
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "${DEB_STAGE}/etc/systemd/system/${APP_BINARY}.service"

cat > "${DEB_STAGE}/DEBIAN/control" << EOF
Package: ${APP_BINARY}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Maintainer: DevOps Team <devops@example.com>
Depends: python3 (>= 3.8)
Description: DevOps monitoring application with /health and /metrics endpoints
 Standalone Python application from the first-devops-project repository.
 It serves a health check endpoint, a Prometheus exposition endpoint and a
 simple status page. The package installs a systemd unit that runs the
 application as the unprivileged ${APP_BINARY} user.
EOF
chmod 0644 "${DEB_STAGE}/DEBIAN/control"

cat > "${DEB_STAGE}/DEBIAN/postinst" << EOF
#!/bin/sh
set -e
if ! getent group ${APP_BINARY} > /dev/null 2>&1; then
    groupadd --system ${APP_BINARY} || true
fi
if ! getent passwd ${APP_BINARY} > /dev/null 2>&1; then
    useradd --system --gid ${APP_BINARY} --home-dir /opt/${APP_BINARY} \
        --shell /usr/sbin/nologin ${APP_BINARY} || true
fi
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
fi
exit 0
EOF
chmod 0755 "${DEB_STAGE}/DEBIAN/postinst"

echo "==> Формирование контрольных сумм пакета"
( cd "$DEB_STAGE" && find . -type f -not -path './DEBIAN/*' | sort | xargs -r md5sum > DEBIAN/md5sums )

echo "==> Сборка пакета ${DEB}"
dpkg-deb --root-owner-group --build "$DEB_STAGE" "$DEB"

echo ""
echo "==> Готово:"
ls -lh "$ARCHIVE" "$PYZ" "$DEB"
echo ""
echo "==> Содержимое архива ${ARCHIVE}:"
tar -tzf "$ARCHIVE"
echo ""
echo "==> Содержимое пакета ${DEB}:"
dpkg-deb --contents "$DEB"
