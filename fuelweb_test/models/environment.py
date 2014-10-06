#    Copyright 2013 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import time
import yaml

from devops.helpers.helpers import _get_file_size
from devops.helpers.helpers import _wait
from devops.helpers.helpers import SSHClient
from devops.helpers.helpers import wait
from devops.manager import Manager
from ipaddr import IPNetwork
from paramiko import RSAKey
from proboscis.asserts import assert_equal
from proboscis.asserts import assert_true

from fuelweb_test.helpers import checkers
from fuelweb_test.helpers.decorators import revert_info
from fuelweb_test.helpers.decorators import retry
from fuelweb_test.helpers.eb_tables import Ebtables
from fuelweb_test.models.fuel_web_client import FuelWebClient
from fuelweb_test import settings
from fuelweb_test import logwrap
from fuelweb_test import logger


class EnvironmentModel(object):
    hostname = 'nailgun'
    domain = 'test.domain.local'
    installation_timeout = 1800
    deployment_timeout = 1800
    puppet_timeout = 2000
    nat_interface = ''  # INTERFACES.get('admin')
    admin_net = 'admin'
    admin_net2 = 'admin2'
    multiple_cluster_networks = settings.MULTIPLE_NETWORKS

    def __init__(self, os_image=None):
        self._virtual_environment = None
        self._keys = None
        self.manager = Manager()
        self.os_image = os_image
        self._fuel_web = FuelWebClient(self.get_admin_node_ip(), self)

    def _get_or_create(self):
        try:
            return self.manager.environment_get(self.env_name)
        except Exception:
            self._virtual_environment = self.describe_environment()
            self._virtual_environment.define()
            return self._virtual_environment

    def router(self, router_name=None):
        router_name = router_name or self.admin_net
        if router_name == self.admin_net2:
            return str(IPNetwork(self.get_virtual_environment().
                                 network_by_name(router_name).ip_network)[2])
        return str(
            IPNetwork(
                self.get_virtual_environment().network_by_name(router_name).
                ip_network)[1])

    @property
    def fuel_web(self):
        """FuelWebClient
        :rtype: FuelWebClient
        """
        return self._fuel_web

    @property
    def node_roles(self):
        return NodeRoles(
            admin_names=['admin'],
            other_names=['slave-%02d' % x for x in range(1, int(
                settings.NODES_COUNT))]
        )

    @property
    def env_name(self):
        return settings.ENV_NAME

    def add_empty_volume(self, node, name,
                         capacity=settings.NODE_VOLUME_SIZE * 1024 * 1024
                         * 1024, device='disk', bus='virtio', format='qcow2'):
        self.manager.node_attach_volume(
            node=node,
            volume=self.manager.volume_create(
                name=name,
                capacity=capacity,
                environment=self.get_virtual_environment(),
                format=format),
            device=device,
            bus=bus)

    def add_node(self, memory, name, vcpu=1, boot=None):
        return self.manager.node_create(
            name=name,
            memory=memory,
            vcpu=vcpu,
            environment=self.get_virtual_environment(),
            boot=boot)

    @logwrap
    def add_syslog_server(self, cluster_id, port=5514):
        self.fuel_web.add_syslog_server(
            cluster_id, self.get_host_node_ip(), port)

    def bootstrap_nodes(self, devops_nodes, timeout=600):
        """Lists registered nailgun nodes
        Start vms and wait until they are registered on nailgun.
        :rtype : List of registered nailgun nodes
        """
        #self.dhcrelay_check()

        for node in devops_nodes:
            node.start()
            #TODO(aglarendil): LP#1317213 temporary sleep
            #remove after better fix is applied
            time.sleep(2)
        wait(lambda: all(self.nailgun_nodes(devops_nodes)), 15, timeout)

        for node in self.nailgun_nodes(devops_nodes):
            self.sync_node_time(self.get_ssh_to_remote(node["ip"]))

        return self.nailgun_nodes(devops_nodes)

    def create_interfaces(self, networks, node,
                          model=settings.INTERFACE_MODEL):
        if settings.BONDING:
            for network in networks:
                self.manager.interface_create(
                    network, node=node, model=model,
                    interface_map=settings.BONDING_INTERFACES)
        else:
            for network in networks:
                self.manager.interface_create(network, node=node, model=model)

    def describe_environment(self):
        """Environment
        :rtype : Environment
        """
        environment = self.manager.environment_create(self.env_name)
        networks = []
        interfaces = settings.INTERFACE_ORDER
        if self.multiple_cluster_networks:
            logger.info('Multiple cluster networks feature is enabled!')
        if settings.BONDING:
            interfaces = settings.BONDING_INTERFACES.keys()

        for name in interfaces:
            networks.append(self.create_networks(name, environment))
        for name in self.node_roles.admin_names:
            self.describe_admin_node(name, networks)
        for name in self.node_roles.other_names:
            if self.multiple_cluster_networks:
                networks1 = [net for net in networks if net.name
                             in settings.NODEGROUPS[0]['pools']]
                networks2 = [net for net in networks if net.name
                             in settings.NODEGROUPS[1]['pools']]
                # If slave index is even number, then attach to
                # it virtual networks from the second network group.
                if int(name[-2:]) % 2 == 1:
                    self.describe_empty_node(name, networks1)
                elif int(name[-2:]) % 2 == 0:
                    self.describe_empty_node(name, networks2)
            else:
                self.describe_empty_node(name, networks)
        return environment

    def create_networks(self, name, environment):
        ip_networks = [
            IPNetwork(x) for x in settings.POOLS.get(name)[0].split(',')]
        new_prefix = int(settings.POOLS.get(name)[1])
        pool = self.manager.create_network_pool(networks=ip_networks,
                                                prefix=int(new_prefix))
        return self.manager.network_create(
            name=name,
            environment=environment,
            pool=pool,
            forward=settings.FORWARDING.get(name),
            has_dhcp_server=settings.DHCP.get(name))

    def devops_nodes_by_names(self, devops_node_names):
        return map(
            lambda name:
            self.get_virtual_environment().node_by_name(name),
            devops_node_names)

    @logwrap
    def describe_admin_node(self, name, networks):
        node = self.add_node(
            memory=settings.HARDWARE.get("admin_node_memory", 1024),
            vcpu=settings.HARDWARE.get("admin_node_cpu", 1),
            name=name,
            boot=['hd', 'cdrom'])
        self.create_interfaces(networks, node)

        if self.os_image is None:
            self.add_empty_volume(node, name + '-system')
            self.add_empty_volume(
                node,
                name + '-iso',
                capacity=_get_file_size(settings.ISO_PATH),
                format='raw',
                device='cdrom',
                bus='ide')
        else:
            volume = self.manager.volume_get_predefined(self.os_image)
            vol_child = self.manager.volume_create_child(
                name=name + '-system',
                backing_store=volume,
                environment=self.get_virtual_environment()
            )
            self.manager.node_attach_volume(
                node=node,
                volume=vol_child
            )
        return node

    def describe_empty_node(self, name, networks):
        node = self.add_node(
            name=name,
            memory=settings.HARDWARE.get("slave_node_memory", 1024),
            vcpu=settings.HARDWARE.get("slave_node_cpu", 1))
        self.create_interfaces(networks, node)
        self.add_empty_volume(node, name + '-system')

        if settings.USE_ALL_DISKS:
            self.add_empty_volume(node, name + '-cinder')
            self.add_empty_volume(node, name + '-swift')

        return node

    @logwrap
    def get_admin_remote(self):
        """SSH to admin node
        :rtype : SSHClient
        """
        return self.nodes().admin.remote(self.admin_net,
                                         login='root',
                                         password='r00tme')

    @logwrap
    def get_admin_node_ip(self):
        return str(
            self.nodes().admin.get_ip_address_by_network_name(self.admin_net))

    @logwrap
    def get_ebtables(self, cluster_id, devops_nodes):
        return Ebtables(self.get_target_devs(devops_nodes),
                        self.fuel_web.client.get_cluster_vlans(cluster_id))

    def get_host_node_ip(self):
        return self.router()

    def get_keys(self, node):
        params = {
            'ip': node.get_ip_address_by_network_name(self.admin_net),
            'mask': self.get_net_mask(self.admin_net),
            'gw': self.router(),
            'hostname': '.'.join((self.hostname, self.domain)),
            'nat_interface': self.nat_interface,
            'dns1': settings.DNS

        }
        keys = (
            "<Wait>\n"
            "<Esc><Enter>\n"
            "<Wait>\n"
            "vmlinuz initrd=initrd.img ks=cdrom:/ks.cfg\n"
            " ip=%(ip)s\n"
            " netmask=%(mask)s\n"
            " gw=%(gw)s\n"
            " dns1=%(dns1)s\n"
            " hostname=%(hostname)s\n"
            " dhcp_interface=%(nat_interface)s\n"
            " <Enter>\n"
        ) % params
        return keys

    @logwrap
    def get_private_keys(self, force=False):
        if force or self._keys is None:
            self._keys = []
            for key_string in ['/root/.ssh/id_rsa',
                               '/root/.ssh/bootstrap.rsa']:
                with self.get_admin_remote().open(key_string) as f:
                    self._keys.append(RSAKey.from_private_key(f))
        return self._keys

    @logwrap
    def get_ssh_to_remote(self, ip):
        return SSHClient(ip,
                         username='root',
                         password='r00tme',
                         private_keys=self.get_private_keys())

    @logwrap
    def get_ssh_to_remote_by_name(self, node_name):
        return self.get_ssh_to_remote(
            self.fuel_web.get_nailgun_node_by_devops_node(
                self.get_virtual_environment().node_by_name(node_name))['ip']
        )

    def get_target_devs(self, devops_nodes):
        return [
            interface.target_dev for interface in [
                val for var in map(lambda node: node.interfaces, devops_nodes)
                for val in var]]

    def get_virtual_environment(self):
        """Returns virtual environment
        :rtype : devops.models.Environment
        """
        if self._virtual_environment is None:
            self._virtual_environment = self._get_or_create()
        return self._virtual_environment

    def get_network(self, net_name):
        return str(
            IPNetwork(
                self.get_virtual_environment().network_by_name(net_name).
                ip_network))

    def get_net_mask(self, net_name):
        return str(
            IPNetwork(
                self.get_virtual_environment().network_by_name(
                    net_name).ip_network).netmask)

    def make_snapshot(self, snapshot_name, description="", is_make=False):
        if settings.MAKE_SNAPSHOT or is_make:
            self.get_virtual_environment().suspend(verbose=False)
            self.get_virtual_environment().snapshot(snapshot_name, force=True)
            revert_info(snapshot_name, description)

    def nailgun_nodes(self, devops_nodes):
        return map(
            lambda node: self.fuel_web.get_nailgun_node_by_devops_node(node),
            devops_nodes
        )

    def nodes(self):
        return Nodes(self.get_virtual_environment(), self.node_roles)

    def revert_snapshot(self, name):
        if self.get_virtual_environment().has_snapshot(name):
            logger.info('We have snapshot with such name %s' % name)

            self.get_virtual_environment().revert(name)
            logger.info('Starting snapshot reverting ....')

            self.get_virtual_environment().resume()
            logger.info('Starting snapshot resuming ...')

            admin = self.nodes().admin

            try:
                admin.await(
                    self.admin_net, timeout=10 * 60, by_port=8000)
            except Exception as e:
                logger.warning("From first time admin isn't reverted: "
                               "{0}".format(e))
                admin.destroy()
                logger.info('Admin node was destroyed. Wait 10 sec.')
                time.sleep(10)
                self.get_virtual_environment().start(self.nodes().admins)
                logger.info('Admin node started second time.')
                self.nodes().admin.await(
                    self.admin_net, timeout=10 * 60, by_port=8000)
                _wait(self._fuel_web.get_nailgun_version, timeout=120)

            self.sync_time_admin_node()

            for node in self.nodes().slaves:
                if not node.driver.node_active(node):
                    continue
                try:
                    logger.info("Sync time on revert for node %s" % node.name)
                    self.sync_node_time(
                        self.get_ssh_to_remote_by_name(node.name))
                except Exception as e:
                    logger.warning(
                        'Exception caught while trying to sync time on {0}:'
                        ' {1}'.format(node.name, e))
                self.run_nailgun_agent(
                    self.get_ssh_to_remote_by_name(node.name))
            return True
        return False

    def setup_environment(self):
        # start admin node
        admin = self.nodes().admin
        admin.disk_devices.get(device='cdrom').volume.upload(settings.ISO_PATH)
        self.get_virtual_environment().start(self.nodes().admins)
        logger.info("Waiting for admin node to start up")
        wait(lambda: admin.driver.node_active(admin), 60)
        logger.info("Proceed with installation")
        # update network parameters at boot screen
        admin.send_keys(self.get_keys(admin))
        # wait while installation complete
        admin.await(self.admin_net, timeout=10 * 60)
        self.wait_bootstrap()
        time.sleep(10)
        self.sync_time_admin_node()
        if settings.MULTIPLE_NETWORKS:
            self.describe_second_admin_interface()
            self.configure_second_admin_cobbler()
            self.configure_second_dhcrelay()

    @retry()
    @logwrap
    def sync_node_time(self, remote):
        self.execute_remote_cmd(remote, 'hwclock -s')
        self.execute_remote_cmd(remote, 'NTPD=$(find /etc/init.d/ -regex \''
                                        '/etc/init.d/ntp.?\'); $NTPD stop; '
                                        'killall ntpd; ntpd -qg && '
                                        '$NTPD start')
        self.execute_remote_cmd(remote, 'hwclock -w')
        remote_date = remote.execute('date')['stdout']
        logger.info("Node time: %s" % remote_date)

    @logwrap
    def sync_time_admin_node(self):
        logger.info("Sync time on revert for admin")
        remote = self.get_admin_remote()
        self.execute_remote_cmd(remote, 'hwclock -s')
        # Sync time using ntpd
        try:
            # If public NTP servers aren't accessible ntpdate will fail and
            # ntpd daemon shouldn't be restarted to avoid 'Server has gone
            # too long without sync' error while syncing time from slaves
            self.execute_remote_cmd(remote, "ntpdate -d $(awk '/^server/{print"
                                            " $2}' /etc/ntp.conf)")
        except AssertionError as e:
            logger.warning('Error occurred while synchronizing time on master'
                           ': {0}'.format(e))
        else:
            self.execute_remote_cmd(remote, 'service ntpd stop && ntpd -qg && '
                                            'service ntpd start')
            self.execute_remote_cmd(remote, 'hwclock -w')

        remote_date = remote.execute('date')['stdout']
        logger.info("Master node time: {0}".format(remote_date))

    def verify_node_service_list(self, node_name, smiles_count):
        remote = self.get_ssh_to_remote_by_name(node_name)
        checkers.verify_service_list(remote, smiles_count)

    def verify_network_configuration(self, node_name):
        checkers.verify_network_configuration(
            node=self.fuel_web.get_nailgun_node_by_name(node_name),
            remote=self.get_ssh_to_remote_by_name(node_name)
        )

    def wait_bootstrap(self):
        logger.info("Waiting while bootstrapping is in progress")
        log_path = "/var/log/puppet/bootstrap_admin_node.log"
        logger.info("Puppet timeout set in {0}".format(
            float(settings.PUPPET_TIMEOUT)))
        wait(
            lambda: not
            self.get_admin_remote().execute(
                "grep 'Fuel node deployment complete' '%s'" % log_path
            )['exit_code'],
            timeout=(float(settings.PUPPET_TIMEOUT))
        )

    def dhcrelay_check(self):
        admin_remote = self.get_admin_remote()
        out = admin_remote.execute("dhcpcheck discover "
                                   "--ifaces eth0 "
                                   "--repeat 3 "
                                   "--timeout 10")['stdout']

        assert_true(self.get_admin_node_ip() in "".join(out),
                    "dhcpcheck doesn't discover master ip")

    def run_nailgun_agent(self, remote):
        agent = remote.execute('/opt/nailgun/bin/agent')['exit_code']
        logger.info("Nailgun agent run with exit_code: %s" % agent)

    def get_fuel_settings(self, remote=None):
        if not remote:
            remote = self.get_admin_remote()
        cmd = 'cat {cfg_file}'.format(cfg_file=settings.FUEL_SETTINGS_YAML)
        result = remote.execute(cmd)
        if result['exit_code'] == 0:
            fuel_settings = yaml.load(''.join(result['stdout']))
        else:
            raise Exception('Can\'t output {cfg_file} file: {error}'.
                            format(cfg_file=settings.FUEL_SETTINGS_YAML,
                                   error=result['stderr']))
        return fuel_settings

    def admin_install_pkg(self, pkg_name):
        """Install a package <pkg_name> on the admin node"""
        admin_remote = self.get_admin_remote()
        remote_status = admin_remote.execute("rpm -q {0}'".format(pkg_name))
        if remote_status['exit_code'] == 0:
            logger.info("Package '{0}' already installed.".format(pkg_name))
        else:
            logger.info("Installing package '{0}' ...".format(pkg_name))
            remote_status = admin_remote.execute("yum -y install {0}"
                                                 .format(pkg_name))
            logger.info("Installation of the package '{0}' has been"
                        " completed with exit code {1}"
                        .format(pkg_name, remote_status['exit_code']))
        return remote_status['exit_code']

    def admin_run_service(self, service_name):
        """Start a service <service_name> on the admin node"""
        admin_remote = self.get_admin_remote()
        admin_remote.execute("service {0} start".format(service_name))
        remote_status = admin_remote.execute("service {0} status"
                                             .format(service_name))
        if any('running...' in status for status in remote_status['stdout']):
            logger.info("Service '{0}' is running".format(service_name))
        else:
            logger.info("Service '{0}' failed to start"
                        " with exit code {1} :\n{2}"
                        .format(service_name,
                                remote_status['exit_code'],
                                remote_status['stdout']))

    @logwrap
    def execute_remote_cmd(self, remote, cmd, exit_code=0):
        result = remote.execute(cmd)
        assert_equal(result['exit_code'], exit_code,
                     'Failed to execute "{0}" on remote host: {1}'.
                     format(cmd, result['stderr']))
        return result['stdout']

    @logwrap
    def describe_second_admin_interface(self):
        remote = self.get_admin_remote()
        second_admin_network = self.get_network(self.admin_net2).split('/')[0]
        second_admin_netmask = self.get_net_mask(self.admin_net2)
        second_admin_if = settings.INTERFACES.get(self.admin_net2)
        second_admin_ip = str(self.nodes().admin.
                              get_ip_address_by_network_name(self.admin_net2))
        logger.info(('Parameters for second admin interface configuration: '
                     'Network - {0}, Netmask - {1}, Interface - {2}, '
                     'IP Address - {3}').format(second_admin_network,
                                                second_admin_netmask,
                                                second_admin_if,
                                                second_admin_ip))
        add_second_admin_ip = ('DEVICE={0}\\n'
                               'ONBOOT=yes\\n'
                               'NM_CONTROLLED=no\\n'
                               'USERCTL=no\\n'
                               'PEERDNS=no\\n'
                               'BOOTPROTO=static\\n'
                               'IPADDR={1}\\n'
                               'NETMASK={2}\\n').format(second_admin_if,
                                                        second_admin_ip,
                                                        second_admin_netmask)
        cmd = ('echo -e "{0}" > /etc/sysconfig/network-scripts/ifcfg-{1};'
               'ifup {1}; ip -o -4 a s {1} | grep -w {2}').format(
            add_second_admin_ip, second_admin_if, second_admin_ip)
        logger.debug('Trying to assign {0} IP to the {1} on master node...'.
                     format(second_admin_ip, second_admin_if))
        result = remote.execute(cmd)
        assert_equal(result['exit_code'], 0, ('Failed to assign second admin '
                     'IP address on master node: {0}').format(result))
        logger.debug('Done: {0}'.format(result['stdout']))
        self.configure_second_admin_firewall(second_admin_network,
                                             second_admin_netmask)

    @logwrap
    def configure_second_admin_cobbler(self):
        dhcp_template = '/etc/cobbler/dnsmasq.template'
        remote = self.get_admin_remote()
        main_admin_ip = str(self.nodes().admin.
                            get_ip_address_by_network_name(self.admin_net))
        second_admin_ip = str(self.nodes().admin.
                              get_ip_address_by_network_name(self.admin_net2))
        second_admin_network = self.get_network(self.admin_net2).split('/')[0]
        second_admin_netmask = self.get_net_mask(self.admin_net2)
        network = IPNetwork('{0}/{1}'.format(second_admin_network,
                                             second_admin_netmask))
        discovery_subnet = [net for net in network.iter_subnets(1)][-1]
        first_discovery_address = str(discovery_subnet.network)
        last_discovery_address = str(discovery_subnet.broadcast - 1)
        new_range = ('dhcp-range=internal2,{0},{1},{2}\\n'
                     'dhcp-option=net:internal2,option:router,{3}\\n'
                     'dhcp-boot=net:internal2,pxelinux.0,boothost,{4}\\n').\
            format(first_discovery_address, last_discovery_address,
                   second_admin_netmask, second_admin_ip, main_admin_ip)
        cmd = ("dockerctl shell cobbler sed -r '$a \{0}' -i {1};"
               "dockerctl shell cobbler cobbler sync").format(new_range,
                                                              dhcp_template)
        result = remote.execute(cmd)
        assert_equal(result['exit_code'], 0, ('Failed to add second admin'
                     'network to cobbler: {0}').format(result))

    @logwrap
    def configure_second_admin_firewall(self, network, netmask):
        remote = self.get_admin_remote()
        # Allow forwarding and correct remote logging
        # for nodes from the second admin network
        rules = [
            ('-t nat -I POSTROUTING -s {0}/{1} -p udp -m udp --dport 514 -m'
             ' comment --comment "rsyslog-udp-514-unmasquerade" -j ACCEPT;').
            format(network, netmask),
            ('-t nat -I POSTROUTING -s {0}/{1} -p tcp -m tcp --dport 514 -m'
             ' comment --comment "rsyslog-tcp-514-unmasquerade" -j ACCEPT;').
            format(network, netmask),
            ('-t nat -I POSTROUTING -s {0}/{1} -o eth+ -m comment --comment '
             '"004 forward_admin_net2" -j MASQUERADE').
            format(network, netmask),
            ('-I FORWARD -i {0} -o docker0 -p tcp -m state --state NEW -m tcp'
             ' --dport 514 -m comment --comment "rsyslog-tcp-514-accept" -j '
             'ACCEPT').format(settings.INTERFACES.get(self.admin_net2)),
            ('-I FORWARD -i {0} -o docker0 -p udp -m state --state NEW -m udp'
             ' --dport 514 -m comment --comment "rsyslog-udp-514-accept" -j '
             'ACCEPT').format(settings.INTERFACES.get(self.admin_net2))
        ]

        for rule in rules:
            cmd = 'iptables {0}'.format(rule)
            result = remote.execute(cmd)
            assert_equal(result['exit_code'], 0,
                         ('Failed to add firewall rule for second admin net'
                          'on master node: {0}, {1}').format(rule, result))
        # Save new firewall configuration
        cmd = 'service iptables save'
        result = remote.execute(cmd)
        assert_equal(result['exit_code'], 0,
                     ('Failed to save firewall configuration on master node:'
                      ' {0}').format(result))

    @logwrap
    def configure_second_dhcrelay(self):
        remote = self.get_admin_remote()
        second_admin_if = settings.INTERFACES.get(self.admin_net2)
        sed_cmd = "/  interface:/a \  interface: {0}".format(second_admin_if)
        self._fuel_web.modify_python_file(remote, sed_cmd,
                                          settings.FUEL_SETTINGS_YAML)
        cmd = ('supervisorctl restart dhcrelay_monitor; '
               'pgrep -f "[d]hcrelay.*{0}"').format(second_admin_if)
        result = remote.execute(cmd)
        assert_equal(result['exit_code'], 0, ('Failed to start DHCP relay on '
                     'second admin interface: {0}').format(result))


class NodeRoles(object):
    def __init__(self,
                 admin_names=None,
                 other_names=None):
        self.admin_names = admin_names or []
        self.other_names = other_names or []


class Nodes(object):
    def __init__(self, environment, node_roles):
        self.admins = []
        self.others = []
        for node_name in node_roles.admin_names:
            self.admins.append(environment.node_by_name(node_name))
        for node_name in node_roles.other_names:
            self.others.append(environment.node_by_name(node_name))
        self.slaves = self.others
        self.all = self.slaves + self.admins
        self.admin = self.admins[0]

    def __iter__(self):
        return self.all.__iter__()
