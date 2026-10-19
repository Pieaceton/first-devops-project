#!/usr/bin/env bash
#
# Сборка релизного пакета приложения.
#
# Создает dist/app-release.tar.gz, содержащий:
#   * main.py        - исходный код приложения
#   * BUILD_INFO.txt - метаданные сборки (коммит, версия, дата)
#   * __pycache__/   - скомпилированный байткод Python
#
# Использование:
#   ./build.sh            - сборка с автоматическим определением коммита
#   VERSION=1.2.3 ./build.sh - сборка с заданной версией
#
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

APP_NAME="app-release"
DIST_DIR="dist"
STAGE_DIR="${DIST_DIR}/${APP_NAME}"
ARCHIVE="${DIST_DIR}/${APP_NAME}.tar.gz"

VERSION="${VERSION:-1.0.0}"

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
rm -rf "$STAGE_DIR" "$ARCHIVE"
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

echo ""
echo "==> Готово:"
ls -lh "$ARCHIVE"
echo ""
echo "==> Содержимое архива:"
tar -tzf "$ARCHIVE"
