import os
import csv
from datetime import datetime


def first_non_empty(row, cols):
    for col in cols:
        if col in row and row[col] not in (None, ''):
            return row[col]
    return None


def get_device_value(row):
    if row.get('d') not in (None, ''):
        return row.get('d')
    return row.get('d_p')


def get_type_from_filename(filename):
    name = filename.lower()

    if 'actuator' in name:
        return 'actuator'
    elif 'sensor' in name:
        return 'sensor'
    elif 'interaction' in name:
        return 'interaction'
    else:
        # fallback → prefix before first underscore
        return filename.split('_')[0]


def merge_device_csvs_sorted(device_folder, output_file):
    csv_files = [f for f in os.listdir(device_folder) if f.endswith('.csv')]
    merged_rows = []
    all_columns = set()

    for file in csv_files:
        file_path = os.path.join(device_folder, file)
        file_type = get_type_from_filename(file)

        with open(file_path, newline='', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)

            for row in reader:
                # Normalize blanks → None
                row = {k: (v if v != '' else None) for k, v in row.items()}

                # Derived columns
                row['c'] = first_non_empty(row, ['c_a', 'c_i', 'c_s'])
                row['a'] = first_non_empty(row, ['a_i', 'a_s', 'a_cmd'])
                row['device'] = get_device_value(row)
                row['type'] = file_type

                # Normalize timestamp for sorting
                if 't' in row and row['t']:
                    try:
                        row['_t_sort'] = datetime.strptime(
                            row['t'], '%Y-%m-%d %H:%M:%S'
                        )
                    except ValueError:
                        row['_t_sort'] = None
                else:
                    row['_t_sort'] = None

                merged_rows.append(row)
                all_columns.update(row.keys())

    # Ensure derived columns included
    all_columns.update(['c', 'a', 'device', 'type'])

    # Sort by timestamp (None last)
    merged_rows.sort(key=lambda x: (x['_t_sort'] is None, x['_t_sort']))

    # Remove temp sort column
    for row in merged_rows:
        row.pop('_t_sort', None)

    # Nice column ordering
    preferred = ['device', 'type', 'c', 'a', 't']
    remaining = [c for c in all_columns if c not in preferred]
    final_columns = preferred + sorted(remaining)

    # Write output
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=final_columns)
        writer.writeheader()
        writer.writerows(merged_rows)

    print(f"Merged CSV saved to {output_file}")


def merge_all_devices_sorted(root_folder, output_root):
    os.makedirs(output_root, exist_ok=True)

    for device in os.listdir(root_folder):
        device_folder = os.path.join(root_folder, device)

        if os.path.isdir(device_folder):
            output_file = os.path.join(output_root, f"{device}_merged.csv")
            merge_device_csvs_sorted(device_folder, output_file)


# Example usage
merge_all_devices_sorted('./', './')
