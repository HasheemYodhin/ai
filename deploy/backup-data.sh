#!/usr/bin/env bash
# Run while Dabba is stopped so databases and their referenced files agree.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: bash deploy/backup-data.sh DATA_DIRECTORY OUTPUT.tar.gz" >&2
  exit 2
fi

data_dir=$(realpath -e -- "$1")
target=$(realpath -m -- "$2")
if [[ ! -d "$data_dir" || "$data_dir" == / ]]; then
  echo "Provide the Dabba data directory." >&2
  exit 2
fi
if [[ "$target" == "$data_dir" || "$target" == "$data_dir/"* || -e "$target" || -L "$target" ]]; then
  echo "Choose a new archive path outside the data directory." >&2
  exit 2
fi
if [[ ! -f "$data_dir/platform.db" || ! -f "$data_dir/conversations.db" ]]; then
  echo "Expected platform.db and conversations.db in the data directory." >&2
  exit 2
fi

umask 077
temp_archive=$(mktemp -- "${target}.partial.XXXXXX")
trap 'rm -f -- "$temp_archive"' EXIT
tar --create --gzip --file "$temp_archive" --directory "$data_dir" .
tar --list --gzip --file "$temp_archive" >/dev/null
ln -T -- "$temp_archive" "$target"
echo "Backup written to $target"
