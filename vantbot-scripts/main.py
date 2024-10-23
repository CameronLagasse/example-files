import ollama
from ollama import Client
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier
from flask import Flask, request, jsonify
import psycopg2
import os
import logging
from vantbot import variables
from vantbot import database
from vantbot import LimitedCharacterMemory
from vantbot import chat_functions

variables.app = Flask(__name__)

logging.basicConfig(level=logging.INFO)  # This will log DEBUG and above to stdout
variables.app.logger.setLevel(logging.INFO)        # Set Flask logger to DEBUG level as well

# Initialize Slack client
variables.slack_token = os.getenv("SLACK_BOT_TOKEN")
variables.client = WebClient(token=variables.slack_token)

# Ollama client setup
ollama_host = "https://ollama.example.com"  # Internal Ollama server URL
variables.ollama_model = "llama3.1:8b"
variables.ollama_client = Client(host=ollama_host)
variables.llava_model = "llava:7b"

# Giphy API setup
giphy_api_key = os.getenv("GIPHY_API_KEY")
giphy_url = "https://api.giphy.com/v1/gifs/search"

# PostgreSQL connection setup
db_connection = psycopg2.connect(
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT")
)

db_connection.autocommit = True

# Set the database connection in the database module
database.set_db_connection(db_connection)

# Create tables after establishing the connection
database.create_tables()

# Create groups and permissions
database.create_group('administrators')
database.create_group('rwe-users')
database.assign_users_to_group_from_file('groups/admin_users.txt', 'administrators')
database.assign_users_to_group_from_file('groups/rwe_users.txt', 'rwe-users')

# Add permission for !entry command to the administrators group
database.add_permission_to_group("administrators", "use_entry_command")

# Add permission for !rwe-recruit command to the rwe-users group
database.add_permission_to_group("rwe-users", "use_rwe_recruit_command")

@variables.app.route("/slack/events", methods=["POST"])
def slack_events():
    # Use the helper function to verify the request and handle the challenge
    event_data, response = chat_functions.verify_and_parse_slack_request(request)
    if response:
        return response  # Return early if the request verification failed or challenge was handled

    event = event_data.get("event") if event_data else None
    if not event:
        return jsonify({"status": "no_event"})

    user_id = event.get("user")
    bot_user_id = variables.client.auth_test()["user_id"]
    channel_id = event.get("channel")
    message_ts = event.get("ts")
    thread_ts = event.get("thread_ts")  # Check if this message is part of a thread
    channel_type = event.get("channel_type")  # Check if it's a DM or public message
    files_ts = ""

    # Check if the message is from the bot itself
    should_ignore, response = chat_functions.ignore_bot_messages(user_id, bot_user_id)
    if should_ignore:
        return response  # Return early if the message should be ignored

    # Add or update the user info
    user_name = database.upsert_user_info(user_id)

    # Log the username interacting with the bot
    variables.app.logger.info(f"Interacting with user: {user_name} (ID: {user_id})")

    # Handle the !entry command
    entry_response = chat_functions.handle_entry_command(event, user_id, user_name, channel_id, thread_ts)
    if entry_response:
        return entry_response  # Return if the !entry command was processed
    
    # Handle the !rwe-recruit command
    rwe_recruit_response = chat_functions.handle_rwe_recruit_command(event, user_id, user_name, channel_id, thread_ts)
    if rwe_recruit_response:
        return rwe_recruit_response # Return if the !rwe-recruit command was processed


  # Handle file uploads
    file_response = chat_functions.handle_file_uploads(event, user_name, channel_id, message_ts, user_id, bot_user_id, channel_type)
    if file_response:
        return file_response  # Return if file uploads were processed

    # Create an instance of the memory class with channel_id and user_id
    memory = LimitedCharacterMemory.LimitedCharacterMemory(channel_id=channel_id, user_id=user_id, max_characters=4000)

    # Handle mentions or DMs
    mention_response = chat_functions.handle_mentions_or_dms(event, event_data, channel_type, channel_id, message_ts, user_name, bot_user_id, thread_ts, memory)
    if mention_response:
        return mention_response


    return jsonify({"status": "ok"})

if __name__ == "__main__":
    variables.app.run(host="0.0.0.0", port=3000)