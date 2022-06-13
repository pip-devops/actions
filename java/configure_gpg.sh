#!/usr/bin/env bash

export XDG_RUNTIME_DIR="/run/user/$UID"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"

systemctl --user status gpg-agent
systemctl --user stop gpg-agent
systemctl --user start gpg-agent