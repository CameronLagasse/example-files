from vantbot import variables
from vantbot import database
from vantbot import llava
from vantbot import llama
import main
from slack_sdk.errors import SlackApiError
import requests
import io
import pdfplumber
import pandas as pd
from vantbot import LimitedCharacterMemory

def handle_file_upload(file_id, channel_id, message_ts, user_input, user_id, bot_user_id):
    try:
         # Create an instance of the memory class with channel_id and user_id
        memory = LimitedCharacterMemory.LimitedCharacterMemory(channel_id=channel_id, user_id=user_id, max_characters=4000)
        # Add or update the user info
        user_name = database.upsert_user_info(user_id)

        # Add user input to memory
        memory.add_message("user", f"{user_name}: {user_input}")

        # Get file info from Slack
        file_info = variables.client.files_info(file=file_id)

        # Download the file
        file_url = file_info["file"]["url_private"]
        headers = {"Authorization": f"Bearer {variables.slack_token}"}
        response = requests.get(file_url, headers=headers)

        variables.app.logger.info(f"Downloaded file size: {len(response.content)} bytes")
        variables.app.logger.info(f"File timestamp (string): {message_ts}")

        # Check if the file has already been processed
        query = "SELECT COUNT(*) FROM responded_messages WHERE message_ts = %s"
        count = database.execute_query(query, (message_ts,), fetch=True)[0][0]
        if count > 0:
            variables.app.logger.info("File has already been processed, ignoring.")
            return  # Exit if this file has already been responded to

        # Store the file timestamp to avoid duplicate responses
        insert_query = "INSERT INTO responded_messages (message_ts) VALUES (%s)"
        database.execute_query(insert_query, (message_ts,))  # Store as string

        # Check the file type and extract content
        file_type = file_info["file"]["mimetype"]
        url_private = file_info["file"]["url_private"]
        
        # Respond to image uploads
        if "image/png" in file_type or "image/jpeg" in file_type:
            variables.app.logger.info("Processing image upload.")
            # Respond to the image upload
            response_text = llava.chat_with_llava(variables.ollama_client, variables.llava_model, user_input, url_private, variables.slack_token)
            # Add bot's response to memory
            memory.add_message("assistant", response_text)
            variables.client.chat_postMessage(channel=channel_id, text=response_text)
        
        elif "application/pdf" in file_type:
            variables.app.logger.info("Processing PDF upload.")
            response_text = extract_text_from_file(response.content, file_type)
            response_from_ollama = analyze_file_content_with_ollama(user_input + "\n" + response_text)["content"]
            # Add bot's response to memory
            memory.add_message("assistant", response_from_ollama)
            variables.client.chat_postMessage(channel=channel_id, text=response_from_ollama)
        
        elif "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in file_type or "application/vnd.ms-excel" in file_type:
            variables.app.logger.info("Processing Excel upload.")
            response_text = extract_text_from_file(response.content, file_type)
            response_from_ollama = analyze_file_content_with_ollama(user_input + "\n" + response_text)["content"]
            # Add bot's response to memory
            memory.add_message("assistant", response_from_ollama)
            variables.client.chat_postMessage(channel=channel_id, text=response_from_ollama)
        
        else:
            variables.client.chat_postMessage(channel=channel_id, text="Sorry, I can only analyze image, PDF, and Excel files.")
        
        memory = None

    except SlackApiError as e:
        variables.app.logger.error(f"Error fetching file: {e.response['error']}")
    except Exception as e:
        variables.app.logger.error(f"Error handling file upload: {str(e)}")

def extract_text_from_file(file_content, file_type):
    # Extract text from file content based on its type
    if file_type == "application/pdf":
        # Use pdfplumber for PDF extraction
        with pdfplumber.open(io.BytesIO(file_content)) as pdf:
            return "\n".join(page.extract_text() for page in pdf.pages if page.extract_text())
    
    elif file_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" or file_type == "application/vnd.ms-excel":
        # Use pandas to read Excel files
        excel_data = pd.read_excel(io.BytesIO(file_content))
        return excel_data.to_string()  # Convert dataframe to string
    
    else:
        # If it's a plain text file
        return file_content.decode("utf-8")

def analyze_file_content_with_ollama(content):
    # Analyze the content using the Ollama model
    return llama.chat_with_ollama(variables.ollama_client, variables.ollama_model, [{"role": "user", "content": content}])