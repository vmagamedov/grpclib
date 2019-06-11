mkfile_dir := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

keys:
	rm -f $(mkfile_dir)*.key
	rm -f $(mkfile_dir)*.pem
	openssl req -x509 -newkey rsa:2048 -nodes -subj '/CN=mccoy.earth.svc.cluster.local' -keyout $(mkfile_dir)mccoy.key -out $(mkfile_dir)mccoy.pem
	openssl req -x509 -newkey rsa:2048 -nodes -subj '/CN=mccoy.earth.svc.cluster.local' -keyout $(mkfile_dir)mccoy-imposter.key -out $(mkfile_dir)mccoy-imposter.pem
	openssl req -x509 -newkey rsa:2048 -nodes -subj '/CN=spock.vulcan.svc.cluster.local' -keyout $(mkfile_dir)spock.key -out $(mkfile_dir)spock.pem
	openssl req -x509 -newkey rsa:2048 -nodes -subj '/CN=spock.vulcan.svc.cluster.local' -keyout $(mkfile_dir)spock-imposter.key -out $(mkfile_dir)spock-imposter.pem
