from typing import Any
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import snowflake.connector
import pandas as pd
from snowflake.core import Root
from dotenv import load_dotenv
import cortex_chat
import time
import requests # Still needed for initial Slack API interaction in upload_chart_to_slack if it remains here

# Import charting functions from the new file
from chart_utils import select_and_plot_chart, upload_chart_to_slack # We will modify upload_chart_to_slack to be passed app.client


# Set Matplotlib backend for server-side generation (can be removed if charting.py handles all plotting)
# import matplotlib
# matplotlib.use('Agg') # Moving this to charting.py

load_dotenv()

# --- Environment Variables ---
ACCOUNT = os.getenv("ACCOUNT")
HOST = os.getenv("HOST")
USER = os.getenv("DEMO_USER")
DATABASE = os.getenv("DEMO_DATABASE")
SCHEMA = os.getenv("DEMO_SCHEMA")
ROLE = os.getenv("DEMO_USER_ROLE")
WAREHOUSE = os.getenv("WAREHOUSE")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
AGENT_ENDPOINT = os.getenv("AGENT_ENDPOINT")
SEMANTIC_MODEL = os.getenv("SEMANTIC_MODEL")
SEARCH_SERVICE = os.getenv("SEARCH_SERVICE")
RSA_PRIVATE_KEY_PATH = os.getenv("RSA_PRIVATE_KEY_PATH")
MODEL = os.getenv("MODEL")

# --- Environment Variable Validation (Added for Robustness) ---
required_env_vars = ["ACCOUNT", "HOST", "DEMO_USER", "DEMO_DATABASE", "DEMO_SCHEMA", "DEMO_USER_ROLE", "WAREHOUSE", "SLACK_APP_TOKEN", "SLACK_BOT_TOKEN", "AGENT_ENDPOINT", "SEMANTIC_MODEL", "SEARCH_SERVICE", "RSA_PRIVATE_KEY_PATH", "MODEL"]
for var in required_env_vars:
    if not os.getenv(var):
        print(f"Error: Required environment variable '{var}' is not set. Please check your .env file.")
        exit(1) # Exit if essential environment variables are missing

DEBUG = False # Set to True for more verbose console output

# --- Initializes Slack App ---
app = App(token=SLACK_BOT_TOKEN)

# --- Global In-Memory Cache for SQL Queries ---
# WARNING: In a production environment, this should be replaced with a more robust,
# persistent, and thread-safe caching mechanism (e.g., Redis, database)
# to handle multiple concurrent users and bot restarts.
global_sql_cache = {}
SQL_SHOW_BUTTON_ACTION_ID = "show_full_sql_query_button"

# --- Slack Message Handlers ---

@app.message("hello")
def message_hello(message, say):
    build = """
Not a developer was stirring, all deep in the fight.
The code was deployed in the pipelines with care,
In hopes that the features would soon be there.

And execs, so eager to see the results,
Were prepping their speeches, avoiding the gulps.
When, what to my wondering eyes should appear,
But a slide-deck update, with a demo so clear!

And we shouted out to developers,
Let’s launch this build live and avoid any crash!
The demos they created, the videos they made,
Were polished and ready, the hype never delayed.
            """

    say(build)
    say(
        text = "Let's BUILD",
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f":snowflake: Let's BUILD!",
                }
            },
            get_hello_world_button_block()
        ]
    )

@app.event("message")
def handle_message_events(ack, body, say):
    try:
        ack()
        prompt = body['event']['text']
        say(
            text = "Snowflake Cortex AI is generating a response",
            blocks=[
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "plain_text",
                        "text": ":snowflake: Snowflake Cortex AI is generating a response. Please wait...",
                    }
                },
                {
                    "type": "divider"
                },
            ]
        )
        # Pass the full body to display_agent_response to extract channel_id
        response = ask_agent(prompt)
        display_agent_response(response, say, app.client, body) # Pass app.client and body
    except Exception as e:
        error_info = f"{type(e).__name__} at line {e.__traceback__.tb_lineno} of {__file__}: {e}"
        print(f"ERROR: {error_info}") # Use a clear ERROR prefix for logs
        say(
            text = "Request failed...",
            blocks=[
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "plain_text",
                        "text": f"An unexpected error occurred: {type(e).__name__}. Please try again later or contact support if the issue persists.",
                    }
                },
                {
                    "type": "divider"
                },
            ]
        )

