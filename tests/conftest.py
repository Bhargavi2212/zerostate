import asyncio
import socket
import threading
import time

import pytest
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.server import ServerAsyncStop, StartAsyncTcpServer


def block(values, cls=ModbusSequentialDataBlock):
    # Starts at 1: pymodbus servers add 1 to the requested address.
    return values if isinstance(values, ModbusSequentialDataBlock) else cls(1, list(values))


@pytest.fixture
def modbus_server():
    """Start an in-process Modbus TCP server on a free localhost port: start(ir=, hr=, co=) -> (port, stop)."""
    running = []

    def start(ir=(0,) * 200, hr=(0,) * 200, co=(False,) * 16):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        # di must be passed: pymodbus 3.9.2 ignores co/ir/hr when di is None.
        ctx = ModbusServerContext(
            slaves=ModbusSlaveContext(di=block([False] * 16), ir=block(ir), hr=block(hr), co=block(co)),
            single=True,
        )
        loop = asyncio.new_event_loop()
        t = threading.Thread(
            target=lambda: loop.run_until_complete(StartAsyncTcpServer(ctx, address=("127.0.0.1", port))),
            daemon=True,
        )
        t.start()
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
                break
            except OSError:
                time.sleep(0.05)

        def stop():
            if t.is_alive():
                asyncio.run_coroutine_threadsafe(ServerAsyncStop(), loop).result(5)
                t.join(5)

        running.append(stop)
        return port, stop

    yield start
    for stop in running:
        stop()
