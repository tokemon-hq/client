import os
import sys
import json
import time
import socket
import hashlib
import inspect
import logging
import asyncio
import platform
import threading
import itertools
import collections

from uniswap.uniswap import ETH_ADDRESS

try:
    import tkinter as tk
    from tkinter import ttk
    from tkinter.messagebox import showerror
    HAS_TK = True
except ImportError:
    # on linux without Tk installed
    HAS_TK = False

import websockets

from uniswap import Uniswap
from web3 import Web3
from dotenv import load_dotenv, find_dotenv


logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

gas_in_gwei = 0
status = "Starting"


def get_client_source():
    if main_is_frozen():
        with open(os.path.join(getattr(sys, '_MEIPASS'), 'src', 'main.py'), 'rt') as f:
            return f.read()
    else:
        return inspect.getsource(sys.modules[__name__]).encode('utf-8')


def get_client_hash():
    return hashlib.sha256(get_client_source()).hexdigest()


def gas_price_strategy(web3, transaction_params):
    return Web3.toWei(gas_in_gwei, 'gwei')


def to_dict(dict_to_parse):

    def parse_value(_val):
        if 'dict' in str(type(_val)).lower():
            return to_dict(_val)
        elif 'HexBytes' in str(type(_val)):
            return _val.hex()
        else:
            return _val

    parsed_dict = dict(dict_to_parse)
    for key, val in parsed_dict.items():
        if 'list' in str(type(val)):
            parsed_dict[key] = [parse_value(x) for x in val]
        else:
            parsed_dict[key] = parse_value(val)
    return parsed_dict


async def uniswap_buy_input(input_token, output_token, input_quantity, max_slippage, max_gas, account, ethereum_provider):
    # set web3 with gas price
    global gas_in_gwei
    gas_in_gwei = max_gas
    w3 = Web3(Web3.HTTPProvider(ethereum_provider))
    w3.eth.setGasPriceStrategy(gas_price_strategy)

    # set uniswap with w3 and slippage
    uniswap_wrapper = Uniswap(account['address'], account['pkey'], web3=w3, version=2, max_slippage=max_slippage)

    # trade exact input_quantity of input_token for output_token
    if input_token == ETH_ADDRESS:
        req = uniswap_wrapper._eth_to_token_swap_input(Web3.toChecksumAddress(output_token), input_quantity, None)
    else:
        req = uniswap_wrapper.make_trade(Web3.toChecksumAddress(input_token), Web3.toChecksumAddress(output_token),
                                     input_quantity)
    tx = w3.eth.waitForTransactionReceipt(req)

    # reformat output
    tx_dict = to_dict(tx)
    return tx_dict


def read_data_from_env():
    path = find_dotenv()
    logging.info('Attempting to read configuration from: %s' % path)
    load_dotenv(path)
    username = os.environ.get('USER_NAME')
    accounts = read_accounts_from_env()
    ethereum_provider = os.environ.get('ETHEREUM_PROVIDER')
    token = os.environ.get('TOKEN')
    base_url = os.environ.get('BASE_URL', 'txwsserver-prod.txmonitor.devops.mk')
    return {
        "username": username,
        "accounts": accounts,
        "ethereum_provider": ethereum_provider,
        "token": token,
        "base_url": base_url
    }


class ConfigError(ValueError):
    pass


def check_config(env_data):
    for n in ('username', 'token', 'base_url', 'ethereum_provider'):
        if not env_data.get(n):
            raise ConfigError("Missing '%s'" % n)

    acts = env_data.get('accounts') or {}
    if not acts:
        raise ConfigError('No Configured Account')

    for i, act in enumerate(acts.values()):
        for n in ('name', 'address', 'pkey'):
            if not act.get(n):
                raise ConfigError("Account %d Missing '%s'" % (i + 1, n))


def read_accounts_from_env():
    num_accounts = int(os.environ.get("NUM_ACCOUNTS", "0"))
    accounts = collections.OrderedDict()
    for i in range(num_accounts):
        index = i + 1
        acc_data = {
            "name": os.environ.get(f"ACCOUNT_{index}_NAME"),
            "address": os.environ.get(f"ACCOUNT_{index}_ADDRESS"),
            "pkey": os.environ.get(f"ACCOUNT_{index}_PKEY")
        }
        accounts[acc_data['name']] = acc_data
    return accounts


