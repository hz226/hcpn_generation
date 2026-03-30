import subprocess

# Run the first script (e.g., generate clean CSV)
subprocess.run(["python", "merge_event_logs_by_device.py"], check=True)

# Run the second script (e.g., add noise to CSV)
subprocess.run(["python", "test.py"], check=True)

print("Both scripts have completed successfully!")
