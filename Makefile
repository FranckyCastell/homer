SHELL := /usr/bin/env -S bash

all: help

help:
	@awk 'BEGIN {FS = ":.*##"; printf "\033[1;33mUsage:\033[0m\n\tmake \033[36m<target>\033[0m\n\033[1;33mTargets:\033[0m\n"} /^[a-zA-Z _\-\/]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

.PHONY: build
build:
	@if [ ! -d "./.venv" ];then \
		python3 -m venv .venv; \
	fi;
	.venv/bin/pip install wheel; \
	.venv/bin/pip install pyinstaller; \
	.venv/bin/pyinstaller --name homer --bootloader-ignore-signals -y main.py;

.PHONY: reinstall
reinstall: uninstall install

.PHONY: install
install:
	@echo "Installing to /usr/local/bin"
	@cp -r dist/homer/* /usr/local/bin/

.PHONY: uninstall
uninstall:
	@echo "Deleting /usr/local/bin/homer"
	@rm -f /usr/local/bin/homer

.PHONY: clean
clean:
	@echo "Cleaning up..."
	@rm -f homer.spec
	@rm -rf build/ dist/
	@rm -rf .venv