def get_connection_uri(base_url: str, username: str):
    return f"ws://{base_url}/api/v1/users/subscribe/{username}"


def main_is_frozen():
    return hasattr(sys, "frozen")


def get_main_dir():
    if main_is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(sys.argv[0])


async def main(env_data, connection_retry=True):
    global status

    uri = get_connection_uri(env_data.get('base_url'), env_data.get('username'))
    logger.info('Connecting to %s' % uri)

    accounts = env_data.get('accounts')

    while connection_retry:
        async with websockets.connect(uri) as websocket:

            msg = {'code': 'login', 'token': env_data.get('token'), "accounts": list(accounts.keys())}
            logger.debug('Authenticating: %r' % msg)

            await websocket.send(json.dumps(msg))

            msg_response = await websocket.recv()

            msg_response_dict = json.loads(msg_response)
            if msg_response_dict['code'] == 'auth_ok':
                logger.info('Authentication successful.')
                status = 'Connected'
                fl_exit = False
                try:
                    while not fl_exit:

                        try:
                            msg = await asyncio.wait_for(websocket.recv(), timeout=10)
                        except asyncio.exceptions.TimeoutError:
                            # ping the server
                            logger.debug('Ping server.')
                            await websocket.send(json.dumps({'code': 'ping', 'token': env_data.get('token'), 'accounts': list(accounts.keys())}))
                            continue

                        try:
                            msg_json = json.loads(msg)
                            if msg_json['code'] == 'close':
                                logger.info('Close signal received from server, exiting.')
                                fl_exit = True
                            elif msg_json['code'] == 'trade':
                                logger.info(f'Trade signal received from server: {msg_json}')
                                input_token = msg_json['input_token']
                                output_token = msg_json['output_token']
                                input_quantity = msg_json['input_quantity']
                                max_slippage = msg_json['max_slippage']
                                max_gas = msg_json['max_gas']
                                trading_config_id = msg_json['trading_config_id']
                                strategy_type = msg_json['strategy_type']
                                account_name = msg_json['account']
                                account = accounts[account_name]
                                tx_dict = await uniswap_buy_input(input_token, output_token, input_quantity,
                                                                  max_slippage,
                                                                  max_gas, account, env_data.get('ethereum_provider'))
                                msg_response = {"status": "done",
                                                "tx": tx_dict,
                                                "trading_config_id": trading_config_id,
                                                "input_quantity": input_quantity,
                                                "strategy_type": strategy_type}
                                logger.info(f'Got transaction: {str(tx_dict)}')
                                logger.info(f'Transaction data sent to server!')
                                await websocket.send(json.dumps(msg_response))
                            else:
                                logger.warning(f'Received unknown message: {msg}')
                        except Exception as e:
                            logger.error(e)
                            msg_response = {"status": "error", "trading_config_id": trading_config_id,
                                            "strategy_type": strategy_type, "message": str(e)}
                            logger.info(f'Transaction data sent to server!')
                            await websocket.send(json.dumps(msg_response))
                except websockets.exceptions.ConnectionClosedOK as e:
                    connection_retry = False
                    logger.info('Server closed the connection')
                except websockets.exceptions.ConnectionClosedError as e:
                    logger.info('Server connection closed abnormally, trying to reconnect in 10 seconds...')
            else:
                connection_retry = False
                logger.error('Error while authenticating to the server. Please check your credentials in the .env file.')
                status = 'Error Authenticating'

        if connection_retry:
            time.sleep(1)


