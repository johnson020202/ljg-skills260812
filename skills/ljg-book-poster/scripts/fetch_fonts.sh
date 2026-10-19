#!/bin/bash
# Fetch the default open-source font library into assets/fonts/.
# Each file is verified against a pinned SHA-256 before being accepted.
# All fonts are freely embeddable/redistributable:
#   LXGW WenKai (R/M)      SIL OFL 1.1   https://github.com/lxgw/LxgwWenKai
#   Smiley Sans Oblique    SIL OFL 1.1   https://github.com/atelier-anchor/smiley-sans
#   Huiwen Mincho          CC0-1.0       https://github.com/bosswnx/huiwenmincho-improved
#   LXGW Neo XiHei         IPA Font License  https://github.com/lxgw/LxgwNeoXiHei
#   LXGW Marker Gothic     SIL OFL 1.1   https://github.com/lxgw/LxgwMarkerGothic
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="assets/fonts"
mkdir -p "$OUT"

fetch() {
  local name="$1" url="$2" sha="$3"
  if [ -f "$OUT/$name" ] && shasum -a 256 -c <<<"$sha  $OUT/$name" >/dev/null 2>&1; then
    echo "OK    $name (already present, checksum verified)"
    return
  fi
  echo "FETCH $name"
  local tmp
  tmp=$(mktemp)
  curl -fL --retry 3 -o "$tmp" "$url"
  if ! shasum -a 256 -c <<<"$sha  $tmp" >/dev/null 2>&1; then
    echo "ERROR: checksum mismatch for $name (upstream may have changed; pin a release tag URL)" >&2
    rm -f "$tmp"
    exit 1
  fi
  mv "$tmp" "$OUT/$name"
  echo "OK    $name"
}

fetch LXGWWenKai-Regular.ttf \
  "https://github.com/lxgw/LxgwWenKai/releases/download/v1.530/LXGWWenKai-Regular.ttf" \
  "2d73eea94ad808999d90c0000c239a84a33b09d4bc6ab6c5b8bbf1eda8a7fc8b"
fetch LXGWWenKai-Medium.ttf \
  "https://github.com/lxgw/LxgwWenKai/releases/download/v1.530/LXGWWenKai-Medium.ttf" \
  "f4b8a34d1f838fe411540cb7c97b1c384ac9738a876c4104500bc42508b2312a"
fetch LXGWNeoXiHei.ttf \
  "https://github.com/lxgw/LxgwNeoXiHei/releases/download/v1.305/LXGWNeoXiHei.ttf" \
  "893cfbec604768f03785ab4f369508de68c274273359a5cadee17e2852975d5c"

# LXGW Marker Gothic ships as a zip; extract the TTF from it.
if [ ! -f "$OUT/LXGWMarkerGothic-Regular.ttf" ]; then
  echo "FETCH LXGWMarkerGothic-Regular.ttf (from release zip)"
  tmpzip=$(mktemp)
  curl -fL --retry 3 -o "$tmpzip" \
    "https://github.com/lxgw/LxgwMarkerGothic/releases/download/v1.004/LxgwMarkerGothic-v1.004.zip"
  python3 - "$tmpzip" "$OUT/LXGWMarkerGothic-Regular.ttf" <<'PY'
import sys, zipfile, hashlib
want_sha = "dfc9b27ef9e83024d5926d4a1feb70604eaf8c16aa73659c81d75a22accadae4"
with zipfile.ZipFile(sys.argv[1]) as archive:
    data = archive.read("LxgwMarkerGothic-v1.004/fonts/ttf/LXGWMarkerGothic-Regular.ttf")
assert hashlib.sha256(data).hexdigest() == want_sha, "marker gothic checksum mismatch"
open(sys.argv[2], "wb").write(data)
PY
  rm -f "$tmpzip"
  echo "OK    LXGWMarkerGothic-Regular.ttf"
else
  echo "OK    LXGWMarkerGothic-Regular.ttf (already present)"
fi
fetch huiwen-mincho.ttf \
  "https://raw.githubusercontent.com/bosswnx/huiwenmincho-improved/40b9dbb9bfa51bc4979b62d0dcd3bc064c5ea049/%E5%8C%AF%E6%96%87%E6%98%8E%E6%9C%9D%E9%AB%94.ttf" \
  "90bb5b835fd5841a46fa8fca4fe1c82aeb4b9c02be15eadc3effc60dad4fef58"

# Smiley Sans ships as a zip; extract the oblique OTF from it.
if [ ! -f "$OUT/SmileySans-Oblique.otf" ]; then
  echo "FETCH SmileySans-Oblique.otf (from release zip)"
  tmpzip=$(mktemp)
  curl -fL --retry 3 -o "$tmpzip" \
    "https://github.com/atelier-anchor/smiley-sans/releases/download/v2.0.1/smiley-sans-v2.0.1.zip"
  python3 - "$tmpzip" "$OUT/SmileySans-Oblique.otf" <<'PY'
import sys, zipfile, hashlib
want_sha = "139b5dcbe70d6d52de85a62d148784c6af4bd161e38fdb62ba0c1e7e5065fca6"
with zipfile.ZipFile(sys.argv[1]) as archive:
    data = archive.read("SmileySans-Oblique.otf")
assert hashlib.sha256(data).hexdigest() == want_sha, "smiley-sans checksum mismatch"
open(sys.argv[2], "wb").write(data)
PY
  rm -f "$tmpzip"
  echo "OK    SmileySans-Oblique.otf"
else
  echo "OK    SmileySans-Oblique.otf (already present)"
fi

cp -f "$(dirname "$0")/../assets/LICENSE-CC0.txt" "$OUT/LICENSE-CC0-huiwen-mincho.txt" 2>/dev/null || true
echo "Font library ready in $OUT"
