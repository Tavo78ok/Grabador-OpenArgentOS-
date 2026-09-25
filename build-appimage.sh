#!/usr/bin/env bash
# Construye un AppImage portable del Grabador OpenArgentOS.
# Requiere: appimagetool (se descarga si no está), python3, ffmpeg en el host
# para empaquetar dependencias mínimas de runtime del script.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/grabador_openargentos.py"
APPDIR="$ROOT/packaging/appimage/GrabadorOpenArgentOS.AppDir"
OUT_DIR="$ROOT/dist"
VERSION="1.1.0"
ARCH="$(uname -m)"

if [[ ! -f "$SRC" ]]; then
  echo "No se encuentra $SRC" >&2
  exit 1
fi

echo "==> Limpiando AppDir..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" \
         "$APPDIR/usr/share/grabador-openargentos" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps"

install -m 0644 "$SRC" "$APPDIR/usr/share/grabador-openargentos/grabador_openargentos.py"

cat > "$APPDIR/usr/bin/grabador-openargentos" << 'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
export PATH="$HERE:$PATH"
# Usa el Python del sistema (GTK/Adw/ffmpeg deben estar en el host)
exec python3 "$HERE/../share/grabador-openargentos/grabador_openargentos.py" "$@"
EOF
chmod 0755 "$APPDIR/usr/bin/grabador-openargentos"

install -m 0644 \
  "$ROOT/packaging/deb/usr/share/applications/org.openargentos.recorder.desktop" \
  "$APPDIR/usr/share/applications/org.openargentos.recorder.desktop"

install -m 0644 \
  "$ROOT/packaging/deb/usr/share/icons/hicolor/scalable/apps/org.openargentos.recorder.svg" \
  "$APPDIR/usr/share/icons/hicolor/scalable/apps/org.openargentos.recorder.svg"

# Entrypoints que exige AppImage (copias; algunos entornos no permiten symlinks)
cp -f "$APPDIR/usr/share/applications/org.openargentos.recorder.desktop" \
      "$APPDIR/grabador-openargentos.desktop"
cp -f "$APPDIR/usr/share/icons/hicolor/scalable/apps/org.openargentos.recorder.svg" \
      "$APPDIR/org.openargentos.recorder.svg"
cp -f "$APPDIR/usr/bin/grabador-openargentos" "$APPDIR/AppRun"
chmod 0755 "$APPDIR/AppRun"

sed -i 's|^Exec=.*|Exec=grabador-openargentos|' "$APPDIR/grabador-openargentos.desktop"
sed -i 's|^Icon=.*|Icon=org.openargentos.recorder|' "$APPDIR/grabador-openargentos.desktop"

mkdir -p "$OUT_DIR"

APPIMAGETOOL="$(command -v appimagetool || true)"
if [[ -z "$APPIMAGETOOL" ]]; then
  echo "==> Descargando appimagetool..."
  TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  APPIMAGETOOL="$ROOT/packaging/appimage/appimagetool-${ARCH}.AppImage"
  if [[ ! -x "$APPIMAGETOOL" ]]; then
    curl -L --fail -o "$APPIMAGETOOL" "$TOOL_URL"
    chmod +x "$APPIMAGETOOL"
  fi
fi

OUT_APPIMAGE="$OUT_DIR/Grabador_OpenArgentOS-${VERSION}-${ARCH}.AppImage"
OUT_TAR="$OUT_DIR/Grabador_OpenArgentOS-${VERSION}-${ARCH}-AppDir.tar.gz"

echo "==> Empaquetando AppDir portable: $OUT_TAR"
tar -C "$(dirname "$APPDIR")" -czf "$OUT_TAR" "$(basename "$APPDIR")"
echo "==> Listo: $OUT_TAR"

echo "==> Intentando AppImage con appimagetool..."
export ARCH
set +e
if [[ -x "$APPIMAGETOOL" ]]; then
  if "$APPIMAGETOOL" "$APPDIR" "$OUT_APPIMAGE"; then
    echo "==> Listo: $OUT_APPIMAGE"
  elif APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" "$APPDIR" "$OUT_APPIMAGE"; then
    echo "==> Listo: $OUT_APPIMAGE"
  else
    echo "!! No se pudo ejecutar appimagetool en este entorno (FUSE/permisos)."
    echo "   Usá el tarball AppDir o construí el AppImage en tu máquina:"
    echo "   appimagetool $APPDIR $OUT_APPIMAGE"
  fi
else
  echo "!! appimagetool no disponible."
fi
set -e

echo "Nota: el launcher usa el Python del sistema (python3 + gi + Adw + ffmpeg)."
