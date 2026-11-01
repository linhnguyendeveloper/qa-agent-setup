#!/usr/bin/env bash
# macOS/Linux counterpart of browser.ps1: starts (or stops) the headed browser used
# for manual login, with remote debugging on the given port and a throwaway profile
# under the scratchpad. Uses Microsoft Edge if present, otherwise Google Chrome.
#   bash browser.sh start <url> <scratchpad> [port]                    fresh profile, user logs in by hand
#   bash browser.sh start-profile <url> <scratchpad> <port> <profile> [edge|chrome]
#                                                                      browser on a temporary copy of the user's real
#                                                                      profile (<profile> = "Default", "Profile 1", ...); default edge
#   bash browser.sh profiles [edge|chrome]                             list the browser's profile directories and names
#   bash browser.sh stop  <scratchpad>
# Chrome refuses --remote-debugging-port on its real user-data-dir, so start-profile copies only the
# login-bearing files (cookies, local/session storage, preferences) into <scratchpad>/pw-profile and
# runs the browser there with sync and extensions off. stop deletes that copy.
#
# Parallel runs (several projects or git worktrees at once) stay apart because everything is keyed to
# the scratchpad's absolute path: the port is the requested one or the next free one, and the port
# actually used is written to <scratchpad>/cdp.port (lib.js reads it via QA_SCRATCH); stop only kills
# the browser on this scratchpad's profile and the recorder whose pid is in <scratchpad>/recorder.pid.
set -u
action="${1:-}"

# Absolute, symlink-free scratchpad path, so start and stop see the same string however it was passed.
abs_dir() { mkdir -p "$1" && (cd "$1" && pwd -P); }

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# First free port from $1 upward (50 tries); never reuse a port another browser already listens on.
free_port() {
  local p="$1" last=$(( $1 + 50 ))
  while [ "$p" -le "$last" ]; do
    port_busy "$p" || { echo "$p"; return 0; }
    p=$(( p + 1 ))
  done
  echo "no free port in $1-$last" >&2
  return 1
}

if [ "$action" = "stop" ]; then
  scratch="$(abs_dir "${2:?scratchpad required}")"
  pkill -f -- "--user-data-dir=$scratch/pw-profile" 2>/dev/null
  if [ -f "$scratch/recorder.pid" ]; then
    pid="$(cat "$scratch/recorder.pid")"
    ps -p "$pid" -o command= 2>/dev/null | grep -q "recorder.js" && kill "$pid" 2>/dev/null
    rm -f "$scratch/recorder.pid"
  fi
  sleep 2
  rm -rf "$scratch/pw-profile" "$scratch/cdp.port"
  [ -e "$scratch/pw-profile" ] && echo "profile removed: false" || echo "profile removed: true"
  exit 0
fi

# Resolve user-data root and binary for the chosen browser ($1 = edge|chrome).
resolve_browser() {
  local which="${1:-edge}"
  case "$(uname)-$which" in
    Darwin-edge)   root="$HOME/Library/Application Support/Microsoft Edge"; bin="/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" ;;
    Darwin-chrome) root="$HOME/Library/Application Support/Google/Chrome";  bin="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ;;
    *-edge)        root="$HOME/.config/microsoft-edge";                      bin="$(command -v microsoft-edge 2>/dev/null)" ;;
    *-chrome)      root="$HOME/.config/google-chrome";                       bin="$(command -v google-chrome 2>/dev/null)" ;;
    *) echo "unknown browser: $which (edge|chrome)"; exit 2 ;;
  esac
}

if [ "$action" = "profiles" ]; then
  resolve_browser "${2:-edge}"
  python3 - "$root" <<'PY'
import json, sys
info = json.load(open(sys.argv[1] + "/Local State"))["profile"]["info_cache"]
for key, v in info.items():
    print(f"{key} | {v.get('name')} | {v.get('user_name') or '-'}")
PY
  exit 0
fi

if [ "$action" = "start-profile" ]; then
  url="${2:?url required}"; scratch="$(abs_dir "${3:?scratchpad required}")"; profile="${5:?profile dir required}"
  port="$(free_port "${4:?port required}")" || exit 1
  resolve_browser "${6:-edge}"
  src="$root/$profile"
  [ -d "$src" ] || { echo "profile dir not found: $profile (run: browser.sh profiles ${6:-edge})"; exit 1; }
  [ -x "$bin" ] || { echo "browser not found: $bin"; exit 1; }
  dest="$scratch/pw-profile"
  rm -rf "$dest"; mkdir -p "$dest/$profile"
  cp "$root/Local State" "$dest/Local State"
  for item in Network "Local Storage" "Session Storage" Preferences "Secure Preferences" Cookies; do
    [ -e "$src/$item" ] && cp -R "$src/$item" "$dest/$profile/$item"
  done
  nohup "$bin" --remote-debugging-port="$port" --user-data-dir="$dest" --profile-directory="$profile" \
    --disable-sync --disable-extensions --no-first-run --no-default-browser-check "$url" >/dev/null 2>&1 &
  echo "$port" > "$scratch/cdp.port"
  echo "started $url on port $port with a temporary copy of ${6:-edge} profile '$profile'"
  exit 0
fi

[ "$action" = "start" ] || { echo "usage: browser.sh start|start-profile|profiles|stop ..."; exit 2; }
url="${2:?url required}"; scratch="$(abs_dir "${3:?scratchpad required}")"
port="$(free_port "${4:-9222}")" || exit 1

browser=""
for c in "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
         "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
         "$(command -v microsoft-edge 2>/dev/null)" "$(command -v google-chrome 2>/dev/null)"; do
  [ -n "$c" ] && [ -x "$c" ] && { browser="$c"; break; }
done
[ -n "$browser" ] || { echo "Edge/Chrome not found"; exit 1; }

nohup "$browser" --remote-debugging-port="$port" --user-data-dir="$scratch/pw-profile" \
  --no-first-run --no-default-browser-check "$url" >/dev/null 2>&1 &
echo "$port" > "$scratch/cdp.port"
echo "started $url on port $port using $(basename "$browser")"
