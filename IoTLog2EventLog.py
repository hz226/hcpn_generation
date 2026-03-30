import csv
from datetime import datetime, timedelta
from collections import defaultdict
import os

# =========================
# 1. Load device logs
# =========================
def load_device_logs(csv_file):
    logs = {'sensor': [], 'actuator': [], 'interaction': []}
    with open(csv_file, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['t'] = datetime.strptime(row['t'], '%Y-%m-%d %H:%M:%S')
            logs[row['type']].append(row)
    return logs

# =========================
# 2. Activity extraction
# =========================
def pi_m(log):
    return log.get('m', 'unknown')

def pi_cmd(log):
    return log.get('cmd', 'unknown')

# =========================
# 3. IoTLog2EventLog with actuator state
# =========================
def IoTLog2EventLog(device_logs, delta_t_seconds):
    delta_t = timedelta(seconds=delta_t_seconds)
    event_logs = defaultdict(lambda: {'sensor': [], 'actuator': [], 'interaction': []})
    caseID = 1

    # Track actuator states: initially all OFF
    actuator_state = {}

    # Group logs by device
    grouped_logs = defaultdict(list)
    for log in device_logs['sensor'] + device_logs['actuator']:
        grouped_logs[log['d']].append(log)
    for log in device_logs['interaction']:
        parent = log.get('d_p', log['d_s'])
        grouped_logs[parent].append(log)

    # Process logs per device
    for device, logs in grouped_logs.items():
        logs.sort(key=lambda x: x['t'])
        prev_time = None
        for log in logs:
            t = log['t']
            if prev_time is not None and (t - prev_time) > delta_t:
                caseID += 1

            if log['type'] == 'sensor':
                event_logs[device]['sensor'].append({
                    'c_s': caseID,
                    'a_s': pi_m(log),
                    't': t,
                    'val': log.get('val',''),
                    'd': log['d'],
                    'sid': log['sid']
                })
            elif log['type'] == 'actuator':
                actuator_id = log['id']
                # default state is OFF if not seen before
                cmd = pi_m(log)
                s_pre = 'dimmed' if cmd=="turn_on" else "ON"
                # For this dataset, all commands are 'turn_on', so new state is ON
                s_post = 'ON' if cmd=="turn_on" else "dimmed"
                actuator_state[actuator_id] = s_post  # update state

                event_logs[device]['actuator'].append({
                    'c_a': caseID,
                    'a_cmd': pi_m(log),
                    't': t,
                    's_pre': s_pre,
                    's_post': s_post,
                    'd': log['d'],
                    'id': actuator_id
                })
            else:  # interaction
                event_logs[device]['interaction'].append({
                    'c_i': caseID,
                    'a_i': log.get('d_s','') + "_" + log.get('cmd','') + "_" + log.get('d_t',''),
                    't': t,
                    'm_i': log.get('m_i',''),
                    'd_s': log.get('d_s',''),
                    'd_t': log.get('d_t',''),
                    'd_p': log.get('d_p','')
                })

            prev_time = t

    return event_logs

# =========================
# 4. Save separate CSVs per device folder
# =========================
def save_event_logs_per_device_folder(event_logs, output_root):
    os.makedirs(output_root, exist_ok=True)
    for device, logs_dict in event_logs.items():
        device_dir = os.path.join(output_root, device)
        os.makedirs(device_dir, exist_ok=True)

        # Sensor CSV
        sensor_file = os.path.join(device_dir, 'sensor_event_log.csv')
        sensor_fields = ['c_s','a_s','t','val','d','sid']
        with open(sensor_file,'w',newline='') as f:
            writer = csv.DictWriter(f, fieldnames=sensor_fields)
            writer.writeheader()
            for log in logs_dict['sensor']:
                log_copy = log.copy()
                log_copy['t'] = log_copy['t'].strftime('%Y-%m-%d %H:%M:%S')
                writer.writerow(log_copy)

        # Actuator CSV
        actuator_file = os.path.join(device_dir, 'actuator_event_log.csv')
        actuator_fields = ['c_a','a_cmd','t','s_pre','s_post','d','id']
        with open(actuator_file,'w',newline='') as f:
            writer = csv.DictWriter(f, fieldnames=actuator_fields)
            writer.writeheader()
            for log in logs_dict['actuator']:
                log_copy = log.copy()
                log_copy['t'] = log_copy['t'].strftime('%Y-%m-%d %H:%M:%S')
                writer.writerow(log_copy)

        # Interaction CSV
        interaction_file = os.path.join(device_dir, 'interaction_event_log.csv')
        interaction_fields = ['c_i','a_i','t','m_i','d_s','d_t','d_p']
        with open(interaction_file,'w',newline='') as f:
            writer = csv.DictWriter(f, fieldnames=interaction_fields)
            writer.writeheader()
            for log in logs_dict['interaction']:
                log_copy = log.copy()
                log_copy['t'] = log_copy['t'].strftime('%Y-%m-%d %H:%M:%S')
                writer.writerow(log_copy)

        print(f"Saved sensor, actuator, and interaction logs for device {device} in folder {device_dir}")
import argparse

# =========================
# 5. Main
# =========================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process IoT device logs into event logs.")
    parser.add_argument("--debug", type=bool, default=False, help="Enable debug mode")
    args = parser.parse_args()
    debug = False
    if not args.debug:
        exit(0)
    input_csv = 'bridge_traffic_simulation_noisy.csv' #'iot_device_logs_dataset.csv'
    output_root = 'temp_event_logs_new' #'event_logs_by_device'

    device_logs = load_device_logs(input_csv)
    event_logs = IoTLog2EventLog(device_logs, delta_t_seconds=4)
    save_event_logs_per_device_folder(event_logs, output_root)
