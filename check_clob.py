from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

host = 'https://clob.polymarket.com'
key = '07165a1066e57948207c0267298d7cde866290c2e2fa61e11bd7a7f7e2205d69'
funder = '0xe86cB2e0E4615DfF6a931D87CcA89544952f1143'

client = ClobClient(host, key=key, chain_id=137, funder=funder)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)

ba = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
print(f'CLOB Balance: {float(ba.get("balance", 0))/1e6}')