# --- Agent Interaction ---

def ask_agent(prompt):
    """
    Sends the user prompt to the Cortex Chat Agent.
    """
    resp = CORTEX_APP.chat(prompt)
    return resp

# --- NEW: Helper for SQL display blocks ---
def get_sql_display_blocks(sql_query, show_full=False):
    """
    Generates Slack blocks for displaying SQL query, either as a button or full code.
    """
    if show_full:
        return [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {
                                "type": "text",
                                "text": "SQL Query:",
                                "style": {
                                    "bold": True
                                }
                            }
                        ]
                    },
                    {
                        "type": "rich_text_preformatted",
                        "elements": [
                            {
                                "type": "text",
                                "text": sql_query
                            }
                        ]
                    }
                ]
            }
        ]
    else:
        # Block to prompt showing the query
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "The underlying SQL query is available. Click to view."
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Show SQL Query",
                        "emoji": True
                    },
                    "action_id": SQL_SHOW_BUTTON_ACTION_ID
                }
            }
        ]

# --- Response Display and Charting Logic ---

def display_agent_response(content, say, app_client, original_body): # Added original_body parameter
    """
    Displays the agent's response, handling both SQL results (with charts)
    and unstructured text responses.
    """
    channel_id = original_body['event']['channel'] # Extract channel_id from original message body

    if content['sql']:
        sql = content['sql']

        df = pd.read_sql(sql, CONN)

        if DEBUG:
            print("Original DataFrame info:")
            df.info() # Debugging: Print DataFrame info to check dtypes

        # --- Robust Type Conversion for Plotting ---
        # Attempt to convert relevant columns to expected types before charting logic
        if len(df.columns) >= 2:
            try:
                # Try to convert the first column to datetime if it's an object/string
                if pd.api.types.is_object_dtype(df.iloc[:, 0]) or pd.api.types.is_string_dtype(df.iloc[:, 0]):
                    temp_col = pd.to_datetime(df.iloc[:, 0], errors='coerce')
                    if not temp_col.isna().all(): # Only convert if some values are valid datetimes
                        df[df.columns[0]] = temp_col
                        if DEBUG:
                            print(f"Converted column '{df.columns[0]}' to datetime where possible.")
            except Exception as e:
                if DEBUG:
                    print(f"Could not convert column '{df.columns[0]}' to datetime: {e}")
            
            # Iterate through all columns to convert to numeric if appropriate
            for i in range(len(df.columns)):
                try:
                    if pd.api.types.is_object_dtype(df.iloc[:, i]) or pd.api.types.is_string_dtype(df.iloc[:, i]):
                        temp_col = pd.to_numeric(df.iloc[:, i], errors='coerce')
                        # Convert if mostly numeric and not entirely NaN after coercion
                        if not temp_col.isna().all() and (temp_col.notna().sum() / len(temp_col) > 0.5):
                            df[df.columns[i]] = temp_col
                            if DEBUG:
                                print(f"Converted column '{df.columns[i]}' to numeric where possible.")
                    elif pd.api.types.is_numeric_dtype(df.iloc[:, i]):
                        # Ensure standard float type for plotting consistency
                        df[df.columns[i]] = df[df.columns[i]].astype(float)
                except Exception as e:
                    if DEBUG:
                        print(f"Could not convert column '{df.columns[i]}' to numeric: {e}")
        
        # --- Drop rows with NaN in numeric columns after conversion ---
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                if df[col].isnull().any():
                    df.dropna(subset=[col], inplace=True)
                    if DEBUG:
                        print(f"Dropped rows with NaN in numeric column '{col}'.")

        if DEBUG:
            print("\nDataFrame after type conversion info:")
            df.info() # Debugging: Print DataFrame info after conversion

            print("\nDataFrame head after conversion:")
            print(df.head()) # Debugging: Print head to see actual values and types

        # --- Prepare blocks for initial message ---
        initial_blocks = []

        # Handle Single-Row Answers Specifically
        if len(df) == 1:
            formatted_answer = ""
            for col in df.columns:
                formatted_answer += f"*{col.replace('_', ' ').title()}*: {df[col].iloc[0]}\n"
            
            initial_blocks.append({
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {
                                "type": "text",
                                "text": "Here's the specific information you requested:",
                                "style": {
                                    "bold": True
                                }
                            }
                        ]
                    },
                    {
                        "type": "rich_text_preformatted",
                        "elements": [
                            {
                                "type": "text",
                                "text": formatted_answer
                            }
                        ]
                    }
                ]
            })
        else:
            # Limit displayed rows and indicate truncation
            original_rows = len(df)
            display_df = df.head(10) # Limit to first 10 rows for display
            truncated_message = ""
            if original_rows > 10:
                truncated_message = "\n\n(Results truncated to 10 lines.)"

            # Display DataFrame as Text Table
            initial_blocks.append({
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_quote",
                        "elements": [
                            {
                                "type": "text",
                                "text": "Answer:",
                                "style": {
                                    "bold": True
                                }
                            }
                        ]
                    },
                    {
                        "type": "rich_text_preformatted",
                        "elements": [
                            {
                                "type": "text",
                                "text": f"{display_df.to_string()}{truncated_message}"
                            }
                        ]
                    }
                ]
            })
        
        # Add the SQL query button/placeholder block
        initial_blocks.extend(get_sql_display_blocks(sql_query=sql, show_full=False))

        # Send the initial message and capture its timestamp (ts)
        try:
            post_response = app_client.chat_postMessage(
                channel=channel_id,
                blocks=initial_blocks,
                text="Your query results are ready." # Fallback text
            )
            message_ts = post_response['ts']
            
            # Store the full SQL query in the global cache, keyed by message_ts
            global_sql_cache[message_ts] = sql

        except Exception as e:
            print(f"Error posting initial message to Slack: {e}")
            say(f"An error occurred while posting results: {e}")
            return


        # --- Dynamic Chart Selection Logic (sent as a follow-up message) ---
        chart_img_url = select_and_plot_chart(df, app_client) # Pass app_client to charting function
        if chart_img_url is not None:
            # Send chart as a new message, referencing the original for context if desired
            app_client.chat_postMessage(
                channel=channel_id,
                blocks=[
                    {
                        "type": "image",
                        "title": {
                            "type": "plain_text",
                            "text": "Chart"
                        },
                        "block_id": "image",
                        "slack_file": {
                            "url": f"{chart_img_url}"
                        },
                        "alt_text": "Chart"
                    }
                ]
            )
        else:
            if DEBUG:
                print("No suitable chart could be generated for the returned data.")
            app_client.chat_postMessage( # Inform user no chart was generated
                channel=channel_id,
                text="Note: No chart could be generated for this data due to its format or content."
            )
    else:
        # --- Handle Unstructured Text Responses ---
        say(
            text = "Answer:",
            blocks = [
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_quote",
                            "elements": [
                                {
                                    "type": "text",
                                    "text": f"Answer: {content['text']}",
                                    "style": {
                                        "bold": True
                                    }
                                }
                            ]
                        },
                        {
                            "type": "rich_text_quote",
                            "elements": [
                                {
                                    "type": "text",
                                    "text": f"* Citation: {content['citations']}",
                                    "style": {
                                        "italic": True
                                    }
                                }
                            ]
                        }
                    ]
                }
            ]
        )

