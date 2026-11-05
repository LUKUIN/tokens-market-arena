# -*- coding: utf-8 -*-
"""Source guard for a live match.

While a match is running, the Python sources are moved into a sealed vault and
replaced by decoy files. Anything that reads the decoys sees an explicit
"CHEATING DETECTED" notice instead of the real parameters; anything that tries to
execute or import a decoy drops a flag, and this guard then ends the match.

Usage:
    python guard.py start [--port 8734]
    python guard.py stop
    python guard.py status
    python guard.py clean        # stop + restore, safe to run any time
"""
import hashlib
import hmac
import io
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.join(HERE, "_guard_vault")
# 加密箱放在项目目录之外，避免和源码同处一棵树里被顺手打包拷走
GUARD_ROOT = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or tempfile.gettempdir(),
    "TokensMarketGuard")
MAGIC = b"TMG1"


def _keystream(key, nonce, n):
    """SHA-256 计数器流：标准库就能拼出的 CTR 流密码，只为防顺手读，不是密码学边界。"""
    buf = bytearray()
    i = 0
    while len(buf) < n:
        buf += hashlib.sha256(key + nonce + i.to_bytes(8, "big")).digest()
        i += 1
    return bytes(buf[:n])


def _encrypt(key, data):
    nonce = os.urandom(16)
    ks = _keystream(key, nonce, len(data))
    ct = bytes(a ^ b for a, b in zip(data, ks))
    tag = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    return MAGIC + nonce + tag + ct


def _decrypt(key, blob):
    if not blob.startswith(MAGIC):
        raise ValueError("not a sealed blob")
    nonce, tag, ct = blob[4:20], blob[20:52], blob[52:]
    if not hmac.compare_digest(tag, hmac.new(key, nonce + ct, hashlib.sha256).digest()):
        raise ValueError("integrity check failed")
    return bytes(a ^ b for a, b in zip(ct, _keystream(key, nonce, len(ct))))
FLAG = os.path.join(VAULT, "CHEAT_FLAG")
STATE = os.path.join(VAULT, "guard_state.json")
SOURCES = []
# Only modules that carry game parameters get sealed. tm_watch_ai.py is pure UI
# (it talks to /state over HTTP and never imports the engine), so leaving it readable
# costs nothing and lets a second spectator process attach to a live match.
SOURCES += [os.path.join("src", n) for n in
            ("tm_engine.py", "tm_api.py", "scratchpad.py")]

DECOY = r'''# ==========================================================================
#  CHEATING DETECTED
# ==========================================================================
#  This file is a decoy. The real sources are sealed while a match is running.
#  Reading source code before or during a match is forbidden by docs/ai-protocol.md.
#
#  This match has been flagged. Stop reading the sources and play the game.
# ==========================================================================
import os as _os, sys as _sys

_flag = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "_guard_vault", "CHEAT_FLAG")
try:
    _d = _os.path.dirname(_flag)
    if not _os.path.isdir(_d):
        _os.makedirs(_d)
    with open(_flag, "w", encoding="utf-8") as _f:
        _f.write("source file executed during a live match\n")
except Exception:
    pass

print("CHEATING DETECTED: source access during a match is forbidden.", file=_sys.stderr)
_sys.exit(1)
'''


def _exists(p):
    return os.path.exists(os.path.join(HERE, p))


def _health(port, timeout=1.0):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _post(port, path, timeout=2.0):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception:
        return None


def seal(port=None):
    """Encrypt the sources into a vault outside the project, then drop decoys.

    ``port`` is recorded in the state file so a later process can tell whether the match that
    sealed these sources is still alive before it thinks about restoring them.

    Refuses when a previous vault is still on disk: sealing twice would encrypt the *decoys*
    into a new box and overwrite the state file, orphaning the real sources of the match that
    is still running. That box can only be opened by its own unseal().
    """
    if os.path.isfile(STATE):
        try:
            with io.open(STATE, encoding="utf-8") as f:
                prev = json.load(f) or {}
            prev_box = os.path.join(GUARD_ROOT, prev.get("box") or "")
            if prev.get("box") and os.path.isdir(prev_box):
                raise RuntimeError(
                    "sources are already sealed by a match that has not exited (box %s); "
                    "sealing again would orphan them" % prev.get("box"))
        except RuntimeError:
            raise
        except Exception:
            pass
    os.makedirs(VAULT, exist_ok=True)
    os.makedirs(GUARD_ROOT, exist_ok=True)
    session = os.urandom(8).hex()
    box = os.path.join(GUARD_ROOT, session)
    os.makedirs(box, exist_ok=True)
    key = os.urandom(32)
    with open(os.path.join(box, "_k"), "wb") as f:
        f.write(key)
    sealed, mapping = [], {}
    for rel in SOURCES:
        src = os.path.join(HERE, rel)
        if not os.path.isfile(src):
            continue
        with open(src, "rb") as f:
            data = f.read()
        name = os.urandom(8).hex() + ".bin"
        with open(os.path.join(box, name), "wb") as f:
            f.write(_encrypt(key, data))
        mapping[name] = rel
        with io.open(src, "w", encoding="utf-8", newline="\n") as f:
            f.write(DECOY)
        sealed.append(rel)
    state = {"sealed": sealed, "started": time.time(), "box": session, "map": mapping,
             "port": core_port(port)}
    with io.open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    return sealed


