from flask import Flask, jsonify, request
import asyncio
import time
import os
from functools import wraps
from concurrent.futures import TimeoutError
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

# Connection pool to reuse connections
connection_pool = {}
# Default timeout in seconds
DEFAULT_TIMEOUT = 25

async def get_candle(asset="CHFJPY_otc", offset=60, period=60, timeout=DEFAULT_TIMEOUT):
    """Fetch candle data from Quotex API with timeout handling
    
    Args:
        asset (str): Trading asset name
        offset (int): Time offset in seconds
        period (int): Candle period in seconds
        timeout (int): Timeout in seconds
        
    Returns:
        list: List of candle data
    """
    try:
        # Use connection from pool if available
        if asset in connection_pool and connection_pool[asset]['connected']:
            print(f"Using existing connection for {asset}")
            client_instance = connection_pool[asset]['client']
        else:
            print(f"Creating new connection for {asset}")
            client_instance = client
            check_connect, message = await asyncio.wait_for(client_instance.connect(), timeout=timeout)
            if check_connect:
                connection_pool[asset] = {
                    'client': client_instance,
                    'connected': True,
                    'last_used': time.time()
                }
            else:
                print(f"Connection failed: {message}")
                return []
        
        # Get candles with timeout
        end_from_time = time.time()
        candles = await asyncio.wait_for(
            client_instance.get_candles(asset, end_from_time, offset, period),
            timeout=timeout
        )
        
        # Update last used time
        if asset in connection_pool:
            connection_pool[asset]['last_used'] = time.time()
            
        if len(candles) > 0:
            return candles
        else:
            print("No candles.")
            return []
    except TimeoutError:
        print(f"Timeout error for {asset}")
        # Mark connection as failed
        if asset in connection_pool:
            connection_pool[asset]['connected'] = False
        return []
    except Exception as e:
        print(f"Error fetching candles for {asset}: {str(e)}")
        return []

# Helper function to run async functions in Flask with timeout
def run_async(coro, timeout=DEFAULT_TIMEOUT):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Create a task with timeout
        return asyncio.wait_for(coro, timeout=timeout, loop=loop)
    except asyncio.TimeoutError:
        print("Operation timed out")
        return []
    except Exception as e:
        print(f"Error in async operation: {str(e)}")
        return []
    finally:
        loop.close()

# Decorator for API endpoints with timeout handling
def async_endpoint(timeout=DEFAULT_TIMEOUT):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            # Get custom timeout from query parameters if provided
            custom_timeout = request.args.get('timeout', timeout, type=int)
            # Ensure timeout is within reasonable limits
            if custom_timeout > 55:  # Gunicorn default worker timeout is 60s
                custom_timeout = 55
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    asyncio.wait_for(f(*args, **kwargs), timeout=custom_timeout)
                )
                return result
            except asyncio.TimeoutError:
                return jsonify({
                    'status': 'error',
                    'message': 'Request timed out',
                    'data': []
                }), 408  # Request Timeout
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e),
                    'data': []
                }), 500  # Internal Server Error
            finally:
                loop.close()
        return wrapped
    return decorator

@app.route('/candles', methods=['GET'])
@async_endpoint()
async def get_candles():
    """API endpoint to get candle data with timeout handling"""
    # Get parameters from request
    offset = request.args.get('offset', 60, type=int)
    period = request.args.get('period', 60, type=int)
    timeout = request.args.get('timeout', DEFAULT_TIMEOUT, type=int)
    
    candles = await get_candle(offset=offset, period=period, timeout=timeout)
    return jsonify({
        'status': 'success',
        'data': candles,
        'count': len(candles)
    })

@app.route('/api/candles/<asset>', methods=['GET'])
@async_endpoint()
async def get_candles_by_asset(asset):
    """API endpoint to get candle data for a specific asset with timeout handling"""
    # Get parameters from request
    offset = request.args.get('offset', 60, type=int)
    period = request.args.get('period', 60, type=int)
    timeout = request.args.get('timeout', DEFAULT_TIMEOUT, type=int)
    
    candles = await get_candle(asset=asset, offset=offset, period=period, timeout=timeout)
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

# Periodic task to clean up stale connections
async def cleanup_connections():
    """Remove connections that haven't been used for a while"""
    while True:
        current_time = time.time()
        stale_connections = []
        for asset, conn_info in connection_pool.items():
            # If connection hasn't been used in 10 minutes, mark for cleanup
            if current_time - conn_info['last_used'] > 600:  # 10 minutes
                stale_connections.append(asset)
        
        # Remove stale connections
        for asset in stale_connections:
            print(f"Removing stale connection for {asset}")
            del connection_pool[asset]
        
        # Sleep for 5 minutes before next cleanup
        await asyncio.sleep(300)  # 5 minutes

# Start cleanup task
def start_cleanup_task():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(cleanup_connections())
    loop.run_forever()

# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'connections': len(connection_pool),
        'uptime': time.time()
    })

if __name__ == '__main__':
    # Start cleanup task in a separate thread
    import threading
    cleanup_thread = threading.Thread(target=start_cleanup_task, daemon=True)
    cleanup_thread.start()
    
    # Get port from environment variable for cloud deployment
    port = int(os.environ.get('PORT', 3000))
    app.run(debug=True, host='0.0.0.0', port=port)