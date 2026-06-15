#!/usr/bin/env bash
# Baseline EuRoC run — wrapper around run_euroc.sh
exec "$(dirname "$0")/run_euroc.sh" baseline "$@"
