import json
import os
import sys

import click
import utilities_common.cli as clicommon
from sonic_py_common import multi_asic
from swsscommon.swsscommon import SonicV2Connector, ConfigDBConnector
from tabulate import tabulate
from utilities_common import platform_sfputil_helper

platform_sfputil = None

REDIS_TIMEOUT_MSECS = 0

CONFIG_SUCCESSFUL = 100
CONFIG_FAIL = 1

VENDOR_NAME = "Credo"
VENDOR_MODEL = "CAC125321P2PA0MS"

# Helper functions


def get_value_for_key_in_dict(mdict, port, key, table_name):
    value = mdict.get(key, None)
    if value is None:
        click.echo("could not retrieve key {} value for port {} inside table {}".format(key, port, table_name))
        sys.exit(CONFIG_FAIL)
    return value

#
# 'muxcable' command ("config muxcable")
#


def get_value_for_key_in_config_tbl(config_db, port, key, table):
    info_dict = {}
    info_dict = config_db.get_entry(table, port)
    if info_dict is None:
        click.echo("could not retrieve key {} value for port {} inside table {}".format(key, port, table))
        sys.exit(CONFIG_FAIL)

    value = get_value_for_key_in_dict(info_dict, port, key, table)

    return value


@click.group(name='muxcable', cls=clicommon.AliasedGroup)
def muxcable():
    """SONiC command line - 'show muxcable' command"""

    if os.geteuid() != 0:
        click.echo("Root privileges are required for this operation")
        sys.exit(CONFIG_FAIL)

    global platform_sfputil
    # Load platform-specific sfputil class
    platform_sfputil_helper.load_platform_sfputil()

    # Load port info
    platform_sfputil_helper.platform_sfputil_read_porttab_mappings()

    platform_sfputil = platform_sfputil_helper.platform_sfputil


def lookup_statedb_and_update_configdb(per_npu_statedb, config_db, port, state_cfg_val, port_status_dict):

    muxcable_statedb_dict = per_npu_statedb.get_all(per_npu_statedb.STATE_DB, 'MUX_CABLE_TABLE|{}'.format(port))
    configdb_state = get_value_for_key_in_config_tbl(config_db, port, "state", "MUX_CABLE")
    ipv4_value = get_value_for_key_in_config_tbl(config_db, port, "server_ipv4", "MUX_CABLE")
    ipv6_value = get_value_for_key_in_config_tbl(config_db, port, "server_ipv6", "MUX_CABLE")

    state = get_value_for_key_in_dict(muxcable_statedb_dict, port, "state", "MUX_CABLE_TABLE")
    if (state == "active" and configdb_state == "active") or (state == "standby" and configdb_state == "active") or (state == "unknown" and configdb_state == "active"):
        if state_cfg_val == "active":
            # status is already active, so right back error
            port_status_dict[port] = 'OK'
        if state_cfg_val == "auto":
            # display ok and write to cfgdb auto
            port_status_dict[port] = 'OK'
            config_db.set_entry("MUX_CABLE", port, {"state": "auto",
                                                    "server_ipv4": ipv4_value, "server_ipv6": ipv6_value})
    elif state == "active" and configdb_state == "auto":
        if state_cfg_val == "active":
            # make the state active and write back OK
            config_db.set_entry("MUX_CABLE", port, {"state": "active",
                                                    "server_ipv4": ipv4_value, "server_ipv6": ipv6_value})
            port_status_dict[port] = 'OK'
        if state_cfg_val == "auto":
            # dont write anything to db, write OK to user
            port_status_dict[port] = 'OK'

    elif (state == "standby" and configdb_state == "auto") or (state == "unknown" and configdb_state == "auto"):
        if state_cfg_val == "active":
            # make the state active
            config_db.set_entry("MUX_CABLE", port, {"state": "active",
                                                    "server_ipv4": ipv4_value, "server_ipv6": ipv6_value})
            port_status_dict[port] = 'INPROGRESS'
        if state_cfg_val == "auto":
            # dont write anything to db
            port_status_dict[port] = 'OK'


