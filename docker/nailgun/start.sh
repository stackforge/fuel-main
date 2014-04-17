#!/bin/bash
#Run puppet to apply custom config
puppet apply -v /etc/puppet/modules/nailgun/examples/nailgun-only.pp

#Set up nailgun DB
/usr/bin/nailgun_syncdb
/usr/bin/nailgun_fixtures
/usr/bin/supervisord -n
