from htmlslacker import HTMLSlacker
import markdown
import os
import re
from slack_sdk.signature import SignatureVerifier
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from vantbot import variables
from vantbot import database
from vantbot import file_ops
from vantbot import llama
from vantbot import giphy

signing_secret = os.getenv("SLACK_SIGNING_SECRET")
verifier = SignatureVerifier(signing_secret)

# Function to fix formatting for Slack
def format_for_slack(text):

    text = HTMLSlacker(markdown.markdown(text)).get_output()
    return text.strip()

def verify_and_parse_slack_request(request):
    """
    Verifies the Slack request signature and handles URL verification challenge.
    Returns a tuple (event_data, response) where:
    - event_data is the parsed event data or None if invalid.
    - response is a Flask response to return immediately (if needed) or None if verification is successful.
    """
    # Verify the request signature
    if not verifier.is_valid_request(request.get_data(), request.headers):
        return None, ("Request verification failed", 400)

    event_data = request.json

    # Handle Slack URL verification challenge
    if "challenge" in event_data:
        variables.app.logger.info("Challenge received")
        return None, jsonify({"challenge": event_data["challenge"]})

    event = event_data.get("event")
    if not event:
        return None, jsonify({"status": "no_event"})

    return event_data, None

def ignore_bot_messages(user_id, bot_user_id):
    """
    Checks if the user ID matches the bot's user ID.
    If the message is from the bot itself, logs the info and returns a Flask response.
    Returns (True, response) if the message should be ignored.
    Returns (False, None) if the message should be processed further.
    """
    if user_id == bot_user_id:
        variables.app.logger.info("Message from myself, ignoring")
        return True, jsonify({"status": "ignored"})
    return False, None

def handle_entry_command(event, user_id, user_name, channel_id, thread_ts):
    """
    Handles the !entry command by extracting the content, checking permissions, 
    and storing the entry in the database.
    
    Returns a Flask response indicating success or failure.
    """
    if event.get("text", "").startswith("!entry"):
        # Check if the user has permission to use the !entry command
        if database.check_user_permission(user_id, "use_entry_command"):
            # Extract the content after the !entry command
            entry_content = event.get("text")[len("!entry"):].strip()
            
            # Store entry in the database
            insert_entry_query = """
            INSERT INTO entry_history (user_id, user_name, entry_content)
            VALUES (%s, %s, %s)
            """
            database.execute_query(insert_entry_query, (user_id, user_name, entry_content))
            
            # Log the action and notify the user
            variables.app.logger.info(f"Stored entry from {user_name}: {entry_content}")
            variables.client.chat_postMessage(channel=channel_id, text="Added entry to database.", thread_ts=thread_ts)
            return jsonify({"status": "entry_stored"})
        else:
            # If the user lacks permission, send an error message
            variables.client.chat_postMessage(channel=channel_id, text="You do not have permission to use this command.", thread_ts=thread_ts)
            return jsonify({"status": "permission_denied"})
    return None  # Return None if it's not an entry command

def handle_rwe_recruit_command(event, user_id, user_name, channel_id, thread_ts):
    """
    Handles the !rwe-recruit [site-id] command by extracting the site_id,
    checking permissions, and passing the site_id to a BigQuery function for processing.
    
    Returns a Flask response indicating success or failure.
    """
    if event.get("text", "").startswith("!rwe-recruit"):
        # Check if the user has permission to use the !rwe-recruit command
        if database.check_user_permission(user_id, "use_rwe_recruit_command"):
            # Extract the site_id after the !rwe-recruit command
            command_parts = event.get("text").split()
            if len(command_parts) > 1:
                site_id = command_parts[1].strip()  # Get the site_id from the command

                # Call the function that processes the site_id with BigQuery
                #try:
                 #   bigquery_result = process_site_id_with_bigquery(site_id)
                  #  variables.app.logger.info(f"Processed site_id {site_id} with BigQuery")

                    # Notify the user that the command was successfully processed
                variables.client.chat_postMessage(channel=channel_id, text=f"Site {site_id} successfully processed.", thread_ts=thread_ts)
                return jsonify({"status": "site_processed", "site_id": site_id})
                #except Exception as e:
                  #  variables.app.logger.error(f"Error processing site_id {site_id}: {str(e)}")
                  #  variables.client.chat_postMessage(channel=channel_id, text=f"Failed to process site {site_id}.", thread_ts=thread_ts)
                  #  return jsonify({"status": "processing_failed", "error": str(e)})
            else:
                # Handle missing site_id
                variables.client.chat_postMessage(channel=channel_id, text="You must provide a site ID after the !rwe-recruit command.", thread_ts=thread_ts)
                return jsonify({"status": "missing_site_id"})
        else:
            # If the user lacks permission, send an error message
            variables.client.chat_postMessage(channel=channel_id, text="You do not have permission to use this command.", thread_ts=thread_ts)
            return jsonify({"status": "permission_denied"})
    
    return None  # Return None if it's not an rwe-recruit command

