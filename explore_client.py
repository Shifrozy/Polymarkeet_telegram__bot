from py_clob_client.client import ClobClient
import json

host = 'https://clob.polymarket.com'
key = '07165a1066e57948207c0267298d7cde866290c2e2fa61e11bd7a7f7e2205d69'
funder = '0xe86cB2e0E4615DfF6a931D87CcA89544952f1143'

client = ClobClient(host, key=key, chain_id=137, funder=funder)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)

try:
    # Most professional way to get it
    resp = client.get_api_key()
    print(f"API Key Response: {resp}")
    
    # Check profile
    profile = client.get_proxy_address() # Wait, I tried this.
except Exception as e:
    print(f"Error: {e}")

# Trying another way - checking the response of create_api_key or similar
# Actually let's just use the address directly from public record if possible, 
# but I'll try to find the attribute in client
print(dir(client))
