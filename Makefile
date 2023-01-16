#.SILENT:
SHELL = /bin/bash


all:
	echo -e "Required section:\n\
 build - build project into build directory, with configuration file and environment\n\
 clean - clean all addition file, build directory and output archive file\n\
 test - run all tests\n\
 pack - make output archive, file name format \"ks_prepare_vX.Y.Z_BRANCHNAME.tar.gz\"\n\
"

VERSION := 0.0.1
BRANCH := $(shell git name-rev $$(git rev-parse HEAD) | cut -d\  -f2 | sed -re 's/^(remotes\/)?origin\///' | tr '/' '_')

CONDA = conda/miniconda/bin/conda


conda/miniconda.sh:
	echo Download Miniconda
	mkdir -p conda
	wget https://repo.anaconda.com/miniconda/Miniconda3-py39_4.12.0-Linux-x86_64.sh -O conda/miniconda.sh; \

conda/miniconda: conda/miniconda.sh
	bash conda/miniconda.sh -b -p conda/miniconda; \

install_conda: conda/miniconda

conda/miniconda/bin/conda-pack: conda/miniconda
	conda/miniconda/bin/conda install conda-pack -c conda-forge  -y

install_conda_pack: conda/miniconda/bin/conda-pack

clean_conda:
	rm -rf ./conda
pack: make_build
	rm -f *.tar.gz
	echo Create archive \"ks_prepare-$(VERSION)-$(BRANCH).tar.gz\"
	cd make_build; tar czf ../ks_prepare-$(VERSION)-$(BRANCH).tar.gz ks_prepare

clean_pack:
	rm -f *.tar.gz


build: make_build

make_build:
	# required section
	echo make_build
	mkdir make_build
	cp -R ./ks_prepare make_build

	cp *.md make_build/ks_prepare/


conda_venv: conda/miniconda
	$(CONDA) create --copy -p conda_venv -y
	$(CONDA) install -p conda_venv python==3.9.7 -y
	./conda_venv/bin/python3.9 -m pip  install postprocessing_sdk --extra-index-url http://s.dev.isgneuro.com/repository/ot.platform/simple --trusted-host s.dev.isgneuro.com


venv.tar.gz: conda_venv conda/miniconda/bin/conda-pack
	$(CONDA) pack -p ./conda_venv -o ./venv.tar.gz

venv: venv.tar.gz
	mkdir -p ./venv
	tar -xzf ./venv.tar.gz -C ./venv

clean_venv:
	rm -rf ./venv
	rm -rf ./conda_venv
	rm -rf ./venv.tar.gz

venv/lib/python3.9/site-packages/postprocessing_sdk/pp_cmd/ks_prepare: venv
	ln -r -s ./ks_prepare venv/lib/python3.9/site-packages/postprocessing_sdk/pp_cmd/ks_prepare


dev: venv/lib/python3.9/site-packages/postprocessing_sdk/pp_cmd/ks_prepare
	@echo "!!!IMPORTANT!!!. Configure otl_v1 config.ini"
	@echo "   !!!!    "
	@echo "   vi venv/lib/python3.9/site-packages/postprocessing_sdk/pp_cmd/otl_v1/config.ini"
	@echo "   !!!!    "
	cp ks_prepare/config.example.ini ks_prepare/config.ini
	@echo "   !!!!   Configure mapping objectType -> primitiveName "
	@echo "   vi ks_prepare/config.ini"
	@echo "   !!!!    "
	touch ./dev


clean_build:
	rm -rf make_build


clean: clean_build clean_pack

clean_dev: clean_venv
	rm -f ./dev

test:
	@echo "Testing..."

clean_test:
	@echo "Clean tests"