# --- NEW: Action handler for "Show SQL Query" button ---
@app.action(SQL_SHOW_BUTTON_ACTION_ID)
def handle_show_sql_query(ack, body, client):
    ack() # Acknowledge the button click immediately

    message_ts = body['message']['ts']
    channel_id = body['channel']['id']
    
    # Retrieve the SQL query from the cache using the message's timestamp
    sql_query = global_sql_cache.get(message_ts)

    if not sql_query:
        # If SQL not found (e.g., bot restarted, cache cleared), inform the user ephemerally
        client.chat_postMessage(
            channel=channel_id,
            text="Sorry, I couldn't retrieve the SQL query for this message. It might have expired or been cleared.",
            thread_ts=message_ts # Reply in thread if message has one
        )
        return

    # Get the current blocks of the message that the user interacted with
    current_blocks = body['message']['blocks']
    
    # Filter out the "Show SQL Query" button block from the current blocks
    # We identify it by its type "section" and the action_id in its accessory
    updated_blocks = []
    for block in current_blocks:
        if (block.get("type") == "section" and 
            block.get("accessory", {}).get("type") == "button" and 
            block.get("accessory", {}).get("action_id") == SQL_SHOW_BUTTON_ACTION_ID):
            continue # Skip this block (the button)
        updated_blocks.append(block)
    
    # Add the full SQL query blocks to the end of the updated_blocks list
    updated_blocks.extend(get_sql_display_blocks(sql_query, show_full=True))

    # Update the original message in Slack with the new set of blocks
    try:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=updated_blocks,
            text="Your query results and SQL." # Fallback text for updated message
        )
    except Exception as e:
        print(f"Error updating message with SQL: {e}")
        client.chat_postMessage(
            channel=channel_id,
            text=f"An error occurred while displaying the query: {e}",
            thread_ts=message_ts
        )

    # Clean up the cache after the SQL has been displayed in the message
    if message_ts in global_sql_cache:
        del global_sql_cache[message_ts]


