#!/usr/bin/env python3
"""
Command-line helper for WCH CH32V MounRiver Studio projects.

First goal: make build/inspection reproducible outside the IDE so an AI agent
can safely call one tool instead of guessing MounRiver internals.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import hashlib
import subprocess as subprocess_module
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


CONFIG_FILE_NAME = ".wch_mrs_tool.json"
ENV_MRS_KEYS = ("WCH_MRS_ROOT", "MOUNRIVER_STUDIO_ROOT", "MOUNRIVER_HOME", "MRS_ROOT")


@dataclass
class ToolPaths:
    mrs_root: str | None = None
    make: str | None = None
    gcc: str | None = None
    objcopy: str | None = None
    size: str | None = None
    openocd: str | None = None
    eclipse: str | None = None
    eclipsec: str | None = None
    wch_link_utility: str | None = None


@dataclass
class ProjectInfo:
    project: str
    exists: bool
    name: str | None = None
    configs: list[str] | None = None
    makefiles: list[str] | None = None
    elf_files: list[str] | None = None
    hex_files: list[str] | None = None
    bin_files: list[str] | None = None
    linker_scripts: list[str] | None = None
    startup_files: list[str] | None = None
    likely_chip: str | None = None


class ToolError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def user_config_path() -> Path:
    return Path.home() / CONFIG_FILE_NAME


def workspace_config_path(project: Path | None) -> Path:
    base = project if project else Path.cwd()
    if base.is_file():
        base = base.parent
    return base / CONFIG_FILE_NAME


def load_config(config_file: Path | None, cli_project: Path | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in (user_config_path(), Path.cwd() / CONFIG_FILE_NAME):
        merged.update(read_json(path))
    if cli_project:
        merged.update(read_json(workspace_config_path(cli_project)))
    if config_file:
        merged.update(read_json(config_file))
    return merged


def resolve_project(args: argparse.Namespace, config: dict[str, Any]) -> Path:
    value = args.project or config.get("project") or config.get("workspace_root")
    return Path(value).expanduser().resolve() if value else Path.cwd().resolve()


def candidate_mrs_roots(explicit: Path | None, config: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    configured = explicit or config.get("mrs_root") or config.get("mounriver_root")
    if configured:
        candidates.append(Path(configured).expanduser())

    for key in ENV_MRS_KEYS:
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]).expanduser())

    if os.name == "nt":
        drives = [Path(f"{letter}:\\") for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ"]
        for drive in drives:
            candidates.extend(
                [
                    drive / "MounRiver_Studio",
                    drive / "MounRiver" / "MounRiver_Studio",
                    drive / "WCH" / "MounRiver_Studio",
                ]
            )
        for env_key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env_key)
            if base:
                candidates.extend(
                    [
                        Path(base) / "MounRiver_Studio",
                        Path(base) / "MounRiver" / "MounRiver_Studio",
                        Path(base) / "WCH" / "MounRiver_Studio",
                    ]
                )
    else:
        candidates.extend(
            [
                Path("/opt/MounRiver_Studio"),
                Path("/opt/mounriver"),
                Path.home() / "MounRiver_Studio",
            ]
        )

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def path_or_none(value: Path | None) -> str | None:
    return str(value) if value else None


def find_first(root: Path, names: list[str]) -> Path | None:
    if not root.exists():
        return None
    lowered = {name.lower() for name in names}
    for path in root.rglob("*"):
        if path.is_file() and path.name.lower() in lowered:
            return path
    return None


def find_exe(root: Path, exe_name: str) -> Path | None:
    if not root.exists():
        return None
    for path in root.rglob(exe_name):
        if path.is_file():
            return path
    return None


def detect_tools(mrs_roots: list[Path]) -> ToolPaths:
    tools = ToolPaths()

    search_roots = [root for root in mrs_roots if root.exists()]
    if search_roots:
        tools.mrs_root = str(search_roots[0])

    for root in search_roots:
        tools.make = tools.make or path_or_none(find_exe(root, "make.exe"))
        tools.gcc = tools.gcc or path_or_none(find_exe(root, "riscv-none-embed-gcc.exe"))
        tools.objcopy = tools.objcopy or path_or_none(find_exe(root, "riscv-none-embed-objcopy.exe"))
        tools.size = tools.size or path_or_none(find_exe(root, "riscv-none-embed-size.exe"))
        tools.openocd = tools.openocd or path_or_none(find_exe(root, "openocd.exe"))
        tools.eclipsec = tools.eclipsec or path_or_none(find_exe(root, "eclipsec.exe"))
        tools.wch_link_utility = tools.wch_link_utility or path_or_none(find_exe(root, "WCH-LinkUtility.exe"))
        tools.eclipse = tools.eclipse or path_or_none(find_first(root, ["MounRiver Studio.exe", "eclipse.exe"]))

    tools.make = tools.make or shutil.which("make") or shutil.which("mingw32-make")
    tools.gcc = tools.gcc or shutil.which("riscv-none-embed-gcc")
    tools.objcopy = tools.objcopy or shutil.which("riscv-none-embed-objcopy")
    tools.size = tools.size or shutil.which("riscv-none-embed-size")
    tools.openocd = tools.openocd or shutil.which("openocd")

    return tools


def parse_project_name(project_file: Path) -> str | None:
    try:
        root = ElementTree.parse(project_file).getroot()
        name = root.findtext("name")
        return name.strip() if name else None
    except Exception:
        return None


def parse_configs(cproject_file: Path) -> list[str]:
    try:
        text = cproject_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    configs = []
    for match in re.finditer(r'<configuration\b[^>]*\bname="([^"]+)"', text):
        if match.group(1) not in configs:
            configs.append(match.group(1))
    return configs


def project_name(project: Path) -> str:
    project_file = project / ".project"
    if project_file.exists():
        name = parse_project_name(project_file)
        if name:
            return name
    return project.name


def rels(project: Path, paths: list[Path]) -> list[str]:
    result = []
    for path in paths:
        try:
            result.append(str(path.relative_to(project)))
        except ValueError:
            result.append(str(path))
    return sorted(result)


def infer_chip(project: Path) -> str | None:
    candidates = []
    for pattern in ("*.h", "*.c", "*.ld", "*.s", "*.S", "*.mk", "Makefile"):
        candidates.extend(project.rglob(pattern))
    chip_re = re.compile(r"\bCH32[VXFL]\d{3}[A-Z0-9]*\b", re.IGNORECASE)
    found: dict[str, int] = {}
    for path in candidates[:2000]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in chip_re.findall(text):
            key = match.upper()
            found[key] = found.get(key, 0) + 1
    if not found:
        return None
    return sorted(found.items(), key=lambda item: item[1], reverse=True)[0][0]


def inspect_project(project: Path) -> ProjectInfo:
    info = ProjectInfo(project=str(project), exists=project.exists(), configs=[])
    if not project.exists():
        return info

    project_file = project / ".project"
    cproject_file = project / ".cproject"
    info.name = parse_project_name(project_file) if project_file.exists() else project.name
    info.configs = parse_configs(cproject_file) if cproject_file.exists() else []
    info.makefiles = rels(project, [p for p in project.rglob("Makefile") if p.is_file()])
    info.elf_files = rels(project, [p for p in project.rglob("*.elf") if p.is_file()])
    info.hex_files = rels(project, [p for p in project.rglob("*.hex") if p.is_file()])
    info.bin_files = rels(project, [p for p in project.rglob("*.bin") if p.is_file()])
    info.linker_scripts = rels(project, [p for p in project.rglob("*.ld") if p.is_file()])
    info.startup_files = rels(project, [p for p in project.rglob("*startup*") if p.is_file()])
    info.likely_chip = infer_chip(project)
    return info


def pick_make_dir(project: Path, config: str | None) -> Path | None:
    candidates = []
    if config:
        candidates.extend([project / config, project / config.capitalize(), project / config.lower()])
    candidates.extend([project / "Debug", project / "Release", project])
    for candidate in candidates:
        if (candidate / "Makefile").exists():
            return candidate
    makefiles = [p.parent for p in project.rglob("Makefile")]
    return makefiles[0] if makefiles else None


def tool_env(tools: ToolPaths) -> dict[str, str]:
    env = os.environ.copy()
    path_parts = []
    for value in (tools.make, tools.gcc, tools.objcopy, tools.size, tools.openocd):
        if value:
            parent = str(Path(value).parent)
            if parent not in path_parts:
                path_parts.append(parent)
    if path_parts:
        env["PATH"] = os.pathsep.join(path_parts + [env.get("PATH", "")])
    return env


def run_command(args: list[str], cwd: Path, dry_run: bool = False, env: dict[str, str] | None = None) -> int:
    print(f"[cwd] {cwd}")
    print("[cmd] " + " ".join(quote_arg(arg) for arg in args))
    if dry_run:
        return 0
    proc = subprocess.run(args, cwd=str(cwd), text=True, env=env)
    return proc.returncode


def default_headless_workspace(project: Path) -> Path:
    digest = hashlib.sha1(str(project).encode("utf-8", errors="ignore")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"wch-mrs-workspace-{digest}"


def quote_arg(value: str) -> str:
    return subprocess_module.list2cmdline([value])


def command_doctor(args: argparse.Namespace) -> int:
    tools = detect_tools(args.mrs_roots)
    result: dict[str, Any] = {
        "status": "success" if tools.make and tools.gcc else "blocked",
        "project_profile": {
            "workspace_root": str(args.project),
            "workspace_os": sys.platform,
            "build_system": "mounriver-make",
            "toolchain": "wch-riscv-gcc" if tools.gcc else None,
        },
        "tools": asdict(tools),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("WCH MounRiver toolchain check")
        for key, value in asdict(tools).items():
            print(f"  {key:8}: {value or 'NOT FOUND'}")
    missing = [key for key in ("make", "gcc") if getattr(tools, key) is None]
    if missing:
        print("Missing required build tools: " + ", ".join(missing), file=sys.stderr)
        return 2
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    info = inspect_project(args.project)
    if args.json:
        result = {
            "status": "success" if info.exists else "blocked",
            "project_profile": {
                "workspace_root": str(args.project),
                "workspace_os": sys.platform,
                "build_system": "mounriver-make",
                "toolchain": "wch-riscv-gcc",
                "target_mcu": info.likely_chip,
                "artifact_path": (str(args.project / info.elf_files[0]) if info.elf_files else None),
                "artifact_kind": ("elf" if info.elf_files else None),
            },
            "project": asdict(info),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Project: {info.project}")
        print(f"Exists : {info.exists}")
        print(f"Name   : {info.name or 'UNKNOWN'}")
        print(f"Chip   : {info.likely_chip or 'UNKNOWN'}")
        print(f"Configs: {', '.join(info.configs or []) or 'UNKNOWN'}")
        print(f"Makefiles: {', '.join(info.makefiles or []) or 'NONE'}")
        print(f"ELF    : {', '.join(info.elf_files or []) or 'NONE'}")
        print(f"HEX    : {', '.join(info.hex_files or []) or 'NONE'}")
        print(f"BIN    : {', '.join(info.bin_files or []) or 'NONE'}")
        print(f"LD     : {', '.join(info.linker_scripts or []) or 'NONE'}")
    return 0 if info.exists else 2


def command_build(args: argparse.Namespace) -> int:
    project = args.project
    if not project.exists():
        raise ToolError(f"project path does not exist: {project}")

    tools = detect_tools(args.mrs_roots)
    backend = args.backend
    if backend == "auto":
        backend = "headless" if tools.eclipsec else "make"

    if backend == "headless":
        if not tools.eclipsec:
            raise ToolError("eclipsec.exe not found. Use --backend make or check --mrs path.")
        name = project_name(project)
        config = args.config or "obj"
        workspace = args.workspace or default_headless_workspace(project)
        action = "-cleanBuild" if args.clean_first else "-build"
        cmd = [
            tools.eclipsec,
            "-nosplash",
            "-data",
            str(workspace),
            "-application",
            "org.eclipse.cdt.managedbuilder.core.headlessbuild",
            "-import",
            str(project),
            action,
            f"{name}/{config}",
        ]
        cwd = Path(tools.mrs_root) if tools.mrs_root else project
        return run_command(cmd, cwd, dry_run=args.dry_run, env=tool_env(tools))

    if not tools.make:
        raise ToolError("make.exe not found. Run doctor and check --mrs path.")

    make_dir = pick_make_dir(project, args.config)
    if not make_dir:
        raise ToolError("no Makefile found. The project may need MounRiver headless build support.")

    cmd = [tools.make]
    if args.jobs:
        cmd.append(f"-j{args.jobs}")
    if args.target:
        cmd.append(args.target)

    return run_command(cmd, make_dir, dry_run=args.dry_run, env=tool_env(tools))


def command_rebuild(args: argparse.Namespace) -> int:
    args.clean_first = True
    return command_build(args)


def command_clean(args: argparse.Namespace) -> int:
    project = args.project
    tools = detect_tools(args.mrs_roots)
    backend = args.backend
    if backend == "auto":
        backend = "headless" if tools.eclipsec else "make"

    if backend == "headless":
        if not tools.eclipsec:
            raise ToolError("eclipsec.exe not found. Use --backend make or check --mrs path.")
        name = project_name(project)
        config = args.config or "obj"
        workspace = args.workspace or default_headless_workspace(project)
        cmd = [
            tools.eclipsec,
            "-nosplash",
            "-data",
            str(workspace),
            "-application",
            "org.eclipse.cdt.managedbuilder.core.headlessbuild",
            "-import",
            str(project),
            "-cleanBuild",
            f"{name}/{config}",
        ]
        cwd = Path(tools.mrs_root) if tools.mrs_root else project
        return run_command(cmd, cwd, dry_run=args.dry_run, env=tool_env(tools))

    args.target = "clean"
    return command_build(args)


def command_config_example(args: argparse.Namespace) -> int:
    example = {
        "mrs_root": r"C:\MounRiver_Studio",
        "project": r"D:\path\to\your\mounriver-project",
    }
    if args.no_project:
        example.pop("project")
    print(json.dumps(example, ensure_ascii=False, indent=2))
    return 0


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def find_artifact(project: Path, kind: str, explicit: Path | None = None) -> Path | None:
    if explicit:
        return explicit.resolve()
    patterns = {
        "elf": ["*.elf"],
        "hex": ["*.hex"],
        "bin": ["*.bin"],
        "auto": ["*.elf", "*.hex", "*.bin"],
    }[kind]
    preferred_dirs = [project / "obj", project / "Debug", project / "Release", project]
    candidates: list[Path] = []
    for directory in preferred_dirs:
        if directory.exists():
            for pattern in patterns:
                candidates.extend(directory.glob(pattern))
    if not candidates:
        for pattern in patterns:
            candidates.extend(project.rglob(pattern))
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def openocd_wch_cfg(tools: ToolPaths, explicit: Path | None = None) -> Path | None:
    if explicit:
        return explicit.resolve()
    if not tools.openocd:
        return None
    openocd = Path(tools.openocd)
    candidates = [
        openocd.parent / "wch-riscv.cfg",
        openocd.parent.parent / "scripts" / "wch" / "wch-riscv.cfg",
        openocd.parent.parent / "scripts" / "board" / "wch-riscv.cfg",
        openocd.parent.parent / "share" / "openocd" / "scripts" / "wch" / "wch-riscv.cfg",
    ]
    return first_existing(candidates)


def command_flash(args: argparse.Namespace) -> int:
    project = args.project
    tools = detect_tools(args.mrs_roots)
    if not tools.openocd:
        raise ToolError("openocd.exe not found. Run doctor and check --mrs path.")

    artifact = find_artifact(project, args.format, args.file)
    if not artifact:
        raise ToolError("no flash artifact found. Build first or pass --file path.")
    if not artifact.exists():
        raise ToolError(f"artifact does not exist: {artifact}")

    cfg = openocd_wch_cfg(tools, args.cfg)
    if not cfg:
        raise ToolError("wch-riscv.cfg not found. Pass --cfg explicitly.")

    program_cmd = f'program "{artifact}" verify reset exit'
    if args.no_verify:
        program_cmd = f'program "{artifact}" reset exit'

    cmd = [
        tools.openocd,
        "-f",
        str(cfg),
        "-c",
        "init",
        "-c",
        "halt",
        "-c",
        program_cmd,
    ]
    cwd = Path(tools.openocd).parent
    return run_command(cmd, cwd, dry_run=args.dry_run, env=tool_env(tools))


def add_build_like_parser(sub: argparse._SubParsersAction, name: str, help_text: str, func: Any) -> None:
    cmd = sub.add_parser(name, help=help_text)
    cmd.add_argument("--config", default="obj", help="MounRiver build config name or make config directory (default: obj)")
    cmd.add_argument("--backend", choices=("auto", "headless", "make"), default="auto", help="build backend (default: auto)")
    cmd.add_argument("--workspace", type=Path, default=None, help="Eclipse workspace for headless builds")
    cmd.add_argument("--clean-first", action="store_true", help="use MounRiver headless cleanBuild instead of incremental build")
    cmd.add_argument("--jobs", type=int, default=os.cpu_count() or 4, help="parallel build jobs")
    cmd.add_argument("--target", default="all", help="make target (default: all)")
    cmd.add_argument("--dry-run", action="store_true", help="print command without running it")
    cmd.set_defaults(func=func)


def add_flash_like_parser(sub: argparse._SubParsersAction, name: str, help_text: str) -> None:
    cmd = sub.add_parser(name, help=help_text)
    cmd.add_argument("--file", type=Path, default=None, help="artifact to flash/download (default: newest obj/*.elf/*.hex/*.bin)")
    cmd.add_argument("--format", choices=("auto", "elf", "hex", "bin"), default="auto", help="artifact kind to auto-select")
    cmd.add_argument("--cfg", type=Path, default=None, help="OpenOCD cfg file (default: MounRiver wch-riscv.cfg)")
    cmd.add_argument("--no-verify", action="store_true", help="skip OpenOCD verify step")
    cmd.add_argument("--dry-run", action="store_true", help="print OpenOCD command without connecting to hardware")
    cmd.set_defaults(func=command_flash)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wch_mrs_tool",
        description="Build helper for WCH CH32V MounRiver Studio projects.",
    )
    parser.add_argument("--project", type=Path, default=None, help="project path (default: current directory or config)")
    parser.add_argument("--mrs", type=Path, default=None, help="MounRiver Studio root (default: config/env/common install paths/PATH)")
    parser.add_argument("--config-file", type=Path, default=None, help=f"optional JSON config file (default search includes {CONFIG_FILE_NAME})")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON where supported")

    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="check MounRiver/GCC/make tool paths")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    doctor.set_defaults(func=command_doctor)

    inspect = sub.add_parser("inspect", help="inspect project files and build outputs")
    inspect.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    inspect.set_defaults(func=command_inspect)

    add_build_like_parser(sub, "build", "build the project using MounRiver headless build or make", command_build)
    add_build_like_parser(sub, "make", "alias for build; familiar for make-based projects", command_build)
    add_build_like_parser(sub, "rebuild", "clean and build using the native backend", command_rebuild)
    add_build_like_parser(sub, "remake", "alias for rebuild; clean and build again", command_rebuild)

    clean = sub.add_parser("clean", help="clean the selected config")
    clean.add_argument("--config", default="obj", help="MounRiver build config name or make config directory (default: obj)")
    clean.add_argument("--backend", choices=("auto", "headless", "make"), default="auto", help="clean backend (default: auto)")
    clean.add_argument("--workspace", type=Path, default=None, help="Eclipse workspace for headless cleans")
    clean.add_argument("--jobs", type=int, default=None, help="parallel clean jobs")
    clean.add_argument("--dry-run", action="store_true", help="print command without running it")
    clean.set_defaults(func=command_clean)

    config_example = sub.add_parser("config-example", help=f"print an example {CONFIG_FILE_NAME} file")
    config_example.add_argument("--no-project", action="store_true", help="omit the project field")
    config_example.set_defaults(func=command_config_example)

    add_flash_like_parser(sub, "flash", "flash ELF/HEX/BIN through WCH OpenOCD")
    add_flash_like_parser(sub, "download", "alias for flash; download firmware to the target")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config_file, args.project)
    args.project = resolve_project(args, config)
    args.mrs_roots = candidate_mrs_roots(args.mrs, config)
    try:
        return args.func(args)
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
