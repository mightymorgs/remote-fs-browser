#!/usr/bin/env bash
set -euo pipefail
case "$(uname -s)" in
 Linux) exec "$(dirname "$0")/linux/install.sh" "$@" ;;
 Darwin) exec "$(dirname "$0")/macos/install.sh" "$@" ;;
 *) echo 'On Windows, use scripts/windows/install.ps1' >&2; exit 1 ;;
esac