# 'muxcable' command ("config muxcable mode <port|all> active|auto")
@muxcable.command()
@click.argument('state', metavar='<operation_status>', required=True, type=click.Choice(["active", "auto"]))
@click.argument('port', metavar='<port_name>', required=True, default=None)
@click.option('--json', 'json_output', required=False, is_flag=True, type=click.BOOL)
def mode(state, port, json_output):
    """Show muxcable summary information"""

    port_table_keys = {}
    y_cable_asic_table_keys = {}
    per_npu_configdb = {}
    per_npu_statedb = {}
    mux_tbl_cfg_db = {}

    # Getting all front asic namespace and correspding config and state DB connector

    namespaces = multi_asic.get_front_end_namespaces()
    for namespace in namespaces:
        asic_id = multi_asic.get_asic_index_from_namespace(namespace)
        # replace these with correct macros
        per_npu_configdb[asic_id] = ConfigDBConnector(use_unix_socket_path=True, namespace=namespace)
        per_npu_configdb[asic_id].connect()
        per_npu_statedb[asic_id] = SonicV2Connector(use_unix_socket_path=True, namespace=namespace)
        per_npu_statedb[asic_id].connect(per_npu_statedb[asic_id].STATE_DB)

        mux_tbl_cfg_db[asic_id] = per_npu_configdb[asic_id].get_table("MUX_CABLE")

        port_table_keys[asic_id] = per_npu_statedb[asic_id].keys(
            per_npu_statedb[asic_id].STATE_DB, 'MUX_CABLE_TABLE|*')

    if port is not None and port != "all":

        asic_index = None
        if platform_sfputil is not None:
            asic_index = platform_sfputil.get_asic_id_for_logical_port(port)
        if asic_index is None:
            # TODO this import is only for unit test purposes, and should be removed once sonic_platform_base
            # is fully mocked
            import sonic_platform_base.sonic_sfp.sfputilhelper
            asic_index = sonic_platform_base.sonic_sfp.sfputilhelper.SfpUtilHelper().get_asic_id_for_logical_port(port)
            if asic_index is None:
                click.echo("Got invalid asic index for port {}, cant retreive mux status".format(port))
                sys.exit(CONFIG_FAIL)

        if per_npu_statedb[asic_index] is not None:
            y_cable_asic_table_keys = port_table_keys[asic_index]
            logical_key = "MUX_CABLE_TABLE|{}".format(port)
            if logical_key in y_cable_asic_table_keys:
                port_status_dict = {}
                lookup_statedb_and_update_configdb(
                    per_npu_statedb[asic_index], per_npu_configdb[asic_index], port, state, port_status_dict)

                if json_output:
                    click.echo("{}".format(json.dumps(port_status_dict, indent=4)))
                else:
                    headers = ['port', 'state']
                    data = sorted([(k, v) for k, v in port_status_dict.items()])
                    click.echo(tabulate(data, headers=headers))

                sys.exit(CONFIG_SUCCESSFUL)

            else:
                click.echo("this is not a valid port present on mux_cable".format(port))
                sys.exit(CONFIG_FAIL)
        else:
            click.echo("there is not a valid asic table for this asic_index".format(asic_index))
            sys.exit(CONFIG_FAIL)

    elif port == "all" and port is not None:

        port_status_dict = {}
        for namespace in namespaces:
            asic_id = multi_asic.get_asic_index_from_namespace(namespace)
            for key in port_table_keys[asic_id]:
                logical_port = key.split("|")[1]
                lookup_statedb_and_update_configdb(
                    per_npu_statedb[asic_id], per_npu_configdb[asic_id], logical_port, state, port_status_dict)

            if json_output:
                click.echo("{}".format(json.dumps(port_status_dict, indent=4)))
            else:
                data = sorted([(k, v) for k, v in port_status_dict.items()])

                headers = ['port', 'state']
                click.echo(tabulate(data, headers=headers))

        sys.exit(CONFIG_SUCCESSFUL)


