#!/bin/sh
# Installs HYUNDAI_KIA_CONNECT_API_VERSION, when set, over the bundled library version,
# then starts the bridge. It can be an exact version, "latest", or a URL.
set -eu

version=${HYUNDAI_KIA_CONNECT_API_VERSION:-}

if [ -n "$version" ]; then
  case $version in
    latest) requirement=hyundai-kia-connect-api ;;
    *://*) requirement="hyundai-kia-connect-api @ $version" ;;
    *) requirement="hyundai-kia-connect-api==$version" ;;
  esac

  echo "Installing $requirement (HYUNDAI_KIA_CONNECT_API_VERSION)"

  if ! uv pip install --python /app/.venv --upgrade-package hyundai-kia-connect-api "$requirement"; then
    echo "Couldn't install $requirement from HYUNDAI_KIA_CONNECT_API_VERSION" >&2
    exit 1
  fi
fi

exec "$@"