def unseal():
    """Decrypt the real sources back into place, then drop the vault flags."""
    out = []
    state = {}
    try:
        if os.path.isfile(STATE):
            with io.open(STATE, encoding="utf-8") as f:
                state = json.load(f) or {}
    except Exception:
        state = {}
    session = state.get("box")
    if session:
        box = os.path.join(GUARD_ROOT, session)
        keypath = os.path.join(box, "_k")
        if os.path.isfile(keypath):
            with open(keypath, "rb") as f:
                key = f.read()
            for name, rel in (state.get("map") or {}).items():
                p = os.path.join(box, name)
                if not os.path.isfile(p):
                    continue
                try:
                    with open(p, "rb") as f:
                        data = _decrypt(key, f.read())
                except Exception as exc:
                    print("  [GUARD] cannot restore %s: %s" % (rel, exc))
                    continue
                with open(os.path.join(HERE, rel), "wb") as f:
                    f.write(data)
                out.append(rel)
            shutil.rmtree(box, ignore_errors=True)
    # 向后兼容：旧版本把明文放在项目内的 _guard_vault/src__*.py
    for rel in SOURCES:
        if rel in out:
            continue
        legacy = os.path.join(VAULT, rel.replace(os.sep, "__"))
        if os.path.isfile(legacy):
            shutil.copy2(legacy, os.path.join(HERE, rel))
            os.remove(legacy)
            out.append(rel)
    try:
        if os.path.isfile(FLAG):
            os.remove(FLAG)
        if os.path.isfile(STATE):
            os.remove(STATE)
    except Exception:
        pass
    return out


def cmd_start(port):
    print("  Waiting for the match server on port %d ..." % port)
    for _ in range(120):
        if _health(port, 0.5):
            break
        time.sleep(0.25)
    else:
        print("  [GUARD] server never came up on port %d; nothing sealed." % port)
        return 2

    sealed = seal()
    print("  [GUARD] sealed %d source file(s); decoys are in place." % len(sealed))
    print("  [GUARD] watching for cheating and for the end of the match ...")

    try:
        while True:
            if os.path.isfile(FLAG):
                msg = io.open(FLAG, encoding="utf-8", errors="ignore").read().strip()
                print()
                print("  " + "=" * 58)
                print("  CHEATING DETECTED: %s" % msg)
                print("  The match is being terminated and flagged.")
                print("  " + "=" * 58)
                _post(port, "/shutdown")
                time.sleep(1.5)
                unseal()
                return 3
            h = _health(port, 0.5)
            if h is None:
                print("  [GUARD] server is gone; restoring sources.")
                unseal()
                return 0
            time.sleep(0.4)
    except KeyboardInterrupt:
        print("\n  [GUARD] interrupted; restoring sources.")
        unseal()
        return 0


def cmd_stop():
    restored = unseal()
    print("  [GUARD] restored %d file(s)." % len(restored))
    return 0


def cmd_status(port):
    sealed = os.path.isfile(STATE)
    print("  sealed:      %s" % ("yes" if sealed else "no"))
    print("  cheat flag:  %s" % ("PRESENT" if os.path.isfile(FLAG) else "none"))
    h = _health(port, 0.5)
    print("  server:      %s" % ("up" if h else "down"))
    if h:
        print("  tick:        %s" % h.get("tick"))
        print("  equity:      %s" % h.get("equity"))
    return 0


def cmd_clean():
    restored = unseal()
    try:
        if os.path.isdir(VAULT) and not os.listdir(VAULT):
            os.rmdir(VAULT)
    except Exception:
        pass
    print("  [GUARD] cleaned up, restored %d file(s)." % len(restored))
    return 0


def main(argv):
    argv = list(argv or sys.argv[1:])
    cmd = argv[0].lower() if argv else "status"
    port = 8734
    if "--port" in argv:
        try:
            port = int(argv[argv.index("--port") + 1])
        except Exception:
            pass
    if cmd == "start":
        return cmd_start(port)
    if cmd == "stop":
        return cmd_stop()
    if cmd == "status":
        return cmd_status(port)
    if cmd == "clean":
        return cmd_clean()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(None))

def core_port(port=None):
    """Normalise whatever we were handed into an int port, or None."""
    try:
        return int(port) if port else None
    except Exception:
        return None


def _alive(port, timeout=1.0):
    """Is a match still answering on this port?"""
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/health" % int(port), timeout=timeout).read()
        return True
    except Exception:
        return False


def restore_if_sealed(quiet=True):
    """If a previous match left the sources sealed, restore them now.

    Safe to call at any time: it does nothing when no vault exists, and does nothing while the
    match that sealed them is still answering on its port — that seal is live, and only that
    match's own exit path may lift it.
    """
    if not os.path.isdir(VAULT):
        return 0
    port = None
    try:
        if os.path.isfile(STATE):
            with io.open(STATE, encoding="utf-8") as f:
                port = (json.load(f) or {}).get("port")
    except Exception:
        port = None
    if port and _alive(port):
        return 0
    n = unseal()
    if n and not quiet:
        print("  [GUARD] previous match left the sources sealed; restored %d file(s)." % len(n))
    return len(n)

def cheated():
    """True when a decoy was executed during this match."""
    return os.path.isfile(FLAG)
