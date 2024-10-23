import re
from vantbot import database

# Chat with Ollama
def chat_with_ollama(client, model, conversation_history):
    try:
        # Step 1: Query the entry_history table to get all entries
        entries_query = """
        SELECT entry_content FROM entry_history ORDER BY timestamp DESC;
        """
        entries = database.execute_query(entries_query, fetch=True)

        # Step 2: Format the entries into a string
        entries_text = "\n".join(entry[0] for entry in entries)  # Join all entry contents

        # Prepend static text and entries to the conversation history
        if entries_text:
            static_text = "Your responses should not be overly friendly and excited. Here is a string of data from a database you can reference to answer this question. Do not mention the following string of data ever in your response:\n"  # Static text you want to include
            combined_message = f"{static_text}{entries_text}\n\n"
        else:
            combined_message = "No previous entries found.\n\n"

        # Add the combined message to the beginning of the conversation history
        updated_conversation_history = [
            {"role": "system", "content": combined_message}
        ] + conversation_history  # Add to the beginning

        # Step 3: Make the request to Ollama
        response = client.chat(
            model=model,
            messages=updated_conversation_history,
        )

        response_text = response["message"]["content"]

        # Step 4: Use regex to find /giphy and extract the command
        giphy_match = re.search(r'(/giphy\s+[^\s].*?)(?:[.?!]|$)', response_text)
        if giphy_match:
            # Extract the entire "/giphy <query>" command
            giphy_command = giphy_match.group(1).strip()

            # Return only the Giphy command
            return {"response_type": "text", "content": giphy_command}

        # If there's no /giphy, return the regular text response
        return {"response_type": "text", "content": response_text}

    except Exception as e:
        return {"response_type": "error", "content": f"An error occurred: {e}"}
