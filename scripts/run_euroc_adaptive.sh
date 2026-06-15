#!/usr/bin/env bash
# Adaptive EuRoC run (trust_estimator) — wrapper around run_euroc.sh
exec "$(dirname "$0")/run_euroc.sh" adaptive "$@"