class GUI(object):

    def __init__(self, env_data):
        self._root = tk.Tk()
        self._root.title('Tokemon Trading Bot')

        # self._root.geometry('500x100')
        # self._root.resizable(width=True, height=True)

        self._root.grid_columnconfigure(0, weight=1)
        self._root.grid_rowconfigure(0, weight=1)

        self._frame = ttk.Frame(self._root)
        self._frame.columnconfigure(1, weight=1)
        self._frame.columnconfigure(1, weight=3)

        self._thread = None

        def _label_entry(_lbl, _txt, _row, is_password=False, **gridpos):
            l = ttk.Label(self._frame, text=_lbl)
            l.grid(column=0, row=_row, sticky='W', padx=5, pady=5, **gridpos)

            sv = tk.StringVar()
            sv.set(_txt or '')
            sve = ttk.Entry(self._frame, textvariable=sv, show="*" if is_password else None)
            sve.grid(column=1, row=_row, padx=5, pady=5, sticky="EW", **gridpos)

            return sv

        self._gui_env_entries = {
            'username': _label_entry('Tokemon Username', env_data.get('username') or '', 1),
            'token': _label_entry('Tokemon Bot Token', env_data.get('token') or '', 2),
            'ethereum_provider': _label_entry('Infura URL', env_data.get('ethereum_provider') or '', 3)
        }

        acts = env_data['accounts']
        self._base_url = env_data['base_url']

        def _acct_entry(_num, _act, _row0):
            return {
                'account_%d_name' % _num: _label_entry('Account %d Name' % _num, _act.get('name') or '', _row0),
                'account_%d_address' % _num: _label_entry('Account %d Address' % _num, _act.get('address') or '', _row0 + 1),
                'account_%d_pkey' % _num: _label_entry('Account %d Private Key' % _num, _act.get('pkey') or '', _row0 + 2, True)
            }

        row = 4
        if len(acts) <= 1:
            try:
                act_1 = acts[tuple(acts.keys())[0]]
            except IndexError:
                act_1 = {'name': None, 'address': None, 'pkey': None}

            self._gui_env_entries.update(_acct_entry(1, act_1, row))
            row += 3

        else:
            for i, act_name in enumerate(acts):
                act = acts[act_name]
                self._gui_env_entries.update(_acct_entry(i + 1, act, row))
                row += 3

        self._button = ttk.Button(self._frame, text='Reconnect', state='disabled')
        self._button.grid(column=1, row=row, sticky='E', padx=5, pady=5)
        self._button.configure(command=self._button_clicked)

        row += 1

        self._result_label = ttk.Label(self._frame)
        self._result_label.grid(row=row, columnspan=3, padx=5, pady=5)

        self._frame.grid(padx=10, pady=10, sticky='NSEW')

    def _button_clicked(self, *args):
        self.start_thread(True)

    def update_status(self):
        offer_reconnect = (self._thread is None) or (not self._thread.is_alive())
        if offer_reconnect:
            self._button.configure(state='normal')
        else:
            self._button.configure(state='disabled')

        msg = 'Status: %s' % status
        self._result_label.configure(text=msg)
        self._root.after(1000, self.update_status)


    def get_env_data_from_gui(self):
        d = {k: self._gui_env_entries[k].get() for k in ('username', 'token', 'ethereum_provider')}
        d['base_url'] = self._base_url

        accounts = {}
        for i in itertools.count(1):
            try:
                act = {}
                for j in ('name', 'address', 'pkey'):
                    act[j] = self._gui_env_entries['account_%d_%s' % (i, j)].get()
                accounts[act['name']] = act
            except KeyError:
                break

        d['accounts'] = accounts
        return d

    def start_thread(self, was_reconfigured=False):
        env_data = self.get_env_data_from_gui()

        try:
            check_config(env_data)
        except ConfigError:
            global status

            if was_reconfigured:
                status = 'Incorrect Configuration'
            else:
                status = 'Not Configured'

            return

        def run_thread():
            global status
            try:
                asyncio.run(main(env_data))
            except (ConnectionError, socket.error):
                status = "Connection Error"
            except Exception:
                status = "Unknown Error"
                logging.error(status, exc_info=True)

        self._thread = threading.Thread(target=run_thread, daemon=True)
        self._thread.start()

    def run(self):
        self.start_thread()
        self.update_status()
        self._root.mainloop()


def uimain(env_data):
    gui = GUI(env_data)
    gui.run()


if __name__ == "__main__":

    try:
        # default to console on linux unless passing gui as an extra argument
        _use_gui = sys.argv[1] == 'gui'
    except IndexError:
        # default to GUI on windows
        _use_gui = platform.system() == 'Windows'

    _env_data = read_data_from_env()

    if HAS_TK and (main_is_frozen() or _use_gui):
        uimain(_env_data)
    else:
        check_config(_env_data)
        asyncio.get_event_loop().run_until_complete(main(_env_data))
