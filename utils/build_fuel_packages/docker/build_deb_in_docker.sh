#!/bin/bash

# This script runs inside docker env, please check build_deb.sh file
# for required input data

set -ex

mkdir -p /tmp/package

# since we have specs in repo we can prepare for build faster
# just unpack prepared sources
tar -xzf /opt/sandbox/SOURCES/*gz -C /tmp/package

sudo apt-get update
sudo apt-get upgrade -f -y --force-yes

DEBFULLNAME=$(awk -F '=' '/DEBFULLNAME/ {print $2}' /opt/sandbox/SOURCES/version) \
DEBEMAIL=$(awk -F '=' '/DEBEMAIL/ {print $2}' /opt/sandbox/SOURCES/version) \
sudo -E dch -c /tmp/package/debian/changelog -D trusty -b --force-distribution \
-v "$(awk -F '=' '/VERSION/ {print $2}' /opt/sandbox/SOURCES/version)-$(awk -F '=' '/RELEASE/ {print $2}' /opt/sandbox/SOURCES/version)" \
"$(awk -F '=' '/DEBMSG/ {print $2}' /opt/sandbox/SOURCES/version)"

dpkg-checkbuilddeps /tmp/package/debian/control 2>&1 | \
  sed 's/^dpkg-checkbuilddeps: Unmet build dependencies: //g' | \
  sed 's/([^()]*)//g;s/|//g' | tee /tmp/package.installdeps

cat /tmp/package.installdeps | xargs --no-run-if-empty sudo DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true apt-get -y install
cd /tmp/package ; DEB_BUILD_OPTIONS=nocheck debuild -us -uc -b -d
cp -v /tmp/*.deb /opt/sandbox/DEB