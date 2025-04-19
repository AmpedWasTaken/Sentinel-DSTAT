from flask import Flask, render_template, jsonify
import psutil
import time
from threading import Thread, Event
import json
import os
import argparse
from rich.console import Console
from rich.panel import Panel
from datetime import datetime

app = Flask(__name__)
console = Console()

def print_banner():
    banner = """
    ╔══════════════════════════════════════════╗
    ║             [bold blue]Sentinel-DSTAT[/bold blue]             ║
    ║     Dynamic Network Statistics Monitor    ║
    ╚══════════════════════════════════════════╝
    """
    console.print(Panel.fit(banner, border_style="blue"))

def print_status(config):
    """Print current monitoring status"""
    status = f"""
    [bold blue]Status:[/bold blue]
    • Monitoring: {'[green]Active[/green]' if config['monitoring']['enabled'] else '[red]Inactive[/red]'}
    • Interface(s): [cyan]{', '.join(config['network']['interfaces'])}[/cyan]
    • Update Interval: [yellow]{config['monitoring']['interval']}s[/yellow]
    • History Logging: {'[green]Enabled[/green]' if config['monitoring']['store_history'] else '[red]Disabled[/red]'}
    • Server: [cyan]http://{config['server']['host']}:{config['server']['port']}[/cyan]
    """
    console.print(Panel.fit(status, title="[bold]Configuration[/bold]", border_style="blue"))

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
            console.print("[green]✓[/green] Configuration loaded successfully")
            return config
    except FileNotFoundError:
        console.print("[yellow]![/yellow] Config file not found, using default configuration")
        return get_default_config()
    except json.JSONDecodeError as e:
        console.print(f"[red]✗[/red] Error parsing config file: {e}")
        return get_default_config()

def get_default_config():
    return {
        "monitoring": {
            "enabled": True,
            "interval": 1.0,
            "store_history": False,
            "history_file": "network_history.json",
            "max_history_records": 1000
        },
        "network": {
            "interfaces": ["all"],
            "bandwidth_units": True,
            "decimal_places": 2
        },
        "server": {
            "host": "0.0.0.0",
            "port": 5000,
            "debug": False
        },
        "chart": {
            "max_data_points": 30,
            "update_interval": 1000
        }
    }

# Global variables
CONFIG = None
current_stats = {
    'pps_in': 0,
    'pps_out': 0,
    'bandwidth_in': 0,
    'bandwidth_out': 0,
    'interfaces': {},
    'timestamp': 0
}
stop_event = Event()

def get_network_stats():
    if CONFIG['network']['interfaces'][0] == "all":
        net_io = psutil.net_io_counters()
        return net_io.bytes_recv, net_io.bytes_sent, net_io.packets_recv, net_io.packets_sent
    
    total_bytes_recv = total_bytes_sent = total_packets_recv = total_packets_sent = 0
    interfaces = psutil.net_io_counters(pernic=True)
    
    for interface in CONFIG['network']['interfaces']:
        if interface in interfaces:
            stats = interfaces[interface]
            total_bytes_recv += stats.bytes_recv
            total_bytes_sent += stats.bytes_sent
            total_packets_recv += stats.packets_recv
            total_packets_sent += stats.packets_sent
    
    return total_bytes_recv, total_bytes_sent, total_packets_recv, total_packets_sent

