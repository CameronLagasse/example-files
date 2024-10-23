import psycopg2
from psycopg2 import sql
import os
from vantbot import variables
from slack_sdk.errors import SlackApiError

# Database connection placeholder
db_connection = None

# Function to set the global database connection
def set_db_connection(connection):
    global db_connection
    db_connection = connection

# SQL to create the user_info table
create_tables_sql = """
CREATE TABLE IF NOT EXISTS responded_messages (
    id SERIAL PRIMARY KEY,
    message_ts VARCHAR(50) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_history (
    id SERIAL PRIMARY KEY,
    channel_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS entry_history (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    user_name VARCHAR(100) NOT NULL,
    entry_content TEXT NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_info (
    user_id VARCHAR(50) PRIMARY KEY,
    user_name VARCHAR(100) NOT NULL,
    last_interaction TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS groups (
    id SERIAL PRIMARY KEY,
    group_name VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS user_groups (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    group_id INT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES user_info(user_id),
    FOREIGN KEY (group_id) REFERENCES groups(id)
);

CREATE TABLE IF NOT EXISTS permissions (
    id SERIAL PRIMARY KEY,
    group_id INT NOT NULL,
    permission_name VARCHAR(100) NOT NULL,
    FOREIGN KEY (group_id) REFERENCES groups(id)
);
"""

# Function to execute a query
def execute_query(query, params=None, fetch=False):
    if db_connection is None:
        raise Exception("Database connection is not set.")
    with db_connection.cursor() as cursor:
        cursor.execute(query, params)
        if fetch:
            return cursor.fetchall()

# Create tables on startup
def create_tables():
    with db_connection.cursor() as cursor:
        cursor.execute(create_tables_sql)
        print("Tables created successfully")

# Function to add or update user info in the database
def upsert_user_info(user_id):
    try:
        user_info = variables.client.users_info(user=user_id)
        user_name = user_info["user"]["real_name"]

        # Insert or update user info in the database
        upsert_query = """
        INSERT INTO user_info (user_id, user_name, last_interaction)
        VALUES (%s, %s, NOW())
        ON CONFLICT (user_id)
        DO UPDATE SET user_name = EXCLUDED.user_name, last_interaction = NOW();
        """
        execute_query(upsert_query, (user_id, user_name))
        return user_name
    except SlackApiError as e:
        variables.app.logger.error(f"Error fetching user info: {e.response['error']}")
        return None
    
# Function to create a group
def create_group(group_name):
    insert_group_sql = """
    INSERT INTO groups (group_name)
    VALUES (%s)
    ON CONFLICT (group_name) DO NOTHING;
    """
    execute_query(insert_group_sql, (group_name,))
    print(f"Group '{group_name}' created successfully")

# Function to assign users from a file to a group
def assign_users_to_group_from_file(file_path, group_name):
    # Find the group_id for the given group_name
    group_id_query = "SELECT id FROM groups WHERE group_name = %s"
    group = execute_query(group_id_query, (group_name,), fetch=True)

    if group:
        group_id = group[0][0]

        try:
            # Open the file and read the user IDs
            with open(file_path, 'r') as file:
                user_ids_from_file = {line.strip() for line in file if line.strip()}

            # Fetch current user IDs assigned to the group
            current_user_ids_query = "SELECT user_id FROM user_groups WHERE group_id = %s"
            current_user_ids = {row[0] for row in execute_query(current_user_ids_query, (group_id,), fetch=True)}

            # Assign new users from the file
            for user_id in user_ids_from_file:
                if user_id not in current_user_ids:
                    insert_user_group_sql = """
                    INSERT INTO user_groups (user_id, group_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING;
                    """
                    execute_query(insert_user_group_sql, (user_id, group_id))
                    print(f"User '{user_id}' assigned to group '{group_name}'")

            # Remove users from the database that are no longer in the file
            for user_id in current_user_ids:
                if user_id not in user_ids_from_file:
                    delete_user_group_sql = """
                    DELETE FROM user_groups
                    WHERE user_id = %s AND group_id = %s;
                    """
                    execute_query(delete_user_group_sql, (user_id, group_id))
                    print(f"User '{user_id}' removed from group '{group_name}'")

        except FileNotFoundError:
            print(f"File '{file_path}' not found.")
        
    else:
        print(f"Group '{group_name}' does not exist.")

# Function to add a permission to a group
def add_permission_to_group(group_name, permission_name):
    group_id_query = "SELECT id FROM groups WHERE group_name = %s"
    group = execute_query(group_id_query, (group_name,), fetch=True)

    if group:
        group_id = group[0][0]
        insert_permission_sql = """
        INSERT INTO permissions (group_id, permission_name)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING;
        """
        execute_query(insert_permission_sql, (group_id, permission_name))
        print(f"Permission '{permission_name}' added to group '{group_name}'")
    else:
        print(f"Group '{group_name}' does not exist")

# Function to check if a user has permission
def check_user_permission(user_id, permission_name):
    query = """
    SELECT p.permission_name
    FROM permissions p
    JOIN user_groups ug ON p.group_id = ug.group_id
    WHERE ug.user_id = %s AND p.permission_name = %s
    """
    result = execute_query(query, (user_id, permission_name), fetch=True)
    return len(result) > 0