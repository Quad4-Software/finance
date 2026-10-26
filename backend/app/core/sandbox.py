"""Kernel-level self-sandboxing for the API and worker processes.

Two independent, best-effort layers:

- Landlock (filesystem): every filesystem access right the running kernel
  supports is handled (denied by default), then read access is granted back
  to the code and data the app legitimately needs, and read+write to the
  handful of directories it actually writes to. Network rights are NOT
  handled: a web app must keep serving TCP.
- seccomp-BPF (syscalls): a default-ALLOW filter with an errno denylist of
  syscalls a finance API never needs (mount, ptrace, kernel modules, key
  management, time setting, ...). Denied calls return EPERM rather than
  killing the process, so a missed edge case surfaces as an ordinary OSError
  instead of a fatal SIGSYS.

Nothing here raises: on a non-Linux platform, a kernel without the feature,
or any unexpected error, the failure is logged and startup continues. The
functions are invoked from process entrypoints only (FastAPI lifespan, the
Celery worker/beat init signals), never at import time, so test suites that
import app modules stay unrestricted.
"""

from __future__ import annotations

import errno
import logging
import os
import sys
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

_applied = False


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


# Syscalls denied with EPERM. The set is resolved by name against the running
# kernel's native syscall table, so entries absent on this architecture are
# simply skipped.
_DENIED_SYSCALLS: tuple[str, ...] = (
    # Mounts and filesystem namespaces
    "mount",
    "umount2",
    "move_mount",
    "open_tree",
    "fsopen",
    "fsmount",
    "fsconfig",
    "mount_setattr",
    "pivot_root",
    "chroot",
    "setns",
    "unshare",
    # Introspection and code injection into other processes
    "ptrace",
    "process_vm_readv",
    "process_vm_writev",
    "open_by_handle_at",
    "name_to_handle_at",
    "userfaultfd",
    # Kernel modules, kexec, BPF/perf
    "init_module",
    "finit_module",
    "delete_module",
    "create_module",
    "query_module",
    "get_kernel_syms",
    "kexec_load",
    "kexec_file_load",
    "bpf",
    "perf_event_open",
    # Kernel keyring
    "keyctl",
    "add_key",
    "request_key",
    # Privileged system control
    "acct",
    "swapon",
    "swapoff",
    "reboot",
    "settimeofday",
    "clock_settime",
    "adjtimex",
    "stime",
    "sethostname",
    "setdomainname",
    "ioperm",
    "iopl",
    "mknod",
    "mknodat",
    "quotactl",
    "quotactl_fd",
    "nfsservctl",
    "uselib",
    "ustat",
    "sysfs",
    "_sysctl",
    "vserver",
    # Architecture-specific legacy calls
    "vm86",
    "vm86old",
    "modify_ldt",
    "subpage_prot",
    "switch_endian",
    "cacheflush",
)


def _existing(paths: Iterable[Path]) -> list[Path]:
    """Keep only paths that exist (allow_path fails on missing ones)."""
    out: list[Path] = []
    for p in paths:
        try:
            if p.exists():
                out.append(p)
        except OSError:
            continue
    return out


def _read_paths() -> list[Path]:
    """Everything the process legitimately reads at runtime."""
    from app.core.config import CREDENTIALS_DIRECTORY

    paths: list[Path] = [
        # The application itself (source, alembic, bundled data files).
        Path(__file__).resolve().parents[2],
        Path("/etc"),
        Path("/usr"),
        Path("/bin"),
        Path("/sbin"),
        Path("/lib"),
        Path("/lib64"),
        Path("/proc"),
        Path("/sys"),
        # Device nodes cannot carry per-file rules (allow_path EINVALs on
        # them), so the directory must be granted as a whole. Read is what
        # /dev/urandom and friends need.
        Path("/dev"),
        # Docker secrets and systemd-style credential directories. These are
        # read-only mounts in practice, so read access suffices.
        Path("/run/secrets"),
        *CREDENTIALS_DIRECTORY,
    ]
    # Interpreter and every import root (venvs, site-packages, PYTHONPATH).
    for attr in ("prefix", "base_prefix", "exec_prefix", "base_exec_prefix"):
        value = getattr(sys, attr, "")
        if value:
            paths.append(Path(value))
    for entry in sys.path:
        if entry:
            paths.append(Path(entry))
    return paths