@muxcable.group(cls=clicommon.AbbreviationGroup)
def prbs():
    """Enable/disable PRBS mode on a port"""
    pass


@prbs.command()
@click.argument('port', required=True, default=None, type=click.INT)
@click.argument('target', required=True, default=None, type=click.INT)
@click.argument('mode_value', required=True, default=None, type=click.INT)
@click.argument('lane_map', required=True, default=None, type=click.INT)
def enable(port, target, mode_value, lane_map):
    """Enable PRBS mode on a port"""

    import sonic_y_cable.y_cable
    res = sonic_y_cable.y_cable.enable_prbs_mode(port, target, mode_value, lane_map)
    if res != True:
        click.echo("PRBS config unsuccesful")
        sys.exit(CONFIG_FAIL)
    click.echo("PRBS config sucessful")
    sys.exit(CONFIG_SUCCESSFUL)


@prbs.command()
@click.argument('port', required=True, default=None, type=click.INT)
@click.argument('target', required=True, default=None, type=click.INT)
def disable(port, target):
    """Disable PRBS mode on a port"""

    import sonic_y_cable.y_cable
    res = sonic_y_cable.y_cable.disable_prbs_mode(port, target)
    if res != True:
        click.echo("PRBS disable unsuccesful")
        sys.exit(CONFIG_FAIL)
    click.echo("PRBS disable sucessful")
    sys.exit(CONFIG_SUCCESSFUL)


@muxcable.group(cls=clicommon.AbbreviationGroup)
def loopback():
    """Enable/disable loopback mode on a port"""
    pass


@loopback.command()
@click.argument('port', required=True, default=None, type=click.INT)
@click.argument('target', required=True, default=None, type=click.INT)
@click.argument('lane_map', required=True, default=None, type=click.INT)
def enable(port, target, lane_map):
    """Enable loopback mode on a port"""

    import sonic_y_cable.y_cable
    res = sonic_y_cable.y_cable.enable_loopback_mode(port, target, lane_map)
    if res != True:
        click.echo("loopback config unsuccesful")
        sys.exit(CONFIG_FAIL)
    click.echo("loopback config sucessful")
    sys.exit(CONFIG_SUCCESSFUL)


@loopback.command()
@click.argument('port', required=True, default=None, type=click.INT)
@click.argument('target', required=True, default=None, type=click.INT)
def disable(port, target):
    """Disable loopback mode on a port"""

    import sonic_y_cable.y_cable
    res = sonic_y_cable.y_cable.disable_loopback_mode(port, target)
    if res != True:
        click.echo("loopback disable unsuccesful")
        sys.exit(CONFIG_FAIL)
    click.echo("loopback disable sucessful")
    sys.exit(CONFIG_SUCCESSFUL)


@muxcable.group(cls=clicommon.AbbreviationGroup)
def hwmode():
    """Configure muxcable hardware directly"""
    pass


