# Sourced by the platform installers after CONFIG and SOURCE are set.
BOOTSTRAP_ARGS=()
WITH_NFS=1
INSTALL_DEPENDENCIES=1
while [ "$#" -gt 0 ]; do
  case "$1" in
    --username|--password-file)
      [ "$#" -ge 2 ] || { echo "Missing value for $1" >&2; exit 1; }
      BOOTSTRAP_ARGS+=("$1" "$2"); shift 2 ;;
    --without-nfs) WITH_NFS=0; shift ;;
    --skip-dependencies) INSTALL_DEPENDENCIES=0; shift ;;
    *) echo "Unknown installer option: $1" >&2; exit 1 ;;
  esac
done
[ -f "$CONFIG" ] || { echo 'Configuration file does not exist.' >&2; exit 1; }
umask 077
