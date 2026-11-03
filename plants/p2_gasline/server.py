"""P2 OPC UA server (SPEC.md): the gas line model behind opc.tcp://0.0.0.0:4840, nodes ns=2;s=<TAG>.PV,
<VALVE>.FB and <VALVE>.CMD, Good StatusCode and a SourceTimestamp on every value.

Users (passwords from the environment, never in files): `zerostate` reads only; `operator` may write
*.CMD and nothing else. The server's own permission check enforces it, and every write attempt,
allowed or refused, is logged with its user to P2_WRITE_LOG (/var/log/p2_writes.jsonl).
Faults and truth go through a unix socket inside the container (P2_CONTROL), never the network.

    ZS_TIME_SCALE=30 P2_PASSWORD_ZEROSTATE=... P2_PASSWORD_OPERATOR=... python server.py
"""

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from asyncua import Server, ua
from asyncua.crypto.permission_rules import USER_TYPES, PermissionRuleset
from asyncua.server.user_managers import UserManager
from asyncua.server.users import User, UserRole
from asyncua.ua.ua_binary import struct_from_binary

sys.path.insert(0, str(Path(__file__).parent))
from model import COMMANDED, SPANS, GasLine

NS_URI = "urn:zerostate:p2_gasline"
TICK_WALL_S = 0.05  # x30 -> 1.5 process-s per tick, the model's largest step
WRITE = ua.NodeId(ua.ObjectIds.WriteRequest_Encoding_DefaultBinary)
READ_ONLY = {ua.NodeId(t) for t in USER_TYPES} - {WRITE, ua.NodeId(ua.ObjectIds.CallRequest_Encoding_DefaultBinary)}


class Users(UserManager):
    def __init__(self, passwords: dict[str, str]):
        self.passwords = passwords

    def get_user(self, iserver, username=None, password=None, certificate=None):
        ok = username in self.passwords and password == self.passwords[username]
        return User(role=UserRole.User, name=username) if ok else None


class WriteGuard(PermissionRuleset):
    """Reads for every user; writes only `operator` -> *.CMD values. Every write attempt is logged."""

    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)

    def check_validity(self, user, action_type_id, body):
        if action_type_id != WRITE:
            return action_type_id in READ_ONLY
        items = struct_from_binary(ua.WriteParameters, body.copy()).NodesToWrite  # copy: the server parses it again
        nodes = [str(i.NodeId.Identifier) for i in items]
        allowed = (user.name == "operator"
                   and all(n.endswith(".CMD") and i.AttributeId == ua.AttributeIds.Value for n, i in zip(nodes, items, strict=True)))
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "user": user.name, "nodes": nodes, "allowed": allowed}) + "\n")
        return allowed


class Plant:
    """The model, the address space and the update loop."""

    def __init__(self, server: Server, model: GasLine, scale: float):
        self.server, self.model, self.scale = server, model, scale
        self.updating = True
        self.nodes: dict[str, object] = {}

    async def build(self) -> None:
        idx = await self.server.register_namespace(NS_URI)
        assert idx == 2, idx  # ns=2;s=<name> is the contract with ZeroState's map
        obj = await self.server.nodes.objects.add_object(ua.NodeId("P2", idx), "P2")
        for name, value in self.model.measure().items():
            node = await obj.add_variable(ua.NodeId(name, idx), name, ua.Variant(float(value), ua.VariantType.Double))
            if name.endswith(".CMD"):
                await node.set_writable()  # AccessLevel too: PV and FB are read-only in the address space
            self.nodes[name] = node
        await self.publish()

    async def publish(self) -> None:
        ts = datetime.now(UTC)
        for name, value in self.model.measure().items():
            dv = ua.DataValue(ua.Variant(float(value), ua.VariantType.Double), StatusCode_=ua.StatusCode(ua.StatusCodes.Good),
                              SourceTimestamp=ts, ServerTimestamp=ts)
            await self.server.write_attribute_value(self.nodes[name].nodeid, dv)

    async def tick(self) -> None:
        for v in COMMANDED:  # the operator's writes land on *.CMD; the model follows them
            self.model.command(v, await self.nodes[f"{v}.CMD"].read_value())
        self.model.step(self.scale * TICK_WALL_S)
        if self.updating:  # S12: a stopped update loop leaves values and SourceTimestamps old
            await self.publish()

    def control(self, req: dict) -> dict:
        """Eval only (unix socket): truth, faults, update loop on/off."""
        kind = req.get("request")
        if kind == "set":
            for k, v in req["data"].items():
                self.model.set(k, v)
        elif kind == "updates":
            self.updating = bool(req["on"])
        elif kind != "read":
            return {"error": f"unknown request {kind!r}"}
        return {"t": time.time(), "updating": self.updating, "time_scale": self.scale, **self.model.truth()}


def make_server(endpoint: str, passwords: dict[str, str], write_log: str | Path) -> Server:
    server = Server(user_manager=Users(passwords))
    server.set_endpoint(endpoint)
    server.set_server_name("ZeroState P2 gas line")
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity], permission_ruleset=WriteGuard(write_log))
    server.set_identity_tokens([ua.UserNameIdentityToken])  # no anonymous sessions
    return server


async def serve(endpoint: str, passwords: dict[str, str], write_log: str | Path, scale: float,
                control_path: str | None = None, seed: int | None = None, ready=None, stop: asyncio.Event | None = None,
                box: dict | None = None) -> None:
    """`ready` (any object with .set()), `stop` and `box` (receives the Plant) are for in-process tests."""
    server = make_server(endpoint, passwords, write_log)
    await server.init()
    plant = Plant(server, GasLine(seed=seed), scale)
    await plant.build()
    if box is not None:
        box["plant"] = plant

    async def on_control(reader, writer):
        try:
            reply = plant.control(json.loads(await reader.readline()))
        except (ValueError, KeyError, TypeError) as e:  # a bad request must not stop the plant
            reply = {"error": f"{type(e).__name__}: {e}"}
        writer.write((json.dumps(reply) + "\n").encode())
        await writer.drain()
        writer.close()

    ctl = await asyncio.start_unix_server(on_control, control_path) if control_path else None
    async with server:
        if ready:
            ready.set()
        while not (stop and stop.is_set()):
            t0 = time.monotonic()
            await plant.tick()
            await asyncio.sleep(max(0.0, TICK_WALL_S - (time.monotonic() - t0)))
    if ctl:
        ctl.close()


def main() -> None:
    passwords = {u: os.environ[f"P2_PASSWORD_{u.upper()}"] for u in ("zerostate", "operator")}
    scale = float(os.environ.get("ZS_TIME_SCALE", "30"))
    control = os.environ.get("P2_CONTROL", "/run/p2/control.sock")
    Path(control).parent.mkdir(parents=True, exist_ok=True)
    Path(control).unlink(missing_ok=True)
    print(f"P2 gas line: x{scale:g}, instruments {sorted(SPANS)}", flush=True)
    asyncio.run(serve("opc.tcp://0.0.0.0:4840/", passwords, os.environ.get("P2_WRITE_LOG", "/var/log/p2_writes.jsonl"),
                      scale, control))


if __name__ == "__main__":
    main()
