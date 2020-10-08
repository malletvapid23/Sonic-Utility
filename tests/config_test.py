import os
import traceback

from click.testing import CliRunner

from utilities_common.db import Db

load_minigraph_command_output="""\
Executing stop of service telemetry...
Executing stop of service swss...
Executing stop of service lldp...
Executing stop of service pmon...
Executing stop of service bgp...
Executing stop of service hostcfgd...
Executing stop of service nat...
Running command: /usr/local/bin/sonic-cfggen -H -m --write-to-db
Running command: pfcwd start_default
Running command: config qos reload
Executing reset-failed of service bgp...
Executing reset-failed of service dhcp_relay...
Executing reset-failed of service hostcfgd...
Executing reset-failed of service hostname-config...
Executing reset-failed of service interfaces-config...
Executing reset-failed of service lldp...
Executing reset-failed of service nat...
Executing reset-failed of service ntp-config...
Executing reset-failed of service pmon...
Executing reset-failed of service radv...
Executing reset-failed of service rsyslog-config...
Executing reset-failed of service snmp...
Executing reset-failed of service swss...
Executing reset-failed of service syncd...
Executing reset-failed of service teamd...
Executing reset-failed of service telemetry...
Executing restart of service hostname-config...
Executing restart of service interfaces-config...
Executing restart of service ntp-config...
Executing restart of service rsyslog-config...
Executing restart of service swss...
Executing restart of service bgp...
Executing restart of service pmon...
Executing restart of service lldp...
Executing restart of service hostcfgd...
Executing restart of service nat...
Executing restart of service telemetry...
Reloading Monit configuration ...
Please note setting loaded from minigraph will be lost after system reboot. To preserve setting, run `config save`.
"""

class TestLoadMinigraph(object):
    @classmethod
    def setup_class(cls):
        os.environ['UTILITIES_UNIT_TESTING'] = "1"
        print("SETUP")

    def test_load_minigraph(self, get_cmd_module, setup_single_broacom_asic):
        (config, show) = get_cmd_module
        runner = CliRunner()
        result = runner.invoke(config.config.commands["load_minigraph"], ["-y"])
        print(result.exit_code)
        print(result.output)
        traceback.print_tb(result.exc_info[2])
        assert result.exit_code == 0
        assert "\n".join([ l.rstrip() for l in result.output.split('\n')]) == load_minigraph_command_output

    def test_load_minigraph_with_disabled_telemetry(self, get_cmd_module, setup_single_broacom_asic):
        (config, show) = get_cmd_module
        db = Db()
        runner = CliRunner()
        result = runner.invoke(config.config.commands["feature"].commands["state"], ["telemetry", "disabled"], obj=db)
        assert result.exit_code == 0
        result = runner.invoke(show.cli.commands["feature"].commands["status"], ["telemetry"], obj=db)
        print(result.output)
        assert result.exit_code == 0
        result = runner.invoke(config.config.commands["load_minigraph"], ["-y"], obj=db)
        print(result.exit_code)
        print(result.output)
        assert result.exit_code == 0
        assert "telemetry" not in result.output

    @classmethod
    def teardown_class(cls):
        os.environ['UTILITIES_UNIT_TESTING'] = "0"
        print("TEARDOWN")
