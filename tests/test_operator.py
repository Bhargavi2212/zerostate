"""P1-3: the operator's writes against an in-process PLC stand-in."""

import importlib.util
from pathlib import Path

import pytest
from conftest import block
from pymodbus.datastore import ModbusSequentialDataBlock

spec = importlib.util.spec_from_file_location("operator_p1", Path(__file__).parents[1] / "plants" / "p1_grfics" / "operator.py")
op_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(op_mod)

LOG: list[tuple[str, int, list]] = []


class Recording(ModbusSequentialDataBlock):
    kind = "?"

    def setValues(self, address, values):  # pymodbus API name
        LOG.append((self.kind, address - 1, list(values) if isinstance(values, list) else [values]))
        super().setValues(address, values)


class HR(Recording):
    kind = "hr"


class Coil(Recording):
    kind = "coil"


class StuckHR(ModbusSequentialDataBlock):
    def setValues(self, address, values):  # pymodbus API name
        pass


def plc(modbus_server, hr_cls=HR):
    LOG.clear()
    hr = [0] * 200
    hr[100:104] = [65535, 0, 13107, 47399]  # PLC's current commands
    hr[10:14] = op_mod.DEFAULT_SETPOINTS
    port, _ = modbus_server(hr=block(hr, hr_cls), co=block([False] * 16, Coil))
    return op_mod.Operator("127.0.0.1", port)


def test_manual_on_copies_commands_before_setting_the_coil(modbus_server):
    op = plc(modbus_server)
    op.manual_on()
    s = op.status()
    op.close()
    writes = [(k, a) for k, a, _ in LOG]
    assert writes.index(("hr", 10)) < writes.index(("coil", 0))
    assert s["manual_mode"] is True
    assert s["manual_setpoint_pct"] == s["command_pct"]  # bumpless: nothing moves on the switch


def test_readback_mismatch_aborts_before_the_coil(modbus_server):
    op = plc(modbus_server, StuckHR)
    with pytest.raises(op_mod.OperatorError):
        op.manual_on()
    assert op._coil() is False
    op.close()


def test_manual_off_restores_plc_defaults(modbus_server):
    op = plc(modbus_server)
    op.manual_on()
    op.set("f1", 0)
    op.manual_off()
    s = op.status()
    op.close()
    assert s["manual_mode"] is False
    assert [round(v) for v in s["manual_setpoint_pct"].values()] == [0, 0, 100, 100]


def test_writes_only_coil0_and_hr10_13(modbus_server):
    op = plc(modbus_server)
    op.manual_on()
    op.set("product", 0)
    op.manual_off()
    op.close()
    assert {k for k, _, _ in LOG} <= {"hr", "coil"}
    assert all(10 <= a <= 13 for k, a, _ in LOG if k == "hr")
    assert all(a == 0 for k, a, _ in LOG if k == "coil")
