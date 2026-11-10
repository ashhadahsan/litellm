from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from types import MappingProxyType
from typing import Final, TypeAlias

from pydantic import TypeAdapter
from typing_extensions import assert_never

SUPERVISED_ENV: Final = "_LITELLM_GATEWAY_SUPERVISED"
RUST_HOP: Final = "127.0.0.1"


class Mode(Enum):
    DISABLED = auto()


@dataclass(frozen=True, slots=True)
class InheritedFd:
    fd: int


@dataclass(frozen=True, slots=True)
class AssignedPort:
    port: int


ChildListener: TypeAlias = InheritedFd | AssignedPort


@dataclass(frozen=True, slots=True)
class Supervised:
    listener: ChildListener
    trusted_proxies: str


RustForwardMode: TypeAlias = Mode | Supervised
_SUPERVISED: Final = TypeAdapter(Supervised)


def supervised_environment(supervised: Supervised) -> Mapping[str, str]:
    return MappingProxyType({SUPERVISED_ENV: _SUPERVISED.dump_json(supervised).decode()})


def rust_forward_mode(environ: Mapping[str, str]) -> RustForwardMode:
    supervised: Final = environ.get(SUPERVISED_ENV)
    if supervised is not None:
        return _SUPERVISED.validate_json(supervised)
    return Mode.DISABLED


# A supervised server's TCP peer is always Rust on loopback, so server-level proxy headers would trust any
# client's forwarding headers. They stay off there and ``peer.wrap`` applies the operator's trust instead.


def _uvicorn_listener(listener: ChildListener) -> Mapping[str, object]:
    match listener:
        case InheritedFd(fd):
            return MappingProxyType({"fd": fd})
        case AssignedPort(port):
            return MappingProxyType({"host": RUST_HOP, "port": port})
        case _:
            assert_never(listener)


def uvicorn_options(mode: RustForwardMode, factory: str) -> Mapping[str, object]:
    match mode:
        case Supervised(listener):
            return MappingProxyType(
                {"app": factory, "factory": True, **_uvicorn_listener(listener), "proxy_headers": False}
            )
        case Mode.DISABLED:
            return MappingProxyType({})
        case _:
            assert_never(mode)


def _uvicorn_listener_flags(listener: ChildListener) -> tuple[str, ...]:
    match listener:
        case InheritedFd(fd):
            return ("--fd", str(fd))
        case AssignedPort(port):
            return ("--host", RUST_HOP, "--port", str(port))
        case _:
            assert_never(listener)


def uvicorn_flags(mode: RustForwardMode) -> tuple[str, ...]:
    match mode:
        case Supervised(listener):
            return (*_uvicorn_listener_flags(listener), "--no-proxy-headers")
        case Mode.DISABLED:
            return ()
        case _:
            assert_never(mode)


def _gunicorn_listener(listener: ChildListener) -> str:
    match listener:
        case InheritedFd(fd):
            return f"fd://{fd}"
        case AssignedPort(port):
            return f"{RUST_HOP}:{port}"
        case _:
            assert_never(listener)


def gunicorn_bind(mode: RustForwardMode, public: str) -> str:
    match mode:
        case Supervised(listener):
            return _gunicorn_listener(listener)
        case Mode.DISABLED:
            return public
        case _:
            assert_never(mode)


def server_proxy_headers(mode: RustForwardMode) -> bool:
    match mode:
        case Supervised():
            return False
        case Mode.DISABLED:
            return True
        case _:
            assert_never(mode)
