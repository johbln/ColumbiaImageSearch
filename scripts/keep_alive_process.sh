#!/bin/bash

sleep_time=600

while getopts :-: option
do
  case "${option}"
  in
  - )  LONG_OPTARG="${OPTARG#*=}"
         case $OPTARG in
           cmd=?*  ) command="$LONG_OPTARG" ;;
           args=?* ) args="$LONG_OPTARG" ;;
           log=?* ) log="$LONG_OPTARG";;
           *    ) echo "Illegal option --$OPTARG" >&2; exit 2 ;;
         esac ;;
  esac
done

if [ ${command+x} ]; then
  echo "command: "${command}
else
  echo "command not set. Use --cmd to set command please."
  exit -1
fi

if [ ${args+x} ]; then
  echo "args: "${args}
else
  echo "args not set. Use --args to set args please."
  exit -1
fi

if [ ${log+x} ]; then
  echo "log: "${log}
else
  echo "log not set. Use --log to set args please."
  exit -1
fi

while true;
do
    echo "["$(date)"] Starting process." >> ${log}"_keepalive";
    ${command} ${args} &> ${log}"_"$(date +%Y-%m-%d_%H-%M-%S);
    echo "["$(date)"] Process crashed." >> ${log}"_keepalive";
    sleep ${sleep_time};
done
