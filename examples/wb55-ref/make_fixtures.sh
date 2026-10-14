#!/usr/bin/env bash
# Regenerate ci-out/ from real tool runs: gcc --coverage, pytest, gcovr, flawfinder.
# Requires gcc and uv. ci-out/junit-hil.xml is NOT generated here — see README.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf build
mkdir -p build ci-out
rm -f ci-out/junit-module.xml ci-out/coverage.lcov ci-out/coverage.xml ci-out/flawfinder.sarif

for f in supervisor frame_auth; do
	gcc --coverage -O0 -fPIC -c "src/$f.c" -o "build/$f.o"
done
gcc --coverage -shared -o build/libwb55.so build/supervisor.o build/frame_auth.o

WB55_LIB="$PWD/build/libwb55.so" uvx --quiet pytest -q -p no:cacheprovider --junitxml=ci-out/junit-module.xml
uvx --quiet gcovr --root . --lcov ci-out/coverage.lcov --cobertura ci-out/coverage.xml build
uvx --quiet flawfinder --quiet --sarif src > ci-out/flawfinder.sarif || true   # exits non-zero on hits

# Tools embed this checkout's absolute path. Rewrite it to a neutral CI-style root so the fixtures carry no
# local paths and still exercise path resolution for artifacts produced in a different checkout.
sed -i "s#$PWD#/builds/wb55-ref#g" ci-out/junit-module.xml ci-out/coverage.lcov ci-out/coverage.xml ci-out/flawfinder.sarif
sed -i 's/hostname="[^"]*"/hostname="ci-runner"/' ci-out/junit-module.xml
echo "fixtures regenerated in ci-out/"
