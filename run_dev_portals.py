import os
import signal
import socket
import subprocess
import sys
import time

from app import PORTAL_PORTS, create_app, db, get_available_development_credentials, seed_data

ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(ROOT, '.venv', 'bin', 'python')
if not os.path.exists(PYTHON):
    PYTHON = sys.executable

PORTAL_COMMANDS = [
    ('Customer', os.path.join(ROOT, 'customer_portal.py'), PORTAL_PORTS['customer']),
    ('Admin', os.path.join(ROOT, 'admin_portal.py'), PORTAL_PORTS['admin']),
    ('Delivery', os.path.join(ROOT, 'delivery_portal.py'), PORTAL_PORTS['delivery']),
]


def portal_url(role):
    return f"http://127.0.0.1:{PORTAL_PORTS[role]}"


def print_startup_banner():
    print('', flush=True)
    print('SweetCrumbs portals are running:', flush=True)
    print(f"  Customer portal: {portal_url('customer')}", flush=True)
    print('    Use for customers to browse products, manage cart, checkout, and track orders.', flush=True)
    print(f"  Admin portal:    {portal_url('admin')}", flush=True)
    print('    Use for admins to manage products, inventory, orders, customers, and analytics.', flush=True)
    print(f"  Delivery portal: {portal_url('delivery')}", flush=True)
    print('    Use for delivery staff to view assigned orders, update delivery status, and see history.', flush=True)
    print('', flush=True)
    print('Available login credentials:', flush=True)
    for entry in get_available_development_credentials():
        print(
            f"  [{entry['role'].upper():8}] {entry['email']} / {entry['password']}"
            + (f"  ({entry['label']})" if entry['label'] else ''),
            flush=True,
        )
    print(f"  [SELF-SIGNUP] Create new customer accounts at {portal_url('customer')}/auth/register", flush=True)
    print('', flush=True)
    print('Use this launcher when you want all 3 portals together in one terminal.', flush=True)
    print('Press Ctrl+C to stop all three portals.', flush=True)


def ensure_ports_available():
    for label, _, port in PORTAL_COMMANDS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(('127.0.0.1', port))
            except OSError as exc:
                raise RuntimeError(
                    f'Port {port} is already in use, so the {label.lower()} portal cannot start. '
                    f'Stop the process using http://127.0.0.1:{port} and run this launcher again.'
                ) from exc


def prepare_database():
    previous_setting = os.environ.get('ENABLE_PORTAL_SIDECARS')
    previous_banner_setting = os.environ.get('PORTAL_LAUNCHER_CHILD')
    os.environ['ENABLE_PORTAL_SIDECARS'] = 'false'
    os.environ['PORTAL_LAUNCHER_CHILD'] = '1'
    try:
        app = create_app('development', portal_role='customer')
        from models import safe_create_all

        with app.app_context():
            safe_create_all(app)
            seed_data(app)
    finally:
        if previous_setting is None:
            os.environ.pop('ENABLE_PORTAL_SIDECARS', None)
        else:
            os.environ['ENABLE_PORTAL_SIDECARS'] = previous_setting
        if previous_banner_setting is None:
            os.environ.pop('PORTAL_LAUNCHER_CHILD', None)
        else:
            os.environ['PORTAL_LAUNCHER_CHILD'] = previous_banner_setting


def main():
    processes = []
    try:
        ensure_ports_available()
        print('Preparing database and seed data once before starting the portals...', flush=True)
        prepare_database()

        for label, script_path, _port in PORTAL_COMMANDS:
            env = os.environ.copy()
            env.setdefault('FLASK_ENV', 'development')
            env['AUTO_INIT_DB'] = 'false'
            env['ENABLE_PORTAL_SIDECARS'] = 'false'
            env['PORTAL_LAUNCHER_CHILD'] = '1'
            process = subprocess.Popen([PYTHON, script_path], cwd=ROOT, env=env)
            processes.append((label, process))
            time.sleep(0.8)

        print_startup_banner()

        while True:
            time.sleep(1)
            for label, process in processes:
                if process.poll() is not None:
                    raise RuntimeError(f'{label} portal stopped unexpectedly.')
    except KeyboardInterrupt:
        pass
    finally:
        for _, process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        for _, process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == '__main__':
    main()
