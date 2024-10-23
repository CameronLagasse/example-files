from vantbot import database

# Define the LimitedCharacterMemory class
class LimitedCharacterMemory:
    def __init__(self, channel_id, user_id, max_characters=4000):
        self.channel_id = channel_id
        self.user_id = user_id
        self.max_characters = max_characters

    def add_message(self, role, content):
        # Insert the new message into the conversation_history table
        insert_query = """
        INSERT INTO conversation_history (channel_id, user_id, role, content)
        VALUES (%s, %s, %s, %s);
        """
        database.execute_query(insert_query, (self.channel_id, self.user_id, role, content))
        
        # Trim memory if necessary
        self.trim_memory()

    def trim_memory(self):
        # Calculate total characters stored for this user in the conversation_history table
        count_query = """
        SELECT SUM(CHAR_LENGTH(content)) FROM conversation_history
        WHERE channel_id = %s AND user_id = %s;
        """
        total_characters = database.execute_query(count_query, (self.channel_id, self.user_id), fetch=True)[0][0] or 0

        # If total characters exceed the limit, remove the oldest messages
        while total_characters > self.max_characters:
            # Find the oldest message
            select_oldest_query = """
            SELECT id, CHAR_LENGTH(content) FROM conversation_history
            WHERE channel_id = %s AND user_id = %s
            ORDER BY timestamp ASC LIMIT 1;
            """
            oldest_message = database.execute_query(select_oldest_query, (self.channel_id, self.user_id), fetch=True)
            if oldest_message:
                message_id, message_length = oldest_message[0]
                # Delete the oldest message
                delete_query = """
                DELETE FROM conversation_history WHERE id = %s;
                """
                database.execute_query(delete_query, (message_id,))
                # Update total characters
                total_characters -= message_length

    def get_history(self):
        # Retrieve all messages for this user from the conversation_history table
        select_query = """
        SELECT role, content FROM conversation_history
        WHERE channel_id = %s AND user_id = %s
        ORDER BY timestamp ASC;
        """
        messages = database.execute_query(select_query, (self.channel_id, self.user_id), fetch=True)
        return [{"role": role, "content": content} for role, content in messages]