#!/usr/bin/env bash
# Construye el paquete .deb de Grabador OpenArgentOS
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/grabador_openargentos.py"
TEMPLATE="$ROOT/packaging/deb"
OUT_DIR="$ROOT/dist"
BUILD_ROOT="$(mktemp -d /tmp/grabador-deb-XXXXXX)"
VERSION="$(grep -m1 '^Version:' "$TEMPLATE/DEBIAN/control" | awk '{print $2}')"
PKG_NAME="grabador-openargentos_${VERSION}_all.deb"

cleanup() { rm -rf "$BUILD_ROOT"; }
trap cleanup EXIT

if [[ ! -f "$SRC" ]]; then
  echo "No se encuentra $SRC" >&2
  exit 1
fi

echo "==> Preparando árbol del paquete en $BUILD_ROOT ..."
mkdir -p "$BUILD_ROOT"
cp -a "$TEMPLATE/." "$BUILD_ROOT/"

install -d "$BUILD_ROOT/usr/share/grabador-openargentos"
install -m 0644 "$SRC" "$BUILD_ROOT/usr/share/grabador-openargentos/grabador_openargentos.py"
install -d "$BUILD_ROOT/usr/bin"
cat > "$BUILD_ROOT/usr/bin/grabador-openargentos" << 'EOF'
#!/bin/bash
exec python3 /usr/share/grabador-openargentos/grabador_openargentos.py "$@"
EOF
chmod 0755 "$BUILD_ROOT/usr/bin/grabador-openargentos"
chmod 0755 "$BUILD_ROOT/DEBIAN"
chmod 0644 "$BUILD_ROOT/DEBIAN/control"

install -d "$OUT_DIR"
echo "==> Construyendo $PKG_NAME ..."
dpkg-deb --build --root-owner-group "$BUILD_ROOT" "$OUT_DIR/$PKG_NAME"
echo "==> Listo: $OUT_DIR/$PKG_NAME"
dpkg-deb -I "$OUT_DIR/$PKG_NAME"
