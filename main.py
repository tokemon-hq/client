import asyncio
import json
import websockets
from uniswap import Uniswap
from web3 import Web3
import logging
from dotenv import load_dotenv
import os
from time import sleep

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
gas_in_gwei = 0


def gas_price_strategy(web3, transaction_params):
    return Web3.toWei(gas_in_gwei, 'gwei')


def to_dict(dict_to_parse):
    parsed_dict = dict(dict_to_parse)
    for key, val in parsed_dict.items():
        if 'list' in str(type(val)):
            parsed_dict[key] = [parse_value(x) for x in val]
        else:
            parsed_dict[key] = parse_value(val)
    return parsed_dict


def parse_value(val):
    if 'dict' in str(type(val)).lower():
        return to_dict(val)
    elif 'HexBytes' in str(type(val)):
        return val.hex()
    else:
        return val


async def uniswap_buy_input(input_token, output_token, input_quantity, max_slippage, max_gas, account, ethereum_provider):
    # set web3 with gas price
    global gas_in_gwei
    gas_in_gwei = max_gas
    w3 = Web3(Web3.HTTPProvider(ethereum_provider))
    w3.eth.setGasPriceStrategy(gas_price_strategy)

    # set uniswap with w3 and slippage
    uniswap_wrapper = Uniswap(account['address'], account['pkey'], web3=w3, version=2, max_slippage=max_slippage)

    # trade exact input_quantity of input_token for output_token
    req = uniswap_wrapper.make_trade(Web3.toChecksumAddress(input_token), Web3.toChecksumAddress(output_token),
                                     input_quantity)
    tx = w3.eth.waitForTransactionReceipt(req)

    # reformat output
    tx_dict = to_dict(tx)
    return tx_dict


def read_data_from_env():
    load_dotenv()
    username = os.environ.get('USER_NAME')
    accounts = read_accounts_from_env()
    ethereum_provider = os.environ.get('ETHEREUM_PROVIDER')
    token = os.environ.get('TOKEN')
    base_url = os.environ.get('BASE_URL')
    return {
        "username": username,
        "accounts": accounts,
        "ethereum_provider": ethereum_provider,
        "token": token,
        "base_url": base_url
    }


def read_accounts_from_env():
    num_accounts = int(os.environ.get("NUM_ACCOUNTS"))
    accounts = {}
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
    return f"wss://{base_url}/api/v1/users/subscribe/{username}"


async def main():
    env_data = read_data_from_env()

    uri = get_connection_uri(env_data.get('base_url'), env_data.get('username'))
    accounts = env_data.get('accounts')

    connection_retry = True

    while connection_retry:
        async with websockets.connect(uri) as websocket:

            msg = {'code': 'login', 'token': env_data.get('token'), "accounts": list(accounts.keys())}

            await websocket.send(json.dumps(msg))

            msg_response = await websocket.recv()
            msg_response_dict = json.loads(msg_response)
            if msg_response_dict['code'] == 'auth_ok':
                logger.info('Authentication successful.')
                fl_exit = False
                try:
                    while not fl_exit:
                        # get in processing mode
                        msg = await websocket.recv()

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
                                msg_response = {"status": "done", "tx": tx_dict, "trading_config_id": trading_config_id,
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
        if connection_retry:
            sleep(10)


asyncio.get_event_loop().run_until_complete(main())
