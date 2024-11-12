#!/bin/bash

# Create speedtest directory
mkdir -p /home/itadmin/speedtest

cd /home/itadmin/speedtest || {
    echo "Failed to change directory to ~/speedtest"
    exit 1
}

# Update and install packages
apt-get update
apt-get upgrade -y
apt-get install -y speedtest-cli influxdb influxdb-client python3-pip

# Install influxdb Python module
pip3 install influxdb

# Start InfluxDB server
systemctl unmask influxdb
systemctl enable influxdb
systemctl start influxdb

# Give InfluxDB time to start up
sleep 10

# Create InfluxDB database and user
if influx -execute "CREATE DATABASE internetspeed"; then
    echo "Database created successfully"
else
    echo "Failed to create database"
    exit 1
fi

if influx -execute "CREATE USER \"your-username\" WITH PASSWORD 'your-password'"; then
    echo "User created successfully"
else
    echo "Failed to create user"
    exit 1
fi

if influx -execute "GRANT ALL ON \"internetspeed\" TO \"your-username\""; then
    echo "Permissions granted successfully"
else
    echo "Failed to grant permissions"
    exit 1
fi

# Create speedtest script
cat <<'EOF' >speedtest_script.py
#!/usr/bin/env python3

import speedtest
import csv
from datetime import datetime
from influxdb import InfluxDBClient

# Create a SpeedtestClient
st = speedtest.Speedtest(secure=True)

# Get the best server
st.get_best_server()

# Function to calculate jitter
def calculate_jitter(ping_results):
    if len(ping_results) < 2:
        return 0  # Jitter is 0 if there are not enough results
    return sum(abs(ping_results[i] - ping_results[i - 1]) for i in range(1, len(ping_results))) / (len(ping_results) - 1)

# Get download and upload speeds in Mbps
download_speed = st.download() / 1024 / 1024  # Convert to Mbps
upload_speed = st.upload() / 1024 / 1024  # Convert to Mbps
ping = st.results.ping  # Ping in milliseconds

# Calculate the average download speed and upload speed
num_measurements = 24  # Adjust this value as needed
download_speeds = [download_speed]
upload_speeds = [upload_speed]

if len(download_speeds) > num_measurements:
    download_speeds.pop(0)
if len(upload_speeds) > num_measurements:
    upload_speeds.pop(0)

average_download_speed = sum(download_speeds) / len(download_speeds)
average_upload_speed = sum(upload_speeds) / len(upload_speeds)

# Run multiple ping tests and record the results
ping_results = []
for _ in range(5):  # You can adjust the number of ping tests as needed
    st.get_best_server()  # Re-select the best server for each ping test
    ping_results.append(st.results.ping)

# Calculate jitter
jitter = calculate_jitter(ping_results)

# Get the current date and time
current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Create a CSV file to store the results
csv_filename = "speedtest_results.csv"

# Write the results to the CSV file
with open(csv_filename, mode="a", newline="") as file:
    writer = csv.writer(file)
    writer.writerow([current_time, download_speed, average_download_speed, average_upload_speed, upload_speed, ping, jitter])

print("Speed test completed and results saved to", csv_filename)

# Prepare the data for InfluxDB
speed_data = [
    {
        "measurement": "internet_speed",
        "tags": {
            "host": "clustermaster"
        },
        "fields": {
            "download_speed": float(download_speed),
            "upload_speed": float(upload_speed),
            "average_download_speed": float(average_download_speed),
            "average_upload_speed": float(average_upload_speed),
            "ping": float(ping),
            "jitter": float(jitter)
        }
    }
]

# Connect to InfluxDB and write data
client = InfluxDBClient('localhost', 8086, 'your-username', 'your-password', 'internetspeed')

client.write_points(speed_data)
EOF

# Check if the script was created successfully
if [ -f "speedtest_script.py" ]; then
    echo "Python script has been created successfully"
else
    echo "Failed to create Python script"
    exit 1
fi

# Make the Python script executable
chmod +x speedtest_script.py

# Add a cron job to run the speedtest script every 5 minutes
(
    crontab -l 2>/dev/null
    echo "*/5 * * * * /usr/bin/python3 /home/itadmin/speedtest/speedtest_script.py"
) | crontab -

echo "Cron job has been set up to run every 5 minutes"%