def handle_file_uploads(event, user_name, channel_id, message_ts, user_id, bot_user_id, channel_type):
    """
    Handles file uploads by processing each file received if the bot is mentioned.
    
    Returns a Flask response indicating success or failure.
    """
    # Check if files are present in the event
    if event.get("files"):
        variables.app.logger.info(f"Received a file from user: {user_name}")
        
        # Check if the bot was mentioned or if it's a direct message (channel_type == "im")
        if event.get("type") == "app_mention" or channel_type == "im":
            # Get the list of files
            files = event.get("files")
            
            if files:  # Check if the files list is not empty
                variables.app.logger.info(f"Number of files received: {len(files)}")
                
                # Loop through each file in the list
                for file in files:
                    file_id = file.get("id")  # Get the 'id' of the current file
                    
                    if file_id:
                        variables.app.logger.info(f"Processing File ID: {file_id} in Channel: {channel_id}")
                        file_ops.handle_file_upload(
                            file_id, 
                            channel_id, 
                            message_ts, 
                            event.get("text", "").replace(f"<@{bot_user_id}>", "").strip(), 
                            user_id, 
                            bot_user_id
                        )
                    else:
                        variables.app.logger.error("No file ID found for one of the files")
                
                return jsonify({"status": "files_received"})
            else:
                variables.app.logger.error("No files found")
                return jsonify({"status": "no_files_found"})
    return None  # Return None if there are no files to process

def handle_mentions_or_dms(event, event_data, channel_type, channel_id, message_ts, user_name, bot_user_id, thread_ts, memory):
    if "event" in event_data and event.get("type") in ["app_mention", "message"]:
        if channel_type == "im" or event.get("type") == "app_mention":
            query = "SELECT COUNT(*) FROM responded_messages WHERE message_ts = %s"
            if database.execute_query(query, (message_ts,), fetch=True)[0][0] > 0:
                variables.app.logger.info("Already responded to this message, ignoring")
                return jsonify({"status": "already_responded"})

            variables.app.logger.info(f"Responding to a mention or DM from {user_name}")
            insert_query = "INSERT INTO responded_messages (message_ts) VALUES (%s)"
            database.execute_query(insert_query, (message_ts,))

            # Get user input
            if channel_type == "im":
                user_input = event.get("text")
                response_ts = message_ts  # Respond in the main channel for DMs
            else:
                user_input = event.get("text").replace(f"<@{bot_user_id}>", "")
                response_ts = thread_ts if thread_ts else message_ts  # Use thread_ts if present, else main message timestamp

            # Ensure user_input is not None
            if user_input is None:
                variables.app.logger.error("No text found in the event.")
                return jsonify({"status": "no_text_found"})

            user_input = user_input.strip()

            # Use the `memory` instance to add messages
            memory.add_message("user", f"{user_name}: {user_input}")

            # Get conversation history
            conversation_history = memory.get_history()

            # Get response from Ollama
            ollama_response = llama.chat_with_ollama(variables.ollama_client, variables.ollama_model, conversation_history)

            variables.app.logger.info(f"RESPONSE FROM OLLAMA: {ollama_response}")

            # Check if the response contains "content"
            if "content" in ollama_response:
                response_text = ollama_response["content"]

                # Format the response for Slack
                formatted_response = format_for_slack(response_text)

                # Detect and handle /giphy requests
                giphy_match = re.search(r"/giphy\s+(\w+)", formatted_response)
                if giphy_match:
                    giphy_keyword = giphy_match.group(1)
                    giphy_url = giphy.get_giphy(giphy_keyword)

                    if giphy_url:
                        # Post the Giphy response to the same thread_ts or message_ts as other responses
                        variables.client.chat_postMessage(channel=channel_id, text=giphy_url, thread_ts=response_ts if thread_ts else None)
                    else:
                        variables.client.chat_postMessage(channel=channel_id, text="Could not find a Giphy for that query.", thread_ts=response_ts if thread_ts else None)

                    # Remove the /giphy part from the response text
                    formatted_response = re.sub(r"/giphy\s+\w+", "", formatted_response).strip()


                # If there's any remaining response text, post it
                if formatted_response:
                    memory.add_message("assistant", formatted_response)

                    # Store the bot's response in the conversation history
                    insert_query = """
                    INSERT INTO conversation_history (channel_id, user_id, role, content)
                    VALUES (%s, %s, %s, %s)
                    """
                    database.execute_query(insert_query, (channel_id, bot_user_id, "assistant", formatted_response))

                    # Post the response to Slack
                    try:
                        variables.client.chat_postMessage(channel=channel_id, text=formatted_response, thread_ts=response_ts if thread_ts else None, mrkdwn=True)
                    except SlackApiError as e:
                        variables.app.logger.error(f"Error posting message: {e.response['error']}")
            else:
                variables.app.logger.error(f"Ollama response did not contain 'content': {ollama_response}")

    return jsonify({"status": "handled"})