"""
Running GeoLibre tools (TM05-141).

geolibre-wasm runs `geolibre-cli.wasm` in-process through wasmtime. This module runs it
the same way, with a sandboxed `/work` directory and the CLI's argv, and adds three
things the pipeline needs:

- **A checked runtime.** The WASM is fetched once from the pinned release, outside the
  repository, and checked against tools.yml's sha256. The package's own first-use
  download skips that check.
- **A compiled-module cache.** Compiling the 24 MB module takes about 3 s and 870 MB.
  A serialised copy beside it loads in 10 ms, so each worker process pays nothing.
- **Peak memory per call.** WASM linear memory only grows, so its size after a call is
  that call's peak. The pipeline reports it per tool.

`run()` takes and returns file bytes, like geolibre_wasm.run_tool. Tools only ever see
`/work`.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

import wasmtime

WASMTIME_VERSION = metadata.version("wasmtime")

_engine: wasmtime.Engine | None = None
_modules: dict[str, wasmtime.Module] = {}


class ToolFailed(RuntimeError):
    """A GeoLibre tool exited non-zero or trapped; the message carries its last output."""


@dataclass
class Result:
    files: dict[str, bytes]
    log: list[str]
    #: WASM linear memory after the call, which is its peak, in bytes.
    peak_memory: int


def cache_dir() -> Path:
    """Where the runtime, DEM tiles and mosaics live: outside git (TERRAIN_CACHE_DIR)."""
    default = Path.home() / ".cache" / "campsite" / "terrain"
    return Path(os.environ.get("TERRAIN_CACHE_DIR") or default)


def runtime_path(runtime: dict[str, str]) -> Path:
    """The checked WASM runtime, fetched on first use. GEOLIBRE_WASM overrides the
    location, and is checked against the same sha256."""
    override = os.environ.get("GEOLIBRE_WASM")
    path = Path(override) if override else cache_dir() / "geolibre" / Path(runtime["url"]).name
    if not path.exists():
        if override:
            raise FileNotFoundError(f"GEOLIBRE_WASM={override} does not exist")
        path.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(runtime["url"], headers={"User-Agent": "campsite"})
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
            data = response.read()
        partial = path.with_suffix(".part")
        partial.write_bytes(data)
        partial.replace(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != runtime["sha256"]:
        raise RuntimeError(
            f"{path} has sha256 {digest}, expected {runtime['sha256']} (tools.yml runtime)"
        )
    return path


def prepare(path: Path) -> None:
    """Compile (or load) the module once, so worker processes start from the cache."""
    _module(path)


def _module(path: Path) -> wasmtime.Module:
    global _engine
    key = str(path)
    if key in _modules:
        return _modules[key]
    if _engine is None:
        _engine = wasmtime.Engine()
    # The compiled form is tied to this wasmtime version, so its name says which.
    compiled = path.with_name(f"{path.name}.wasmtime-{WASMTIME_VERSION}.cwasm")
    if compiled.exists():
        module = wasmtime.Module.deserialize_file(_engine, str(compiled))
    else:
        module = wasmtime.Module.from_file(_engine, str(path))
        partial = compiled.with_name(f"{compiled.name}.{os.getpid()}.part")
        partial.write_bytes(module.serialize())
        partial.replace(compiled)
    _modules[key] = module
    return module


def run(wasm: Path, tool: str, args: dict, inputs: dict[str, bytes]) -> Result:
    """Run one tool. `inputs` are written to /work under their names; `args` are passed
    as `--key=value`, so a file argument is spelt `/work/<name>`. New files come back by
    name."""
    module = _module(wasm)
    work = Path(tempfile.mkdtemp(prefix="terrain-"))
    try:
        for name, data in inputs.items():
            (work / name).write_bytes(data)
        argv = ["geolibre", tool]
        for key, value in args.items():
            if isinstance(value, bool):
                value = "true" if value else "false"
            argv.append(f"--{key}={value}")
        log_file = work / ".log"
        store = wasmtime.Store(_engine)
        wasi = wasmtime.WasiConfig()
        wasi.argv = argv
        wasi.preopen_dir(str(work), "/work")
        wasi.stdout_file = str(log_file)
        wasi.stderr_file = str(log_file)
        store.set_wasi(wasi)
        linker = wasmtime.Linker(_engine)
        linker.define_wasi()
        instance = linker.instantiate(store, module)
        code = 0
        try:
            instance.exports(store)["_start"](store)
        except wasmtime.ExitTrap as exit_trap:
            code = exit_trap.code
        except wasmtime.Trap as trap:
            code = -1
            earlier = log_file.read_text() if log_file.exists() else ""
            log_file.write_text(f"{earlier}\n{trap}")
        memory = instance.exports(store)["memory"].data_len(store)
        log = log_file.read_text(errors="replace").splitlines() if log_file.exists() else []
        if code != 0:
            tail = " | ".join(line for line in log[-4:] if line.strip())
            raise ToolFailed(f"{tool} exited {code}: {tail}")
        files = {
            path.name: path.read_bytes()
            for path in work.iterdir()
            if path.is_file() and path.name not in inputs and path.name != ".log"
        }
        return Result(files=files, log=log, peak_memory=memory)
    finally:
        shutil.rmtree(work, ignore_errors=True)
