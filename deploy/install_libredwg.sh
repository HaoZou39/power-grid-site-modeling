#!/bin/sh
set -eu

apt-get update
apt-get install -y --no-install-recommends build-essential curl ca-certificates xz-utils
curl -fL https://github.com/LibreDWG/libredwg/releases/download/0.14/libredwg-0.14.tar.xz -o /tmp/libredwg.tar.xz
echo '62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275 /tmp/libredwg.tar.xz' | sha256sum -c -
tar -xf /tmp/libredwg.tar.xz -C /tmp
cd /tmp/libredwg-0.14
./configure --disable-shared --disable-bindings
make -j2
install -m755 programs/dwg2dxf /usr/local/bin/dwg2dxf
