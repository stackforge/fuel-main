#!/bin/bash

source /etc/fuel/functions.sh
set -o errexit
trap 'print_debug_info' ERR
set -o xtrace

rm -rf /etc/yum.repos.d/*

cat << EOF > /etc/yum.repos.d/nailgun.repo
[nailgun]
name=Nailgun Local Repo
baseurl=http://$(route -n | awk '/^0.0.0.0/ {print $2}'):${DOCKER_PORT}/os/x86_64/
gpgcheck=0
EOF

yum clean expire-cache
yum update -y

yum install -y --quiet sudo mcollective shotgun fuel-agent fuel-provisioning-scripts

# /var/lib/fuel/ibp is a mount point for IBP host volume
mkdir -p /var/lib/hiera /var/lib/fuel/ibp
touch /etc/puppet/hiera.yaml /var/lib/hiera/common.yaml

systemctl daemon-reload
puppet apply --color false --detailed-exitcodes --debug --verbose \
  /etc/puppet/modules/mcollective/examples/mcollective-server-only.pp || [[ $? == 2 ]]

puppet apply --color false --detailed-exitcodes --debug --verbose \
  /etc/puppet/modules/nailgun/examples/dhcp-ranges.pp || [[ $? == 2 ]]

#FIXME(mattymo): Workaround to make diagnostic snapshots work
mkdir -p /opt/nailgun/bin /var/www/nailgun/dump
ln -s /usr/bin/nailgun_dump /opt/nailgun/bin/nailgun_dump

cat << EOF > /etc/yum.repos.d/nailgun.repo
[nailgun]
name=Nailgun Local Repo
baseurl=file:/var/www/nailgun/centos/x86_64
gpgcheck=0
EOF

yum clean all

systemctl enable start-container.service
