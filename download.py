from typing import Any
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import snowflake.connector
import pandas as pd
from snowflake.core import Root
from dotenv import load_dotenv, find_dotenv
import cortex_chat
import time
import requests

# Import charting functions from the new file
from chart_utils import select_and_plot_chart, upload_chart_to_slack

# --- Environment Variable Loading ---
dotenv_path = find_dotenv()
if dotenv_path:
    load_dotenv(dotenv_path)
else:
    print("WARNING: .env file not found. Ensure it's in the script's directory or a parent. Relying on system environment variables.")

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

# --- Environment Variable Validation ---
required_env_vars = [
    "ACCOUNT", "HOST", "DEMO_USER", "DEMO_DATABASE", "DEMO_SCHEMA",
    "DEMO_USER_ROLE", "WAREHOUSE", "SLACK_APP_TOKEN", "SLACK_BOT_TOKEN",
    "AGENT_ENDPOINT", "SEMANTIC_MODEL", "SEARCH_SERVICE", "RSA_PRIVATE_KEY_PATH", "MODEL"
]

for var in required_env_vars:
    value = os.getenv(var)
    if not value:
        print(f"FATAL ERROR: Required environment variable '{var}' is NOT set. Please check your .env file or system environment.")
        exit(1)

# --- Initialize Slack App ---
try:
    app = App(token=SLACK_BOT_TOKEN)
except Exception as e:
    print(f"FATAL ERROR: Failed to initialize Slack App: {e}")
    exit(1)

# --- Global In-Memory Caches ---
global_sql_cache = {}
global_dataframe_cache = {}
SQL_SHOW_BUTTON_ACTION_ID = "show_full_sql_query_button"
DOWNLOAD_DATA_BUTTON_ACTION_ID = "download_data_button"

# --- Global Connection Objects ---
CONN = None
CORTEX_APP = None

# --- Helper function to get a fresh Snowflake connection ---
def get_snowflake_connection():
    """
    Establishes and returns a new Snowflake connection using JWT authentication.
    """
    try:
        # Read private key file to ensure it's accessible
        with open(RSA_PRIVATE_KEY_PATH, 'rb') as key_file:
            private_key_content = key_file.read()
            if not private_key_content:
                raise ValueError(f"Private key file '{RSA_PRIVATE_KEY_PATH}' is empty.")

        conn = snowflake.connector.connect(
            user=USER,
            authenticator="SNOWFLAKE_JWT",
            private_key_file=RSA_PRIVATE_KEY_PATH,
            account=ACCOUNT,
            warehouse=WAREHOUSE,
            role=ROLE,
            host=HOST
        )

        # Test connection with a simple query
        with conn.cursor() as cursor:
            cursor.execute("SELECT CURRENT_VERSION()")
            cursor.fetchone()

        return conn
    except Exception as e:
        print(f"ERROR: Failed to connect to Snowflake: {e}")
        raise

# --- Helper function to initialize Cortex Chat Agent ---
def get_cortex_chat_agent():
    """
    Initializes and returns a new Cortex Chat Agent.
    """
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
        return cortex_app
    except Exception as e:
        print(f"ERROR: Failed to initialize Cortex Chat Agent: {e}")
        raise

# --- Agent Interaction ---
def ask_agent(prompt):
    """
    Sends the user prompt to the Cortex Chat Agent.
    """
    resp = CORTEX_APP.chat(prompt)
    return resp

# --- Enhanced DataFrame formatting for Slack ---
def format_dataframe_for_slack(df, max_rows=10, max_col_width=20):
    """
    Enhanced DataFrame formatting for better Slack display
    """
    display_df = df.head(max_rows)
    
    # Truncate long column values for better display
    formatted_df = display_df.copy()
    for col in formatted_df.columns:
        if formatted_df[col].dtype == 'object':
            formatted_df[col] = formatted_df[col].astype(str).str[:max_col_width]
            # Add ellipsis for truncated values
            mask = formatted_df[col].str.len() == max_col_width
            formatted_df.loc[mask, col] = formatted_df.loc[mask, col] + "..."
    
    # Format numbers nicely
    for col in formatted_df.columns:
        if pd.api.types.is_numeric_dtype(formatted_df[col]):
            if formatted_df[col].dtype in ['float64', 'float32']:
                # Round floats to 2 decimal places
                formatted_df[col] = formatted_df[col].round(2)
    
    # Create the formatted string with better spacing
    table_string = formatted_df.to_string(
        index=False,
        max_cols=None,
        max_colwidth=max_col_width,
        justify='left'
    )
    
    original_rows = len(df)
    if original_rows > max_rows:
        table_string += f"\n\n📊 Showing {max_rows} of {original_rows} total rows"
    
    return table_string

