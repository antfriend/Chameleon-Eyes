#!/bin/sh
# Keep the eye website running: start eye_server.py, and start it again if it stops.
# Started at boot by the arduino user's crontab:
#
#     @reboot /home/arduino/chameleon/start_eyes.sh
#
# The retry also covers boot, when cron can run before the cameras are ready.
# Stop it with:  pkill -f '[s]tart_eyes.sh'; pkill -f '[e]ye_server.py'
cd "$(dirname "$0")" || exit 1
while true; do
    python3 eye_server.py >> eye_server.log 2>&1
    sleep 5
done