@hwmode.command()
@click.argument('state', metavar='<operation_status>', required=True, type=click.Choice(["active", "standby"]))
@click.argument('port', metavar='<port_name>', required=True, default=None)
def state(state, port):
    """Configure the muxcable mux state {active/standby}"""

    per_npu_statedb = {}
    transceiver_table_keys = {}
    transceiver_dict = {}

    # Getting all front asic namespace and correspding config and state DB connector

    namespaces = multi_asic.get_front_end_namespaces()
    for namespace in namespaces:
        asic_id = multi_asic.get_asic_index_from_namespace(namespace)
        per_npu_statedb[asic_id] = SonicV2Connector(use_unix_socket_path=False, namespace=namespace)
        per_npu_statedb[asic_id].connect(per_npu_statedb[asic_id].STATE_DB)

        transceiver_table_keys[asic_id] = per_npu_statedb[asic_id].keys(
            per_npu_statedb[asic_id].STATE_DB, 'TRANSCEIVER_INFO|*')

    if port is not None and port != "all":
        click.confirm(('Muxcable at port {} will be changed to {} state. Continue?'.format(port, state)), abort=True)
        logical_port_list = platform_sfputil_helper.get_logical_list()
        if port not in logical_port_list:
            click.echo("ERR: This is not a valid port, valid ports ({})".format(", ".join(logical_port_list)))
            sys.exit(CONFIG_FAIL)

        asic_index = None
        if platform_sfputil is not None:
            asic_index = platform_sfputil_helper.get_asic_id_for_logical_port(port)
            if asic_index is None:
                # TODO this import is only for unit test purposes, and should be removed once sonic_platform_base
                # is fully mocked
                import sonic_platform_base.sonic_sfp.sfputilhelper
                asic_index = sonic_platform_base.sonic_sfp.sfputilhelper.SfpUtilHelper().get_asic_id_for_logical_port(port)
                if asic_index is None:
                    click.echo("Got invalid asic index for port {}, cant retreive mux status".format(port))
                    sys.exit(CONFIG_FAIL)

        if platform_sfputil is not None:
            physical_port_list = platform_sfputil_helper.logical_port_name_to_physical_port_list(port)

        if not isinstance(physical_port_list, list):
            click.echo(("ERR: Unable to locate physical port information for {}".format(port)))
            sys.exit(CONFIG_FAIL)
        if len(physical_port_list) != 1:
            click.echo("ERR: Found multiple physical ports ({}) associated with {}".format(
                ", ".join(physical_port_list), port))
            sys.exit(CONFIG_FAIL)

        transceiver_dict[asic_index] = per_npu_statedb[asic_index].get_all(
            per_npu_statedb[asic_index].STATE_DB, 'TRANSCEIVER_INFO|{}'.format(port))

        vendor_value = get_value_for_key_in_dict(transceiver_dict[asic_index], port, "manufacturer", "TRANSCEIVER_INFO")
        model_value = get_value_for_key_in_dict(transceiver_dict[asic_index], port, "model", "TRANSCEIVER_INFO")

        """ This check is required for checking whether or not this port is connected to a Y cable
        or not. The check gives a way to differentiate between non Y cable ports and Y cable ports.
        TODO: this should be removed once their is support for multiple vendors on Y cable"""

        if vendor_value != VENDOR_NAME or model_value != VENDOR_MODEL:
            click.echo("ERR: Got invalid vendor value and model for port {}".format(port))
            sys.exit(CONFIG_FAIL)

        physical_port = physical_port_list[0]

        logical_port_list_for_physical_port = platform_sfputil_helper.get_physical_to_logical()

        logical_port_list_per_port = logical_port_list_for_physical_port.get(physical_port, None)

        """ This check is required for checking whether or not this logical port is the one which is 
        actually mapped to physical port and by convention it is always the first port.
        TODO: this should be removed with more logic to check which logical port maps to actual physical port
        being used"""

        if port != logical_port_list_per_port[0]:
            click.echo("ERR: This logical Port {} is not on a muxcable".format(port))
            sys.exit(CONFIG_FAIL)

        import sonic_y_cable.y_cable
        read_side = sonic_y_cable.y_cable.check_read_side(physical_port)
        if read_side == False or read_side == -1:
            click.echo(("ERR: Unable to get read_side for the cable port {}".format(port)))
            sys.exit(CONFIG_FAIL)

        mux_direction = sonic_y_cable.y_cable.check_mux_direction(physical_port)
        if mux_direction == False or mux_direction == -1:
            click.echo(("ERR: Unable to get mux direction for the cable port {}".format(port)))
            sys.exit(CONFIG_FAIL)

        if int(read_side) == 1:
            if state == "active":
                res = sonic_y_cable.y_cable.toggle_mux_to_torA(physical_port)
            elif state == "standby":
                res = sonic_y_cable.y_cable.toggle_mux_to_torB(physical_port)
            click.echo("Success in toggling port {} to {}".format(port, state))
        elif int(read_side) == 2:
            if state == "active":
                res = sonic_y_cable.y_cable.toggle_mux_to_torB(physical_port)
            elif state == "standby":
                res = sonic_y_cable.y_cable.toggle_mux_to_torA(physical_port)
            click.echo("Success in toggling port {} to {}".format(port, state))

        if res == False:
            click.echo("ERR: Unable to toggle port {} to {}".format(port, state))
            sys.exit(CONFIG_FAIL)

    elif port == "all" and port is not None:

        click.confirm(('Muxcables at all ports will be changed to {} state. Continue?'.format(state)), abort=True)
        logical_port_list = platform_sfputil_helper.get_logical_list()

        rc = True
        for port in logical_port_list:
            if platform_sfputil is not None:
                physical_port_list = platform_sfputil_helper.logical_port_name_to_physical_port_list(port)

            asic_index = None
            if platform_sfputil is not None:
                asic_index = platform_sfputil_helper.get_asic_id_for_logical_port(port)
                if asic_index is None:
                    # TODO this import is only for unit test purposes, and should be removed once sonic_platform_base
                    # is fully mocked
                    import sonic_platform_base.sonic_sfp.sfputilhelper
                    asic_index = sonic_platform_base.sonic_sfp.sfputilhelper.SfpUtilHelper().get_asic_id_for_logical_port(port)
                    if asic_index is None:
                        click.echo("Got invalid asic index for port {}, cant retreive mux status".format(port))

            if not isinstance(physical_port_list, list):
                click.echo(("ERR: Unable to locate physical port information for {}".format(port)))
                continue

            if len(physical_port_list) != 1:
                click.echo("ERR: Found multiple physical ports ({}) associated with {}".format(
                    ", ".join(physical_port_list), port))
                continue

            transceiver_dict[asic_index] = per_npu_statedb[asic_index].get_all(
                per_npu_statedb[asic_index].STATE_DB, 'TRANSCEIVER_INFO|{}'.format(port))
            vendor_value = transceiver_dict[asic_index].get("manufacturer", None)
            model_value = transceiver_dict[asic_index].get("model", None)

            """ This check is required for checking whether or not this port is connected to a Y cable
            or not. The check gives a way to differentiate between non Y cable ports and Y cable ports.
            TODO: this should be removed once their is support for multiple vendors on Y cable"""

            if vendor_value != VENDOR_NAME or model_value != VENDOR_MODEL:
                continue

            physical_port = physical_port_list[0]

            logical_port_list_for_physical_port = platform_sfputil_helper.get_physical_to_logical()

            logical_port_list_per_port = logical_port_list_for_physical_port.get(physical_port, None)

            """ This check is required for checking whether or not this logical port is the one which is 
            actually mapped to physical port and by convention it is always the first port.
            TODO: this should be removed with more logic to check which logical port maps to actual physical port
            being used"""

            if port != logical_port_list_per_port[0]:
                continue

            import sonic_y_cable.y_cable
            read_side = sonic_y_cable.y_cable.check_read_side(physical_port)
            if read_side == False or read_side == -1:
                click.echo(("ERR: Unable to get read side for the cable port {}".format(port)))
                rc = False
                continue

            mux_direction = sonic_y_cable.y_cable.check_mux_direction(physical_port)
            if mux_direction == False or mux_direction == -1:
                click.echo(("ERR: Unable to get mux direction for the cable port {}".format(port)))
                rc = False
                continue

            if int(read_side) == 1:
                if state == "active":
                    res = sonic_y_cable.y_cable.toggle_mux_to_torA(physical_port)
                elif state == "standby":
                    res = sonic_y_cable.y_cable.toggle_mux_to_torB(physical_port)
                click.echo("Success in toggling port {} to {}".format(port, state))
            elif int(read_side) == 2:
                if state == "active":
                    res = sonic_y_cable.y_cable.toggle_mux_to_torB(physical_port)
                elif state == "standby":
                    res = sonic_y_cable.y_cable.toggle_mux_to_torA(physical_port)
                click.echo("Success in toggling port {} to {}".format(port, state))

            if res == False:
                rc = False
                click.echo("ERR: Unable to toggle port {} to {}".format(port, state))

        if rc == False:
            click.echo("ERR: Unable to toggle one or more ports to {}".format(state))
            sys.exit(CONFIG_FAIL)