def network_monitor():
    prev_bytes_recv, prev_bytes_sent, prev_packets_recv, prev_packets_sent = get_network_stats()
    
    while not stop_event.is_set():
        try:
            time.sleep(CONFIG['monitoring']['interval'])
            
            bytes_recv, bytes_sent, packets_recv, packets_sent = get_network_stats()
            
            global current_stats
            current_stats = {
                'bandwidth_in': bytes_recv - prev_bytes_recv,
                'bandwidth_out': bytes_sent - prev_bytes_sent,
                'pps_in': packets_recv - prev_packets_recv,
                'pps_out': packets_sent - prev_packets_sent,
                'timestamp': time.time()
            }
            
            # Print real-time stats to console
            bandwidth_in = format_bytes(current_stats['bandwidth_in'])
            pps_in = format_number(current_stats['pps_in'])
            console.print(f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim] │ BW: [green]{bandwidth_in:>10}[/green] │ PPS: [yellow]{pps_in:>10}[/yellow]")
            
            if CONFIG['monitoring']['store_history']:
                save_history(current_stats)
            
            prev_bytes_recv, prev_bytes_sent = bytes_recv, bytes_sent
            prev_packets_recv, prev_packets_sent = packets_recv, packets_sent
            
        except Exception as e:
            console.print(f"[red]✗[/red] Network monitoring error: {e}")
            time.sleep(1)

def format_bytes(bytes):
    if bytes == 0:
        return "0 B/s"
    units = ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s']
    i = 0
    while bytes >= 1024 and i < len(units)-1:
        bytes /= 1024.
        i += 1
    return f"{bytes:.2f} {units[i]}"

def format_number(num):
    return f"{num:,} pps"

def save_history(stats):
    history_path = os.path.join(os.path.dirname(__file__), CONFIG['monitoring']['history_file'])
    try:
        if os.path.exists(history_path):
            with open(history_path, 'r+') as f:
                history = json.load(f)
                history['data'].append(stats)
                if len(history['data']) > CONFIG['monitoring']['max_history_records']:
                    history['data'] = history['data'][-CONFIG['monitoring']['max_history_records']:]
                f.seek(0)
                json.dump(history, f)
                f.truncate()
        else:
            with open(history_path, 'w') as f:
                json.dump({'data': [stats]}, f)
    except Exception as e:
        console.print(f"[red]✗[/red] Error saving history: {e}")

@app.route('/')
def index():
    return render_template('index.html', config=CONFIG)

@app.route('/stats')
def get_stats():
    return jsonify(current_stats)

@app.route('/config')
def get_config():
    return jsonify(CONFIG)

@app.route('/interfaces')
def get_interfaces():
    return jsonify(list(psutil.net_io_counters(pernic=True).keys()))

def parse_args():
    parser = argparse.ArgumentParser(description='Sentinel-DSTAT - Dynamic Network Statistics Monitor')
    parser.add_argument('--config', type=str, help='Path to custom config file')
    parser.add_argument('--host', type=str, help='Host to bind to')
    parser.add_argument('--port', type=int, help='Port to bind to')
    return parser.parse_args()

def main():
    global CONFIG
    
    console.clear()
    print_banner()
    
    args = parse_args()
    
    # Load configuration
    if args.config:
        config_path = args.config
        try:
            with open(config_path, 'r') as f:
                CONFIG = json.load(f)
                console.print(f"[green]✓[/green] Loaded custom config from: {config_path}")
        except Exception as e:
            console.print(f"[red]✗[/red] Error loading custom config: {e}")
            CONFIG = load_config()
    else:
        CONFIG = load_config()
    
    # Override config with command line arguments
    if args.host:
        CONFIG['server']['host'] = args.host
    if args.port:
        CONFIG['server']['port'] = args.port
    
    print_status(CONFIG)
    
    # Start monitoring thread
    monitor_thread = Thread(target=network_monitor, daemon=True)
    monitor_thread.start()
    console.print("[green]✓[/green] Network monitoring started\n")
    
    try:
        console.print("[yellow]![/yellow] Press Ctrl+C to stop the server")
        app.run(
            host=CONFIG['server']['host'],
            port=CONFIG['server']['port'],
            debug=CONFIG['server']['debug']
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]![/yellow] Received shutdown signal")
    except Exception as e:
        console.print(f"\n[red]✗[/red] Server error: {e}")
    finally:
        stop_event.set()
        monitor_thread.join(timeout=2)
        console.print("\n[red]✗[/red] Shutting down...")

if __name__ == '__main__':
    main() 