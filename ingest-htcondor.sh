#!/usr/bin/env bash
set -euo pipefail

API="http://localhost:31800/v1/documents/ingest"
WORKSPACE="htcondor"
FILE_LIST="/home/b/Desktop/roadrunner/htcondor-files.txt"
LOG="/home/b/Desktop/roadrunner/ingest-htcondor.log"
BASE="/home/b/Desktop/roadrunner/htcondor"
PARALLEL=8
TOTAL=$(wc -l < "$FILE_LIST")

> "$LOG"

echo "Ingesting $TOTAL files into workspace '$WORKSPACE' with $PARALLEL parallel workers..."
echo "Log: $LOG"

nl -ba "$FILE_LIST" | xargs -P "$PARALLEL" -I {} bash -c '
    num=$(echo "{}" | awk "{print \$1}")
    filepath=$(echo "{}" | awk "{print \$2}")
    total='"$TOTAL"'

    # Derive relative path from base dir (e.g. bindings/python/classad2/_class_ad.py)
    relpath="${filepath#'"$BASE"'/}"

    response=$(curl -s -w "\n%{http_code}" \
        -X POST "'"$API"'" \
        -H "X-Workspace: '"$WORKSPACE"'" \
        -F "file=@${filepath};filename=${relpath}" \
        --connect-timeout 10 \
        --max-time 60 2>&1)

    http_code=$(echo "$response" | tail -1)
    body=$(echo "$response" | sed "\$d")

    if [[ "$http_code" == "200" ]]; then
        echo "[${num}/'"$TOTAL"'] OK: ${relpath}"
    else
        echo "[${num}/'"$TOTAL"'] FAIL(${http_code}): ${relpath} — ${body}"
    fi
' >> "$LOG" 2>&1

FAIL=$(grep -c "^\\[.*FAIL" "$LOG" 2>/dev/null || true)
OK=$(grep -c "^\\[.*OK" "$LOG" 2>/dev/null || true)

echo ""
echo "Done. $OK succeeded, $FAIL failed out of $TOTAL."
echo "Full log: $LOG"
