#!/usr/bin/env bash

LOG="${1:-network_health_log.csv}"
ARCHIVE=0

if [[ "$1" == "--archive" ]]; then
    ARCHIVE=1
    LOG="${2:-network_health_log.csv}"
else
    LOG="${1:-network_health_log.csv}"
fi

if [ ! -f "$LOG" ]; then
  echo "Log file not found: $LOG"
  exit 1
fi

echo "=== Summary by target ==="
awk -F',' '
NR > 1 {
  total[$3]++
  if ($6 != "OK") fail[$3]++
}
END {
  printf "%-20s %8s %8s %8s\n", "target", "total", "fails", "fail_%"
  for (t in total) {
    pct = (fail[t] / total[t]) * 100
    printf "%-20s %8d %8d %7.2f%%\n", t, total[t], fail[t], pct
  }
}' "$LOG" | sort

echo
echo "=== Failures ==="
awk -F',' '
NR > 1 && $6 != "OK" {
  printf "%s  %-20s %-15s %s\n", $1, $3, $4, $8
}' "$LOG"

echo
echo "=== High latency > 250 ms ==="
awk -F',' '
NR > 1 && $6 == "OK" && $7 != "" && $7+0 > 250 {
  printf "%s  %-20s %-15s %s ms\n", $1, $3, $4, $7
}' "$LOG"

echo
echo "=== Quick diagnosis hints ==="
awk -F',' '
NR > 1 {
  ts=$1
  label=$3
  status=$6

  if (status != "OK") {
    fails_at[ts] = fails_at[ts] " " label
  }
}
END {
  for (ts in fails_at) {
    f=fails_at[ts]
    if (f ~ /router/ && f ~ /cloudflare|google_dns|dns_hostname/) {
      print ts " : router + internet failed -> possible router/LAN issue"
    } else if (f !~ /router/ && f ~ /cloudflare|google_dns|dns_hostname/) {
      print ts " : router OK, internet failed -> likely ISP/WAN issue"
    } else if (f ~ /dns_hostname/ && f !~ /cloudflare|google_dns/) {
      print ts " : hostname failed but IPs OK -> possible DNS issue"
    } else if (f ~ /lan_peer/) {
      print ts " : LAN peer failed -> possible local LAN/switch/device issue"
    }
  }
}' "$LOG" | sort

if [[ "$ARCHIVE" -eq 1 ]]; then
    ARCHIVE_NAME="network_health_log_$(date +%Y%m%d_%H%M%S).csv"

    echo
    echo "=== Archiving current log ==="
    mv "$LOG" "$ARCHIVE_NAME"

    echo "Archived to: $ARCHIVE_NAME"

    # Recreate empty log with header
    head -n 1 "$ARCHIVE_NAME" > "$LOG"

    echo "Created fresh log: $LOG"
fi