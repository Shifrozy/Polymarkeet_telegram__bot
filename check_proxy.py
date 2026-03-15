from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
from web3 import Web3

host = 'https://clob.polymarket.com'
key = '07165a1066e57948207c0267298d7cde866290c2e2fa61e11bd7a7f7e2205d69'
funder = '0xe86cB2e0E4615DfF6a931D87CcA89544952f1143'

client = ClobClient(host, key=key, chain_id=137, funder=funder)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)

proxy = client.get_proxy_address()
print(f'Proxy Address: {proxy}')

w3 = Web3(Web3.HTTPProvider('https://polygon-bor-rpc.publicnode.com'))
abi = [{'constant': True, 'inputs': [{'name': '', 'type': 'address'}], 'name': 'balanceOf', 'outputs': [{'name': '', 'type': 'uint256'}], 'type': 'function'}]
usdc = w3.eth.contract(address='0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359', abi=abi)

if proxy:
    bal = usdc.functions.balanceOf(proxy).call() / 1e6
    print(f'Proxy USDC Balance: {bal}')
else:
    print('No proxy found.')
