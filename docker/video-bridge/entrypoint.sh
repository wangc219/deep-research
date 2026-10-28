#!/bin/sh
set -eu
if [ ! -s /run/authorized_keys ]; then
  echo 'Missing collector SSH public key: mount a .pub file at /run/authorized_keys' >&2
  exit 1
fi
cp /run/authorized_keys /keys/authorized_keys
chown root:root /keys /keys/authorized_keys
chmod 0755 /keys
chmod 0644 /keys/authorized_keys
if [ ! -f /host-keys/ssh_host_ed25519_key ]; then
  ssh-keygen -q -t ed25519 -N '' -f /host-keys/ssh_host_ed25519_key
fi
exec /usr/sbin/sshd -D -e
