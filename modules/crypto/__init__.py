"""Crypto — real-time BTC/ETH price lookup via CoinGecko."""

import requests

from modules.base import BasePlugin


class Plugin(BasePlugin):
    name = "crypto"
    triggers = ["crypto", "bitcoin", "btc", "eth", "price"]

    def execute(self, user_input: str) -> dict:
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd"
            res = requests.get(url, timeout=5).json()
            btc = res.get("bitcoin", {}).get("usd", "N/A")
            eth = res.get("ethereum", {}).get("usd", "N/A")
            report = f"BTC: ${btc:,} | ETH: ${eth:,}"
            return {"status": "success", "output": report}
        except Exception as e:
            return {"status": "error", "output": f"Crypto lookup failed: {e}"}