# --- Helper for SQL display blocks ---
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

# --- Helper for Download Data button block ---
def get_download_data_button_block():
    """
    Returns the Slack Block Kit structure for the "Download Data" button.
    """
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "Download the complete result set."
        },
        "accessory": {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Download Data",
                "emoji": True
            },
            "action_id": DOWNLOAD_DATA_BUTTON_ACTION_ID
        }
    }

# --- Response Display and Charting Logic ---
def display_agent_response(content, say, app_client, original_body):
    """
    Displays the agent's response, handling both SQL results (with charts)
    and unstructured text responses.
    """
    channel_id = original_body['event']['channel']

    if content['sql']:
        sql = content['sql']
        df = pd.read_sql(sql, CONN)

        # --- Type Conversion for Plotting ---
        if len(df.columns) >= 2:
            try:
                if pd.api.types.is_object_dtype(df.iloc[:, 0]) or pd.api.types.is_string_dtype(df.iloc[:, 0]):
                    temp_col = pd.to_datetime(df.iloc[:, 0], errors='coerce')
                    if not temp_col.isna().all():
                        df[df.columns[0]] = temp_col
            except Exception:
                pass

            for i in range(len(df.columns)):
                try:
                    if pd.api.types.is_object_dtype(df.iloc[:, i]) or pd.api.types.is_string_dtype(df.iloc[:, i]):
                        temp_col = pd.to_numeric(df.iloc[:, i], errors='coerce')
                        if not temp_col.isna().all() and (temp_col.notna().sum() / len(temp_col) > 0.5):
                            df[df.columns[i]] = temp_col
                    elif pd.api.types.is_numeric_dtype(df.iloc[:, i]):
                        df[df.columns[i]] = df[df.columns[i]].astype(float)
                except Exception:
                    pass

        # --- Drop rows with NaN in numeric columns after conversion ---
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                if df[col].isnull().any():
                    df.dropna(subset=[col], inplace=True)

        # --- Prepare blocks for initial message ---
        initial_blocks = []

        # Handle Empty Results
        if len(df) == 0:
            initial_blocks.append({
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {
                                "type": "text",
                                "text": "📭 No Results Found",
                                "style": {
                                    "bold": True
                                }
                            }
                        ]
                    },
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {
                                "type": "text",
                                "text": "Your query executed successfully but returned no matching records. You might want to try adjusting your search criteria or checking if the data exists."
                            }
                        ]
                    }
                ]
            })
        # Handle Single-Row Answers Specifically
        elif len(df) == 1:
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
            # Enhanced table display
            formatted_table = format_dataframe_for_slack(df)
            
            initial_blocks.append({
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {
                                "type": "text",
                                "text": "📋 Query Results:",
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
                                "text": formatted_table
                            }
                        ]
                    }
                ]
            })

        # Add the SQL query button/placeholder block (always show)
        initial_blocks.extend(get_sql_display_blocks(sql_query=sql, show_full=False))

        # Add the Download Data button block only if there's data
        if len(df) > 0:
            initial_blocks.append(get_download_data_button_block())

        # Send the initial message and capture its timestamp (ts)
        try:
            post_response = app_client.chat_postMessage(
                channel=channel_id,
                blocks=initial_blocks,
                text="Your query results are ready."
            )
            message_ts = post_response['ts']

            # Cache storage
            global_sql_cache[message_ts] = sql
            global_dataframe_cache[message_ts] = df

        except Exception as e:
            print(f"ERROR: Error posting initial message to Slack: {e}")
            say(f"An error occurred while posting results: {e}")
            return

        # --- Dynamic Chart Selection Logic (only for non-empty results) ---
        if len(df) > 0:
            chart_img_url = select_and_plot_chart(df, app_client)
            if chart_img_url is not None:
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
                app_client.chat_postMessage(
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

# --- Slack Message Handlers ---
@app.event("message")
def handle_message_events(ack, body, say):
    global CONN
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

        # Test connection liveness with a simple query
        try:
            with CONN.cursor() as cursor:
                cursor.execute("SELECT 1")
        except (snowflake.connector.errors.ProgrammingError, snowflake.connector.errors.InterfaceError):
            try:
                if CONN:
                    CONN.close()
                CONN = get_snowflake_connection()
            except Exception as re_conn_err:
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
                                "text": f"Sorry, I'm having trouble connecting to Snowflake right now. Please try again later.",
                            }
                        },
                        {
                            "type": "divider"
                        },
                    ]
                )
                return

        response = ask_agent(prompt)
        display_agent_response(response, say, app.client, body)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
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