# --- Hello World Button Definitions (from previous request) ---

def get_hello_world_button_block():
    """
    Returns the Slack Block Kit structure for the "Hello World" button.
    This makes the button definition reusable and isolated.
    """
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Hello World",
                    "emoji": True
                },
                "style": "primary",
                "action_id": "hello_world_button" # Unique ID for this button action
            }
        ]
    }

@app.action("hello_world_button")
def handle_hello_world_button_click(ack, say):
    """
    Handles the click event for the "Hello World" button.
    """
    ack() # Acknowledge the button click immediately
    say("Hi!")


# --- Initialization and App Start ---

def init():
    """
    Initializes Snowflake connection and Cortex Chat Agent.
    """
    # Removed unused 'jwt' variable
    conn, cortex_app = None, None

    try:
        conn = snowflake.connector.connect(
            user=USER,
            authenticator="SNOWFLAKE_JWT",
            private_key_file=RSA_PRIVATE_KEY_PATH,
            account=ACCOUNT,
            warehouse=WAREHOUSE,
            role=ROLE,
            host=HOST
        )
        if not conn.rest.token:
            raise Exception("Snowflake connection unsuccessful: No token received.")
        print(">>>>>>>>>> Snowflake connection successful.")
    except Exception as e:
        print(f"ERROR: Failed to connect to Snowflake: {e}")
        exit(1) # Exit if Snowflake connection fails

    try:
        cortex_app = cortex_chat.CortexChat(
            AGENT_ENDPOINT,
            SEARCH_SERVICE,
            SEMANTIC_MODEL,
            MODEL,
            ACCOUNT,
            USER,
            RSA_PRIVATE_KEY_PATH
        )
        print(">>>>>>>>>> Cortex Chat Agent initialized.")
    except Exception as e:
        print(f"ERROR: Failed to initialize Cortex Chat Agent: {e}")
        exit(1) # Exit if Cortex Chat Agent initialization fails

    print(">>>>>>>>>> Init complete")
    return conn, cortex_app

if __name__ == "__main__":
    CONN, CORTEX_APP = init()
    Root = Root(CONN) # Assuming Root is used elsewhere or for Snowpark Session
    print("Starting SocketModeHandler...")
    SocketModeHandler(app, SLACK_APP_TOKEN).start()