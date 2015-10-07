#!/bin/bash

rm -rf /etc/yum.repos.d/*

cat << EOF > /etc/yum.repos.d/nailgun.repo
[nailgun]
name=Nailgun Local Repo
baseurl=http://$(route -n | awk '/^0.0.0.0/ {print $2}'):${DOCKER_PORT}/os/x86_64/
gpgcheck=0
EOF

yum clean expire-cache
yum update -y

touch /etc/puppet/hiera.yaml
/usr/bin/puppet apply --color false --detailed-exitcodes --debug --verbose \
  /etc/puppet/modules/nailgun/examples/rsyslog-only.pp || [[ $? == 2 ]]

mkdir -p /etc/systemd/system/rsyslogd.service.d/
cat << EOF > /etc/systemd/system/rsyslogd.service.d/restart.conf
[Service]
Restart=always
RestartSec=5
FailureAction=reboot-force
EOF

systemctl set-default multi-user.target
systemctl enable rsyslogd.service

cat << EOF > /etc/yum.repos.d/nailgun.repo
[nailgun]
name=Nailgun Local Repo
baseurl=file:/var/www/nailgun/centos/x86_64
gpgcheck=0
EOF

yum clean all