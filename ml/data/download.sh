#!/usr/bin/env bash
# Downloads the public datasets used by the ML modules into ml/data/raw/ (git-ignored).
# Sources are pinned to exact commits so results are reproducible. See ml/data/README.md.
#
#   bash ml/data/download.sh          # ~450 MB download
#
# Manual alternative (no network on the build machine): download the same URLs in a browser
# and place the files at the paths shown below, then run `make data-check`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAW="$ROOT/raw"
MSR_COMMIT="f5084232f88b1b92d60c8492be5f0737fac320f7"   # ansymo/msr2013-bug_dataset (2015-04-12)
BUGREPO_COMMIT="76d33067f91813690e01ae37b4790e631c5081f4" # logpai/bugrepo (2018-07-12)
MSR="https://raw.githubusercontent.com/ansymo/msr2013-bug_dataset/$MSR_COMMIT/data/v02"
BUGREPO="https://raw.githubusercontent.com/logpai/bugrepo/$BUGREPO_COMMIT"

fetch() {  # fetch <url> <relative target path>
  local url="$1" target="$RAW/$2"
  if [[ -s "$target" ]]; then echo "  have  $2"; return; fi
  mkdir -p "$(dirname "$target")"
  echo "  get   $2"
  curl -fL --retry 3 --silent --show-error -o "$target.part" "$url"
  mv "$target.part" "$target"
}

echo "Lamkanfi et al. (MSR 2013): severity / assignee / component histories"
for project in eclipse mozilla; do
  for attribute in reports severity assigned_to component product; do
    fetch "$MSR/$project/$attribute.json" "msr2013/$project/$attribute.json"
  done
done

echo "logpai/bugrepo: report text and duplicate links"
fetch "$BUGREPO/EclipsePlatform/eclipse_platform.zip" "bugrepo/eclipse_platform.zip"
fetch "$BUGREPO/EclipsePlatform/test.csv"             "bugrepo/eclipse_platform_test.csv"
fetch "$BUGREPO/JDT/eclipse_jdt.csv"                  "bugrepo/eclipse_jdt.csv"
fetch "$BUGREPO/Firefox/mozilla_firefox.zip"          "bugrepo/mozilla_firefox.zip"
fetch "$BUGREPO/MozillaCore/mozilla_core.zip"         "bugrepo/mozilla_core.zip"
fetch "$BUGREPO/Thunderbird/mozilla_thunderbird.csv"  "bugrepo/mozilla_thunderbird.csv"

echo "Unpacking"
for archive in "$RAW"/bugrepo/*.zip; do
  unzip -o -q -d "$RAW/bugrepo/unzipped" "$archive"
done

echo "Recording checksums -> ml/data/raw/SHA256SUMS"
(cd "$RAW" && find msr2013 bugrepo -type f ! -name '*.part' | sort | xargs shasum -a 256) > "$RAW/SHA256SUMS"
echo "Done."
