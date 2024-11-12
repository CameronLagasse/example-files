import requests
import json
import psycopg2
from datetime import datetime
import os
import time

# Database connection details
db_username = os.getenv("DB_USERNAME")
db_password = os.getenv("DB_PASSWORD")
db_host = os.getenv("DB_HOST")
db_port = os.getenv("DB_PORT")
db_database = os.getenv("DB_DATABASE")

# Google Setup
oauth2clientid = os.getenv("OAUTH2CLIENTID")
clientsecret = os.getenv("CLIENTSECRET")
projectid = os.getenv("PROJECTID")
authorization_code = os.getenv("AUTHORIZATION_CODE")
access_token = os.getenv("ACCESS_TOKEN")
refresh_token = os.getenv("REFRESH_TOKEN")

# Variables to track the previous mode and timestamp
last_mode = None
last_timestamp = None

# Energy consumption and cost parameters
btuh_per_hour = 88000  # Furnace input in BTU/h
therms_per_hour = btuh_per_hour / 100000  # Therms consumed per hour
cost_per_therm = 0.78  # Cost of natural gas in USD per therm


def request_tokens():
    global oauth2clientid
    global clientsecret
    global access_token
    global refresh_token
    try:
        with open(".mynest.json") as json_file:
            data = json.load(json_file)
            access_token = data["access_token"]
            refresh_token = data["refresh_token"]
            print("access token:", access_token)
            print("refresh token:", refresh_token)
    except FileNotFoundError:
        print(".mynest.json not found, fetching new tokens...")
        request_token_url = "https://www.googleapis.com/oauth2/v4/token"
        params = {
            "client_id": oauth2clientid,
            "client_secret": clientsecret,
            "code": authorization_code,
            "grant_type": "authorization_code",
            "redirect_uri": "https://www.google.com",
        }
        request_token_resp = requests.post(request_token_url, params=params)
        if request_token_resp.status_code != 200:
            print(request_token_resp.status_code)
        else:
            access_token = request_token_resp.json()["access_token"]
            refresh_token = request_token_resp.json()["refresh_token"]
            with open(".mynest.json", "w") as json_file:
                json.dump(request_token_resp.json(), json_file)


# Refresh access token when it expires
def refresh_access():
    global access_token
    refresh_url = "https://www.googleapis.com/oauth2/v4/token?"
    params = {
        "client_id": oauth2clientid,
        "client_secret": clientsecret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    refresh_resp = requests.post(refresh_url, params=params)

    if refresh_resp.status_code != 200:
        print(f"Error refreshing token: {refresh_resp.status_code} {refresh_resp.text}")
    else:
        access_token = refresh_resp.json()["access_token"]
        print(f"New access token: {access_token}")


# Get current thermostat data
def get_device_status():
    url = (
        "https://smartdevicemanagement.googleapis.com/v1/enterprises/"
        + projectid
        + "/devices"
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + access_token,
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(resp.status_code)
        refresh_access()
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + access_token,
        }
        resp = requests.get(url, headers=headers)
    nest = resp.json()

    # Extract temperature, humidity, and mode data
    temperature = (
        nest["devices"][0]["traits"]["sdm.devices.traits.Temperature"][
            "ambientTemperatureCelsius"
        ]
        * 9
        / 5
        + 32
    )  # Celsius to Fahrenheit
    humidity = nest["devices"][0]["traits"]["sdm.devices.traits.Humidity"][
        "ambientHumidityPercent"
    ]
    mode = nest["devices"][0]["traits"]["sdm.devices.traits.ThermostatHvac"][
        "status"
    ]  # heating, cooling, off

    return temperature, humidity, mode


def calculate_heating_cost(duration_minutes):
    # Convert duration from minutes to hours
    duration_hours = duration_minutes / 60
    # Calculate the total therms consumed
    therms_consumed = therms_per_hour * duration_hours
    # Calculate the total cost
    heating_cost = therms_consumed * cost_per_therm
    return heating_cost


# Save mode duration to DB
def save_mode_duration(mode, duration_minutes):
    """Save the mode duration and cost to the database."""
    try:
        # Calculate heating cost if the mode is HEATING, otherwise set it to 0
        if mode == "HEATING":
            heating_cost = calculate_heating_cost(duration_minutes)
            print(f"Heating cost for {duration_minutes} minutes: ${heating_cost:.2f}")
        else:
            heating_cost = 0  # No heating cost when the mode is not "HEATING"

        # Connect to your postgres DB
        connection = psycopg2.connect(
            host=db_host, dbname=db_database, user=db_username, password=db_password
        )
        cursor = connection.cursor()

        # Insert data into the database, including the calculated heating cost
        insert_query = """
        INSERT INTO mode_duration (mode, duration_minutes, cost, timestamp)
        VALUES (%s, %s, %s, %s)
        """
        cursor.execute(
            insert_query, (mode, duration_minutes, heating_cost, datetime.now())
        )

        # Commit the transaction
        connection.commit()
        print(
            f"Mode duration ({mode}, {duration_minutes} mins, ${heating_cost:.2f} cost) inserted successfully!"
        )

    except Exception as e:
        print("Error while inserting data into PostgreSQL:", e)

    finally:
        # Close communication with the database
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def get_last_mode_and_timestamp():
    """Get the last recorded mode and timestamp from the database."""
    global last_mode, last_timestamp
    try:
        connection = psycopg2.connect(
            host=db_host, dbname=db_database, user=db_username, password=db_password
        )
        cursor = connection.cursor()

        cursor.execute(
            "SELECT mode, timestamp FROM nest_device_data ORDER BY timestamp DESC LIMIT 1"
        )
        result = cursor.fetchone()
        if result:
            last_mode, last_timestamp = result
        else:
            last_mode, last_timestamp = None, None
        print(f"Last mode from get_last_mode function: {last_mode}")
    except Exception as e:
        print("Error while fetching last mode and timestamp:", e)

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# Main logic for tracking mode changes and calculating duration
def main():
    global last_mode, last_timestamp

    # Get the last mode and timestamp from the database
    get_last_mode_and_timestamp()

    # Retrieve current temperature, humidity, and mode
    temperature, humidity, mode = get_device_status()

    current_timestamp = datetime.now()

    # If the mode has changed, calculate and save the duration
    if last_mode is not None:
        duration = (
            current_timestamp - last_timestamp
        ).total_seconds() / 60  # Duration in minutes
        print(f"Mode is still {last_mode}, duration: {duration:.2f} minutes.")
        save_mode_duration(last_mode, duration)

    # Save the current data (temperature, humidity, and mode) to the database
    save_to_db(temperature, humidity, mode)

    # Update the last mode and timestamp in the database
    last_mode = mode
    last_timestamp = current_timestamp


# Save temperature and humidity data to PostgreSQL (from original script)
def save_to_db(temperature, humidity, mode):
    try:
        connection = psycopg2.connect(
            host=db_host, dbname=db_database, user=db_username, password=db_password
        )
        cursor = connection.cursor()

        # Modify your insert query to include mode
        insert_query = """
        INSERT INTO nest_device_data (temperature, humidity, mode, timestamp)
        VALUES (%s, %s, %s, %s)
        """
        cursor.execute(insert_query, (temperature, humidity, mode, datetime.now()))

        connection.commit()
        print(
            f"Temperature:{temperature}, humidity:{humidity}, and mode:{mode} data inserted successfully!"
        )
    except Exception as e:
        print("Error while inserting data:", e)
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


if __name__ == "__main__":
    main()
