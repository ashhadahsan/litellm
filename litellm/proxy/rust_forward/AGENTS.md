# Rust forwarding, Python half

A supervisor runs the Rust gateway on the public port and Python on a private loopback listener. Rust forwards every request to Python unchanged, so Python still serves every route. This package is the Python half of forwarding and pairs with the crate `litellm-rust/crates/gateway-forward`. Once Rust serves every route, both get deleted together

Only the supervised child's side exists so far. Nothing sets `_LITELLM_GATEWAY_SUPERVISED` yet, so every function here is an identity until the supervisor lands

## Boundary

A supervised Python server differs from Python alone in exactly two ways, and nothing else in the proxy may change because Rust is in front

- It listens on the private loopback listener the supervisor gives it, never on the public address
- It restores the client address Rust saw, because its own TCP peer is always Rust

`proxy_server.py`, routes, auth and middleware never know Rust is there. A change that needs one of them to branch on forwarding is in the wrong place

## Modules

- `mode.py` is the Python child's side. `Supervised` is the whole contract the supervisor hands the child, and the `uvicorn_*` and `gunicorn_*` functions translate it into each server's own options
- `peer.py` restores the client address

## Entry points

Entry points (`litellm/proxy/proxy_cli.py`, `gateway/launch.py`, `litellm_cli/main.py`) only translate between their own flags and this package

- In the supervised child they merge `mode.uvicorn_options`, `mode.uvicorn_flags` or `mode.gunicorn_bind` and `mode.server_proxy_headers` into their server settings, and wrap the app with `peer.wrap` in their worker factory. These are identities when forwarding is off, so entry points never branch on it
- Those functions spell the same two facts three times because a server is started three ways here, through uvicorn keyword arguments, uvicorn's own CLI and gunicorn. A new way to start a server gets its own translation in `mode.py`, never a branch in the entry point

## Client address

Python must see each request as if the client had connected directly. `x-litellm-rust-peer` is the only Rust-specific input, and the proxy app itself never knows Rust is in front of it

- Rust sends the client's TCP peer in `x-litellm-rust-peer` and leaves every forwarding header untouched. It never appends itself to `X-Forwarded-For`, because the proxy parses that header on its own (`use_x_forwarded_for`, `mcp_xff_num_trusted_hops`) and an extra hop would shift what those settings resolve
- Server-level proxy headers are off in a supervised server, through `proxy_headers: False` for uvicorn, `--no-proxy-headers` for its CLI and the `proxy_headers` argument of the gunicorn worker. The server's TCP peer is always loopback, which uvicorn and gunicorn trust by default, so leaving them on would let any client set its own address and scheme
- `peer.RustPeerMiddleware` puts the real peer back into the scope and then runs uvicorn's own `ProxyHeadersMiddleware` with the operator's trust. It wraps the app from outside, so it runs before anything that reads the client address
- The operator's trust is one string, `trusted_proxies`. It is resolved by the server library the entry point uses, never defaulted in this package. `server.NO_TRUSTED_PROXIES` stands for proxy headers the operator turned off, since a trust list that matches nobody behaves the same
- `peer.py` honors the peer header only from the loopback hop and always removes it. Any process on the host can connect to the private listener and send that header, so loopback is the trust boundary of the private listener. That widens what Python alone allows only when the operator's trust list leaves loopback out

## Environment contracts

The environment contract is written and read in one place

- The Python child's contract is the `mode.Supervised` type itself. `mode.supervised_environment` serializes it into one variable and `mode.rust_forward_mode` validates it back, so a new field needs no parsing code
