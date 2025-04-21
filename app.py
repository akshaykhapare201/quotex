from flask import Flask, jsonify
import asyncio
import time
from quotexapi.utils.processor import (
    process_candles,
    get_color,
    aggregate_candle
)
from quotexapi.config import credentials
from quotexapi.stable_api import Quotex

app = Flask(__name__)

# Initialize Quotex client
email, password = credentials()
client = Quotex(
    email=email,
    password=password,
    lang="pt",  # Default pt -> Português.
)

async def get_candle(asset="CHFJPY_otc", offset=60, period=60):
    """Fetch candle data from Quotex API
    
    Args:
        asset (str): Trading asset name
        offset (int): Time offset in seconds
        period (int): Candle period in seconds
        
    Returns:
        list: List of candle data
    """
    check_connect, message = await client.connect()
    if check_connect:
        end_from_time = time.time()
        candles = await client.get_candles(asset, end_from_time, offset, period)
        if len(candles) > 0:
            return candles
        else:
            print("No candles.")
            return []
    print("Connection failed.")
    return []

# Helper function to run async functions in Flask
def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

@app.route('/candles', methods=['GET'])
def get_candles():
    """API endpoint to get candle data"""
    candles = run_async(get_candle())
    return jsonify({
        'status': 'success',
        'data': candles,
        'count': len(candles)
    })

@app.route('/api/candles/<asset>', methods=['GET'])
def get_candles_by_asset(asset):
    """API endpoint to get candle data for a specific asset"""
    candles = run_async(get_candle(asset=asset))
    return jsonify({
        'status': 'success',
        'asset': asset,
        'data': candles,
        'count': len(candles)
    })

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'status': 'success',
        'message': 'Quotex API Server is running',
        'endpoints': [
            '/api/candles',
            '/api/candles/<asset>'
        ]
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3000)