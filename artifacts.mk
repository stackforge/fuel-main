.PHONY: artifacts

artifacts: \
	$(ART_DIR)/bootstrap.tar.gz \
	$(ART_DIR)/centos-repo.tar \
	$(ART_DIR)/ubuntu-repo.tar \
	$(ART_DIR)/upgrade-venv.tar.gz \
	$(ART_DIR)/manifests.tar.gz \
	$(ART_DIR)/fuel-images.tar.lrz \
	$(ART_DIR)/version.yaml \
	$(ART_DIR)/openstack.yaml \
	$(ART_DIR)/centos-versions.yaml \
	$(ART_DIR)/ubuntu-versions.yaml

$(ART_DIR)/version.yaml: $(ISOROOT)/version.yaml
	$(ACTION.COPY)

$(ART_DIR)/openstack.yaml: \
		$(BUILD_DIR)/repos/nailgun/nailgun/nailgun/fixtures/openstack.yaml
	$(ACTION.COPY)

$(ART_DIR)/centos-versions.yaml: $(ISOROOT)/centos-versions.yaml
	$(ACTION.COPY)

$(ART_DIR)/ubuntu-versions.yaml: $(ISOROOT)/ubuntu-versions.yaml
	$(ACTION.COPY)

$(ART_DIR)/manifests.tar.gz: $(ISOROOT)/puppet-slave.tgz
	$(ACTION.COPY)

$(ART_DIR)/fuel-images.tar.lrz: $(ISOROOT)/docker.done
	mkdir -p $(@D)
	cp $(ISOROOT)/docker/images/fuel-images.tar.lrz $@

$(ART_DIR)/bootstrap.tar.gz: $(BUILD_DIR)/bootstrap/build.done
	mkdir -p $(@D)
	tar zcf $@ -C $(BUILD_DIR)/bootstrap initramfs.img linux

$(ART_DIR)/centos-repo.tar: $(BUILD_DIR)/packages/build.done
	mkdir -p $(@D)
	tar cf $@ -C $(LOCAL_MIRROR_CENTOS_OS_BASEURL) .

$(ART_DIR)/ubuntu-repo.tar:
	mkdir -p $(@D)
	tar cf $@ -C $(LOCAL_MIRROR_UBUNTU_OS_BASEURL) .

$(ART_DIR)/upgrade-venv.tar.gz: $(BUILD_DIR)/upgrade/venv.done
	mkdir -p $(@D)
	tar zcf $@ -C $(BUILD_DIR)/upgrade/venv .
