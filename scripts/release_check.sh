#!/bin/bash
DIFF="$(git status grpclib setup.py -s)"
if [[ DIFF ]]; then
    echo "Working directory is not clean:"
    echo $DIFF | sed 's/^/  /'
    false
else
    true
fi
