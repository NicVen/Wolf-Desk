"""STAALWAG licensing — admin control CLI.

Strict control over every rented key from the VPS terminal. Talks to the local
licensing service (the service stays the single writer; the sweeper keeps
enforcing expiry/grace/revoke on its own).

Run on the box (env is auto-loaded from /etc/staalwag-licensing.env):

  python3 -m licensing.adminctl list                 # every key + status + days left
  python3 -m licensing.adminctl issue APP --days 30 --contact 123456789
  python3 -m licensing.adminctl admin-key            # your no-bind, all-product master key
  python3 -m licensing.adminctl revoke APP-XXXXXXXX  # cut access now
  python3 -m licensing.adminctl extend APP-XXXXXXXX --days 30
  python3 -m licensing.adminctl reset  APP-XXXXXXXX  # unbind device (client got a new phone)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

from . import config

ENV_FILE = "/etc/staalwag-licensing.env"


def _load_env():
    """Populate ADMIN_TOKEN etc. from the service env file if not already set."""
    if os.environ.get("ADMIN_TOKEN"):
        return
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _base():
    return os.environ.get("LICENSING_LOCAL", "http://127.0.0.1:%d" % config.PORT)


def _call(method, path, data=None):
    token = os.environ.get("ADMIN_TOKEN", config.ADMIN_TOKEN)
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(_base() + path, data=body, method=method,
                                 headers={"X-Admin-Token": token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": "HTTP %d: %s" % (e.code, e.read().decode()[:200])}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def _ago(ts):
    if not ts:
        return "never"
    d = int(time.time()) - int(ts)
    if d < 3600:
        return "%dm" % (d // 60)
    if d < 86400:
        return "%dh" % (d // 3600)
    return "%dd" % (d // 86400)


def cmd_list(_a):
    res = _call("GET", "/admin/list")
    if res.get("error"):
        print("ERROR:", res["error"]); return 1
    lic = res.get("licenses", [])
    if not lic:
        print("No licenses yet."); return 0
    print("%-18s %-10s %-9s %-8s %8s  %-7s %-16s %s" %
          ("KEY", "PRODUCT", "STATUS", "ACCESS", "DAYS", "SEEN", "CONTACT", "FLAGS"))
    print("-" * 100)
    for l in lic:
        flags = []
        if l["admin"]:
            flags.append("ADMIN")
        if l["no_bind"]:
            flags.append("no-bind")
        if l["bound"]:
            flags.append("bound")
        dl = "" if l["days_left"] is None else ("%.1f" % l["days_left"])
        print("%-18s %-10s %-9s %-8s %8s  %-7s %-16s %s" %
              (l["key"], l["product"], l["status"], l["access"], dl,
               _ago(l["last_seen"]), (l["contact"] or "")[:16], " ".join(flags)))
    print("-" * 100)
    print("%d license(s)." % res.get("count", len(lic)))
    return 0


def cmd_issue(a):
    payload = {"product": a.product, "days": a.days}
    if a.contact:
        payload["contact"] = a.contact
    if a.no_bind:
        payload["no_bind"] = True
    res = _call("POST", "/admin/issue", payload)
    print(json.dumps(res, indent=2))
    return 1 if res.get("error") else 0


def cmd_admin_key(a):
    res = _call("POST", "/admin/issue",
                {"product": "APP", "admin": True, "contact": a.contact or "admin"})
    if res.get("error"):
        print("ERROR:", res["error"]); return 1
    print("Admin master key (works on every device, every product, never expires):\n")
    print("   ", res["license_key"], "\n")
    print("Enter it once in the app / any product and you're in — no rebinding, no expiry.")
    return 0


def cmd_revoke(a):
    print(json.dumps(_call("POST", "/admin/revoke", {"key": a.key}), indent=2)); return 0


def cmd_extend(a):
    print(json.dumps(_call("POST", "/admin/extend", {"key": a.key, "days": a.days}), indent=2)); return 0


def cmd_reset(a):
    print(json.dumps(_call("POST", "/admin/reset_device", {"key": a.key}), indent=2)); return 0


def cmd_announce(a):
    try:
        with open(a.file) as f:
            ver = json.load(f)
    except Exception as e:  # noqa: BLE001
        print("ERROR reading %s: %s" % (a.file, e)); return 1
    payload = {"product": a.product, "version": ver.get("version", ""),
               "title": ver.get("title", ""), "type": ver.get("type", ""),
               "notes": ver.get("notes", [])}
    print("Announcing %s v%s to active %s renters..." % (a.product, payload["version"], a.product))
    print(json.dumps(_call("POST", "/admin/announce", payload), indent=2))
    return 0


def main(argv=None):
    _load_env()
    ap = argparse.ArgumentParser(prog="adminctl", description="STAALWAG licensing control")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show every key + status").set_defaults(fn=cmd_list)

    pi = sub.add_parser("issue", help="issue/extend a key for a client")
    pi.add_argument("product")
    pi.add_argument("--days", type=int, default=30)
    pi.add_argument("--contact", default="")
    pi.add_argument("--no-bind", dest="no_bind", action="store_true",
                    help="allow this key on multiple devices")
    pi.set_defaults(fn=cmd_issue)

    pa = sub.add_parser("admin-key", help="mint your no-bind, all-product master key")
    pa.add_argument("--contact", default="admin")
    pa.set_defaults(fn=cmd_admin_key)

    pr = sub.add_parser("revoke", help="cut a key's access immediately")
    pr.add_argument("key"); pr.set_defaults(fn=cmd_revoke)

    pe = sub.add_parser("extend", help="add days to a key (manual renewal / comp)")
    pe.add_argument("key"); pe.add_argument("--days", type=int, default=30)
    pe.set_defaults(fn=cmd_extend)

    prs = sub.add_parser("reset", help="clear a key's device binding")
    prs.add_argument("key"); prs.set_defaults(fn=cmd_reset)

    pan = sub.add_parser("announce", help="notify active renters about a new app version")
    pan.add_argument("--product", default="APP")
    pan.add_argument("--file", default="dashboard/appversion.json")
    pan.set_defaults(fn=cmd_announce)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