# --- Action handler for "Show SQL Query" button ---
@app.action(SQL_SHOW_BUTTON_ACTION_ID)
def handle_show_sql_query(ack, body, client):
    ack()

    message_ts = body['message']['ts']
    channel_id = body['channel']['id']

    sql_query = global_sql_cache.get(message_ts)

    if not sql_query:
        client.chat_postMessage(
            channel=channel_id,
            text="Sorry, I couldn't retrieve the SQL query for this message. It might have expired or been cleared.",
            thread_ts=message_ts
        )
        return

    current_blocks = body['message']['blocks']

    updated_blocks = []
    for block in current_blocks:
        if (block.get("type") == "section" and
            block.get("accessory", {}).get("type") == "button" and
            block.get("accessory", {}).get("action_id") == SQL_SHOW_BUTTON_ACTION_ID):
            continue
        updated_blocks.append(block)

    updated_blocks.extend(get_sql_display_blocks(sql_query, show_full=True))

    try:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=updated_blocks,
            text="Your query results and SQL."
        )
    except Exception as e:
        print(f"Error updating message with SQL: {e}")
        client.chat_postMessage(
            channel=channel_id,
            text=f"An error occurred while displaying the query: {e}",
            thread_ts=message_ts
        )

# --- Download Data Handler ---
@app.action(DOWNLOAD_DATA_BUTTON_ACTION_ID)
def handle_download_data(ack, body, client):
    ack()

    message_ts = body['message']['ts']
    channel_id = body['channel']['id']

    df = global_dataframe_cache.get(message_ts)

    if df is None:
        client.chat_postMessage(
            channel=channel_id,
            text="Sorry, the data for this download has expired or could not be found. Please run the query again.",
            thread_ts=message_ts
        )
        return

    if df.empty:
        client.chat_postMessage(
            channel=channel_id,
            text="The query returned no data, so no file was generated.",
            thread_ts=message_ts
        )
        # Clean up cache for empty results
        if message_ts in global_dataframe_cache:
            del global_dataframe_cache[message_ts]
        if message_ts in global_sql_cache:
            del global_sql_cache[message_ts]
        return

    try:
        csv_content = df.to_csv(index=False)
        filename = f"query_results_{int(time.time())}.csv"

        # Try files_upload_v2 first
        success = False
        try:
            api_response = client.files_upload_v2(
                channel=channel_id,
                content=csv_content,
                filename=filename,
                title="Query Results",
                initial_comment="Here is your complete data set:",
                thread_ts=message_ts
            )
            
            if api_response.get("ok"):
                success = True
                
        except Exception:
            pass

        # Fallback to legacy files_upload if v2 fails
        if not success:
            try:
                api_response = client.files_upload(
                    channels=channel_id,
                    content=csv_content,
                    filename=filename,
                    title="Query Results",
                    initial_comment="Here is your complete data set:",
                    thread_ts=message_ts
                )
                
                if api_response.get("ok"):
                    success = True
                    
            except Exception:
                pass

        if success:
            # Only delete cache on successful upload
            if message_ts in global_dataframe_cache:
                del global_dataframe_cache[message_ts]
            if message_ts in global_sql_cache:
                del global_sql_cache[message_ts]
        else:
            error_msg = api_response.get('error', 'Unknown upload error') if 'api_response' in locals() else 'Upload failed'
            client.chat_postMessage(
                channel=channel_id,
                text=f"❌ File upload failed: `{error_msg}`. Please check bot permissions (`files:write` scope required).",
                thread_ts=message_ts
            )

    except Exception as e:
        client.chat_postMessage(
            channel=channel_id,
            text=f"An unexpected error occurred while preparing your download: `{type(e).__name__}: {e}`",
            thread_ts=message_ts
        )

# --- Hello World Button Handler ---
@app.action("hello_world_button")
def handle_hello_world_button_click(ack, say):
    ack()
    say("Hi!")

# --- Initialization and App Start ---
def init_global_connections():
    """
    Initializes global Snowflake connection and Cortex Chat Agent.
    """
    global CONN, CORTEX_APP
    try:
        CONN = get_snowflake_connection()
        Root(CONN)
        CORTEX_APP = get_cortex_chat_agent()
        print("Global connections initialized successfully.")
    except Exception as e:
        print(f"FATAL ERROR during initial connection setup: {e}")
        exit(1)

if __name__ == "__main__":
    if not SLACK_BOT_TOKEN:
        print("FATAL ERROR: SLACK_BOT_TOKEN is not set. Exiting.")
        exit(1)
    if not SLACK_APP_TOKEN:
        print("FATAL ERROR: SLACK_APP_TOKEN is not set. Exiting.")
        exit(1)

    init_global_connections()

    print("Starting Slack bot...")
    try:
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        handler.start()
    except Exception as e:
        print(f"FATAL ERROR: SocketModeHandler failed to start: {e}")
        exit(1)