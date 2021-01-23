#!/bin/bash
#
# supply docksignal to robot from shell script to reduce resources
#	  Designed to be executed by triggerhappy or similar when infrared
#   docking signal is received by robot kernel
#

printf -v time '%(%s)T' -1
signal=$1

make_docksignal_json() {
  cat <<EOF
  {"dockSignal": {"time": $time, "$signal": 1}}
EOF
}

payload="$(make_docksignal_json)"$'\r'$'\n'

curl --cacert $ROBOT_CA -H "Content-Type: application/json" \
  -H "User: $ROBOT_USER" -H "Authorization: TOK:$ROBOT_APITOKEN" \
  -X POST --data "$payload" $ROBOT_URL/docksignal
