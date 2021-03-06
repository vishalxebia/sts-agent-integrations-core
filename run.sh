#!/bin/bash

set -e

if [ $# -ne 1 ]; then
    echo "Usage: run.sh <start|stop|install>"
    exit 1
fi

rm -rf embedded/dd-agent/checks.d || true
mkdir -p embedded/dd-agent/checks.d
conf_dir=embedded/dd-agent/conf.d/ checks_dir=embedded/dd-agent/checks.d rake copy_checks

pushd embedded/dd-agent

if [ "$1" != "install" ]; then
    python agent.py $1
fi

popd