def _write_paths() -> list[Path]:
    """Directories the app writes to. Created when missing so the rule can
    be added (allow_path requires an existing path)."""
    from app.core.config import get_settings

    settings = get_settings()
    paths = [
        Path(settings.storage_local_path),
        Path(settings.backup_local_path),
        # cwd: celerybeat-schedule and a writable .env both live here.
        Path.cwd(),
        Path("/tmp"),
        # Covers /dev/null and the terminals; DAC permissions still apply.
        Path("/dev"),
    ]
    # Optional agents module: knowledge uploads and the downloaded embedding
    # model. Resolved lazily so a broken agents config can't break sandboxing.
    try:
        from app.agents.config import get_agent_settings

        agent = get_agent_settings()
        paths.append(Path(agent.knowledge_storage_path))
        paths.append(Path(agent.embedding_native_cache_dir))
    except Exception:
        logger.debug("Agents storage paths unavailable; skipping", exc_info=True)
    for p in paths:
        try:
            if not p.exists():
                p.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.debug("Cannot create writable path %s; skipping", p)
    return paths


def apply_landlock() -> bool:
    """Restrict filesystem access to the paths this app needs. Best effort."""
    if not _is_linux():
        logger.info("Landlock: skipped (non-Linux platform %s)", sys.platform)
        return False
    try:
        import landlockpy
        from landlockpy import AccessFS, AccessNet, RestrictFlag, Ruleset
    except ImportError:
        logger.warning("Landlock: landlockpy is not installed; skipping")
        return False

    try:
        abi = landlockpy.abi_version()
        if abi < 1:
            logger.info("Landlock: not supported by this kernel; skipping")
            return False

        read_rights = AccessFS.READ_FILE | AccessFS.READ_DIR | AccessFS.EXECUTE
        with Ruleset(handled_net=AccessNet.NONE, best_effort=True) as ruleset:
            granted_paths = 0
            for path in _existing(_read_paths()):
                try:
                    if ruleset.allow_path(path, read_rights):
                        granted_paths += 1
                except OSError as exc:
                    logger.debug("Landlock: cannot grant read on %s: %s", path, exc)
            write_rights = ruleset.handled_fs
            for path in _existing(_write_paths()):
                try:
                    if ruleset.allow_path(path, write_rights):
                        granted_paths += 1
                except OSError as exc:
                    logger.debug("Landlock: cannot grant write on %s: %s", path, exc)
            try:
                # TSYNC applies the domain to every thread in the process, not
                # just the caller. Older kernels lack it; best_effort mode in
                # landlockpy drops the flag instead of failing.
                ruleset.restrict(RestrictFlag.TSYNC)
            except landlockpy.LandlockError:
                ruleset.restrict(RestrictFlag.NONE)
        logger.info("Landlock: enforced (ABI v%d, %d path rules granted)", abi, granted_paths)
        return True
    except Exception:
        logger.warning("Landlock: failed to apply; continuing unsandboxed", exc_info=True)
        return False


def apply_seccomp() -> bool:
    """Install an errno-denylist syscall filter. Best effort."""
    if not _is_linux():
        logger.info("Seccomp: skipped (non-Linux platform %s)", sys.platform)
        return False
    try:
        import seccompy
        from seccompy import Action, Filter, FilterFlag
    except ImportError:
        logger.warning("Seccomp: seccompy is not installed; skipping")
        return False

    try:
        if not seccompy.supported():
            logger.info("Seccomp: not supported by this kernel; skipping")
            return False

        flags = FilterFlag.NONE
        if seccompy.flag_supported(FilterFlag.TSYNC):
            flags |= FilterFlag.TSYNC
            if seccompy.flag_supported(FilterFlag.TSYNC_ESRCH):
                flags |= FilterFlag.TSYNC_ESRCH

        filt = Filter(default=Action.ALLOW, flags=flags)
        denied = 0
        for name in _DENIED_SYSCALLS:
            try:
                filt.errno(name, errno.EPERM)
                denied += 1
            except ValueError:
                # Name unknown on this architecture's syscall table.
                continue
        filt.load()
        logger.info("Seccomp: enforced (%d syscalls denied with EPERM)", denied)
        return True
    except Exception:
        logger.warning("Seccomp: failed to apply; continuing unsandboxed", exc_info=True)
        return False


def apply_sandbox() -> None:
    """Apply every enabled sandbox layer. Safe to call more than once."""
    global _applied
    if _applied:
        return
    _applied = True

    try:
        from app.core.config import get_settings

        settings = get_settings()
    except Exception:
        logger.warning("Sandbox: settings unavailable; skipping", exc_info=True)
        return

    if not settings.sandbox_enabled:
        logger.info("Sandbox: disabled by SANDBOX_ENABLED")
        return
    # Explicit escape hatch for environments where sandboxing is actively
    # harmful (debuggers, some PaaS runtimes).
    if os.environ.get("QUAD4_NO_SANDBOX", "").strip().lower() in ("1", "true", "yes", "on"):
        logger.info("Sandbox: disabled by QUAD4_NO_SANDBOX")
        return

    if settings.sandbox_landlock_enabled:
        apply_landlock()
    if settings.sandbox_seccomp_enabled:
        apply_seccomp()
