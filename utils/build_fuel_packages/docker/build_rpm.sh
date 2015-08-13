#!/bin/bash

# This is an example how can we use docker rpmbuild_env to build RPM packages
# in Fuel project, sources can be prepared by "make sources" target from fuel-main

set -ex

PACKAGES_TO_BUILD="astute fuel-library7.0 fuel-main fuel-ostf nailgun python-fuelclient fuel-agent"
SOURCE_PATH=${HOME}/fuel-main/build/packages/sources
SPEC_FILE_PATH=${HOME}/fuel-main/build/repos
RESULT_DIR=/tmp/packages

rm -rf ${RESULT_DIR}
mkdir -p ${RESULT_DIR}

for pckgs in ${PACKAGES_TO_BUILD}; do
docker run --privileged --rm -v ${SOURCE_PATH}/${pckgs}:/opt/sandbox/SOURCES \
           -v ${SPEC_FILE_PATH}/${pckgs}/specs/${pckgs}.spec:/opt/sandbox/${pckgs}.spec \
           -v ${RESULT_DIR}:/opt/sandbox/RPMS \
           -u ${UID} \
           fuel-7.0/rpmbuild_env /bin/bash /opt/sandbox/build_rpm_in_docker.sh
done